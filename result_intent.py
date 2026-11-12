"""The question's intent, for the result-shape rules (FASTAPI-TEXT2SQL-353).

The shape rules of result_shape.py read the SQL and the rows, and that is not enough: once
the SQL exists, "Harry Potter films with their duration" and "Harry Potter films" can produce
the same projection, and "the Godfather trilogy in order" the same ORDER BY as a plain list.
What the user asked for is in the question only. This module carries that reading.

Three sources, in order of trust, recorded in `source`:

- "llm": the answer-entity classifier (text2sql.f_classify_result_intent), one gpt-6-luna call
  run in parallel with SQL generation, returns `{entity, task, focus, requested_view}`.
- "rules": EN/FR keyword rules, used when the call failed, returned no usable task, was
  skipped (cache hit on an older row, fast path, identity re-entry), or when
  RESULT_ENTITY_PARALLEL / RESULT_INTENT is off.
- "none": no question to read.

The intent is a prior for the shape rules (-354), never an order: it never changes the SQL.
Pure module, no I/O, so checks/test-result-intent.py runs it offline.

The task vocabulary is the closed set of the evaluation grammar (text2sql-eval
result_shape_assertions.INTENT_TASKS: list, value, rank, count, compare, sequence, trend, and
verdict since phase 2 lot B) plus relate, which the bank does not assert yet. The ticket's `lookup` and `describe` are
folded into `list`: Philippe labelled the identifier lookups 79 and 80 `list` on 2026-11-08,
since a lookup returns entity rows asked for themselves, with no quantity.
"""

import json
import re

INTENT_TASKS = ("list", "value", "rank", "count", "compare", "sequence", "trend", "relate", "verdict")
# "share" (phase 2 lot C): the question asks for parts of a whole ("what share of", "split", "as a
# pie", "repartition", "en camembert"). Only the keyword rules read it, whatever the source: the
# classifier's vocabulary predates it (core_intent below).
# "scatter" (phase 3 lot A): the question names a scatter plot ("scatter plot", "nuage de points"),
# or sets two quantities against each other ("the budget against the revenue", "versus", "en
# fonction de", "a link between the runtime and the rating"). Read by the rules whatever the
# source, as "share": the classifier reads "plot" as chart, which drew bars of one quantity.
# "map" (phase 3 lot B): the question asks for a map ("on a world map", "map of", "sur une carte",
# "carte des"). Read by the rules whatever the source, as "share"; it only moves a result whose
# rows are countries (result_shape: the map is offered where the flag list is), so a map asked of
# anything else changes nothing.
# "hierarchy" (phase 3 lot C): the question asks for the rows grouped under a parent ("grouped by
# trilogy", "by region", "with the films of each", "regroupes par region", "par trilogie"). Read by
# the rules whatever the source, over the classifier's "" only; it only moves entity rows that carry
# a group column (result_shape: two groups and four leaves at least), so it changes nothing else.
# "chain" (phase 3 lot E): the question asks for a lineage of adaptations or remakes ("the chain of
# remakes behind", "trace X back to its source", "which films descend from", "filiation", "remonte
# jusqu'a"). Read by the rules whatever the source, over the classifier's "" only, from the strong
# lineage words of rules_lineage below; the weak ones ("based on", "adapte de") name a source, not a
# lineage, and set no view. It only moves a result that carries summary_facts.chain, which the API's
# lineage walk adds (result_chain.py), so it changes nothing in an offline census.
REQUESTED_VIEWS = ("table", "chart", "cards", "share", "scatter", "map", "hierarchy", "chain")

# Canonical focus names -> the column-name pattern of the projected column that carries it.
# The unit patterns of result_shape.py cover runtime, money, ratio and counts; the rest are
# the plain columns of T2S-tables.sql. Order matters only for readability: a focus maps to
# every projected column its pattern matches.
_FOCUS_COLUMNS = {
    "runtime": r"RUNTIME|DURATION|_MINUTES?\b",
    "budget": r"BUDGET",
    "revenue": r"REVENUE|GROSS|BOX_?OFFICE|EARNING",
    "profit": r"PROFIT|BENEFIT",
    "seasons": r"SEASON",
    "episodes": r"EPISODE",
    "rating": r"RATING|VOTE_AVERAGE|SCORE|NOTE",
    "votes": r"VOTE_COUNT|IMDB_VOTES|\bVOTES\b",
    "popularity": r"POPULARITY",
    "count": r"^COUNT|_COUNT\b|^NB_|NUMBER_OF|^N_|^TOTAL$|^CNT",
    "birth": r"BIRTH",
    "death": r"DEATH",
    "age": r"\bAGE\b|_AGE\b",
    "release_date": r"RELEASE|^DAT_|_DATE$|_YEAR$|^YEAR$",
}
_FOCUS_COLUMN_RES = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in _FOCUS_COLUMNS.items()}

# EN/FR words -> canonical focus. The classifier is asked for canonical names, so this table
# mostly serves the rules and a model that answers with the question's own word anyway.
# Matched on whole words, accents folded.
_FOCUS_SYNONYMS = {
    "runtime": ("runtime", "duration", "length", "long", "longest", "longer", "shortest", "minutes",
                "how long", "duree", "durees", "longs", "longues", "plus long", "plus longs",
                "temps", "combien de temps"),
    "budget": ("budget", "budgets", "cost", "costs", "costliest", "expensive", "cout", "couts"),
    "revenue": ("revenue", "revenues", "box office", "box-office", "gross", "grossing", "grossed",
                "earnings", "earned", "recette", "recettes", "revenus", "rapporte", "rapportes",
                "rapporter"),
    "profit": ("profit", "profits", "benefice", "benefices"),
    "seasons": ("season", "seasons", "saison", "saisons"),
    "episodes": ("episode", "episodes"),
    "rating": ("rating", "ratings", "rated", "imdb rating", "score", "note", "notes", "notes imdb",
               "note imdb", "mieux notes", "mieux notees", "best rated"),
    "votes": ("votes", "vote count"),
    "popularity": ("popularity", "popular", "popularite", "populaire", "populaires"),
    "birth": ("birth", "born", "birth year", "naissance", "ne", "nee", "nes", "nees"),
    "death": ("death", "died", "deces", "mort", "morts"),
    "age": ("age", "old", "oldest", "youngest", "ages"),
    # "the most films" names a count, not a stored rating: "which countries have produced the
    # most TV series" is ordered on a stored SERIE_COUNT, a default sort key, and only the
    # focus tells the ranking from the default order (2577).
    "count": ("most films", "most movies", "most feature films", "most series",
              "most tv series", "most shows", "le plus de films", "le plus de series", "le plus de longs metrages",
              "plus de films", "plus de series"),
    "release_date": ("release date", "release year", "date de sortie", "annee de sortie"),
}


def _fold(text):
    """Lowercase and strip French accents, so the rules read one spelling."""
    table = str.maketrans("àâäáãéèêëíìîïóòôöõúùûüçœæ’", "aaaaaeeeeiiiiooooouuuucoe'")
    return (text or "").lower().translate(table)


def _word_re(words):
    return re.compile(r"(?<![a-z0-9])(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + r")(?![a-z0-9])")


_FOCUS_SYNONYM_RES = {name: _word_re(words) for name, words in _FOCUS_SYNONYMS.items()}


def canonical_focus(words):
    """Map focus words (canonical names or EN/FR words) to canonical focus names, in order."""
    out = []
    for word in words or []:
        folded = _fold(str(word)).strip()
        if not folded:
            continue
        key = folded.replace(" ", "_")
        if key in _FOCUS_COLUMNS:
            name = key
        else:
            name = next((n for n, rx in _FOCUS_SYNONYM_RES.items() if rx.search(folded)), None)
        if name and name not in out:
            out.append(name)
    return out


def focus_columns(focus, result_columns):
    """Return the projected column names that carry the focus, in projection order.

    `result_columns` is result_shape's `columns` list ({name, role, unit}); only metric and
    date columns qualify, so an entity's title can never be the focus.
    """
    names = canonical_focus(focus)
    if not names or not result_columns:
        return []
    out = []
    for column in result_columns:
        name = str(column.get("name") or "")
        if column.get("role") not in ("metric", "date"):
            continue
        if any(_FOCUS_COLUMN_RES[f].search(name) for f in names if f in _FOCUS_COLUMN_RES) and name not in out:
            out.append(name)
    return out


# --- Keyword rules (the fallback) ---------------------------------------------------------
# Checked in this order; first match wins. Written against the folded question.
_COMPARE_RE = re.compile(
    r"\bcompare|\bcomparison\b|\bversus\b|\bvs\.?\s|\bwhich (?:one )?(?:is|was|has|had|made|grossed|earned|lasts?)\b.*\bor\b"
    r"|\bwho (?:has|had|made|directed|won)\b.*\bor\b|\bcompar|\blequel\b|\blaquelle\b"
    r"|\bqui a\b.*\bou\b|\bentre\b.*\bet\b.*\ble plus\b|\bmore \w+ than\b|\bplus de \w+ que\b")
_TREND_RE = re.compile(
    r"\bper (?:year|decade)\b|\beach (?:year|decade)\b|\bby (?:year|decade)\b|\bevery year\b|\bover the (?:years|decades)\b"
    r"|\bpar (?:an|annee|decennie)\b|\bchaque (?:annee|decennie)\b|\bau fil des (?:ans|annees|decennies)\b|\bevolution\b")
_SEQUENCE_RE = re.compile(
    r"\bin order\b|\bchronolog|\brelease order\b|\border of release\b|\bfirst to (?:the )?(?:last|latest|most recent)\b"
    r"|\bfrom (?:his|her|their|its|the) first\b|\bwatch order\b|\bin what order\b|\bwhich order\b|\bdans l'ordre\b|\bpar ordre de sortie\b|\bordre chronologique\b"
    r"|\bdu premier au (?:dernier|plus recent)\b|\bdans quel ordre\b|\bdu plus ancien au plus recent\b|\boldest to (?:the )?newest\b")
_RANK_RE = re.compile(
    r"\btop\s*\d*\b|\bmost\b|\bhighest\b|\bbest\b|\blongest\b|\bshortest\b|\bbiggest\b|\blargest\b|\bworst\b|\blowest\b"
    r"|\b(?:rank|ranked|ranking)\b|\bfrom most to least\b|\ble plus\b|\bles plus\b|\ble moins\b|\bles moins\b|\bmieux note"
    r"|\bplus gros\b|\bclasse\b|\bclassement\b|\bdu plus au moins\b|\bles (?:\d+|dix|cinq|vingt|trois) premier")
# Phrases that look like a superlative and are not one: the end of a sequence ("from the first
# to the most recent") and award names ("Best Picture"). Removed before the rank test only.
_NOT_RANK_RE = re.compile(
    r"\b(?:first|premier) (?:to|au) (?:the )?(?:most recent|latest|plus recent)\b|\bdu plus ancien au plus recent\b"
    r"|\boldest to (?:the )?newest\b|\bbest (?:picture|film|director|actor|actress|supporting \w+|original \w+|adapted \w+"
    r"|foreign \w+|international \w+|animated \w+|documentary|cinematography|score|screenplay)\b|\bmeilleur(?:e)? (?:film|realisat|acteur|actrice)")
_VALUE_RE = re.compile(
    r"\btotal\b|\baverage\b|\bmean\b|\bsum\b|\bcombined\b|\bcumul|\baltogether\b|\bmoyenn?e?\b|\btotale?s?\b|\bcumulee?s?\b"
    r"|\bhow long\b|\bcombien de temps\b|\bhow many (?:minutes|hours|seasons|episodes)\b|\bcombien (?:de minutes|d'heures|de saisons|d'episodes)\b"
    r"|\bcombien (?:de saisons|d'episodes) compte\b|\bwith (?:their|its|the) (?:\w+ )?(?:runtime|duration|budget|revenue|box office|rating|imdb rating|seasons|episodes)\b"
    r"|\b(?:runtime|duration|budget|revenue|rating) of each\b|\bavec (?:la|le|les|leur|leurs) (?:\w+ )?(?:duree|budget|recette|recettes|note|notes|saisons|episodes)\b"
    r"|\bde chacun(?:e)?\b|\bpour chaque\b|\bof each\b|\bfor each\b|\bhow much\b|\bcombien a coute\b|\bwhat is the (?:runtime|budget|revenue|rating)\b")
# A question asking when (phase 2 lot A, the timeline): a date per item, so a value task whose
# focus is the release date. "when"/"quand" only at the start, so "films released when X was
# alive" is not one.
_WHEN_RE = re.compile(
    r"^(?:when|quand)\b|\bin (?:which|what) years?\b|\bwhat year\b|\ben quelles? annees?\b")
# "long metrage" is a format, not a length: "les longs metrages de Miyazaki" named the runtime.
_NOT_FOCUS_RE = re.compile(r"\blongs?[ -]metrages?\b")
_COUNT_RE = re.compile(r"\bhow many\b|\bnumber of\b|\bcount\b|\bcombien\b|\bnombre de\b")
_VERDICT_RE = re.compile(r"^(?:did|does|do|is|was|were|are|has|have|had|can)\s|^(?:est-ce qu|est-ce que)\b")
# Phase 2 lot B. A request worded as a question is not a yes/no question ("Can you show me the
# Kubrick films?", "Pouvez-vous ..."), and French asks yes/no by inversion ("Spielberg a-t-il
# realise Jaws ?", "Titanic est-il plus long qu'Avatar ?") when no question word asks for
# something else ("Quels films Spielberg a-t-il realises ?" is a list).
_NOT_VERDICT_RE = re.compile(
    r"^(?:can|could|would|will) (?:you|i|we)\b|^do you\b|^(?:est-ce que|est-ce qu) (?:tu|vous)\b"
    r"|^(?:peux|pouvez|pourrais|pourriez|veux|voulez)[- ]")
_FR_INVERSION_RE = re.compile(r"\b\w+-(?:t-)?(?:il|elle|ils|elles)\b")
_FR_QUESTION_WORD_RE = re.compile(
    r"\b(?:qui|quoi|quel|quelle|quels|quelles|lequel|laquelle|lesquels|lesquelles|quand|comment|combien|pourquoi)\b|^ou\b|^qu'|^que\b")
_RELATE_RE = re.compile(r"\bconnected\b|\brelationship between\b|\bin common\b|\bboth\b.*\band\b|\bpoint commun\b|\ben commun\b|\blien entre\b")
# Phase 3 lot A. A scatter named as such, whatever else the question says.
_SCATTER_VIEW_RE = re.compile(
    r"\bscatter\s*(?:plot|chart|graph|diagram)?s?\b|\bscatterplot\b|\bnuages? de points\b|\ben nuage\b"
    r"|\bdiagramme de dispersion\b|\bgraphique de dispersion\b")
# Two quantities set against each other: a scatter only when the question names two of them
# (rules_focus), so "films against the war" or "Alien versus Predator" never reads as one.
_SCATTER_RELATION_RE = re.compile(
    r"\bagainst\b|\bversus\b|\bvs\.?(?=\s)|\ben fonction d|\bpar rapport (?:a|au|aux)\b|\bcorrelat|\bcorrelation\b"
    r"|\blink between\b|\brelationship between\b|\brelation between\b|\brelate\b|\brelated to\b"
    r"|\blien entre\b|\brapport entre\b|\brelation entre\b")
_VIEW_RES = (
    ("table", re.compile(r"\bas a table\b|\bin a table\b|\btabular\b|\ben tableau\b|\bsous forme de tableau\b|\bdans un tableau\b")),
    # Phase 2 lot C: parts of a whole. Before "chart", so "as a pie chart" is the share form.
    ("share", re.compile(
        r"\b(?:as|in|on) a (?:pie|donut|doughnut)\b|\bpie[ -]chart\b|\bwhat (?:share|proportion|percentage|fraction)\b"
        r"|\b(?:the )?(?:share|proportion|percentage) of\b|\bsplit\b|\bbreakdown\b|\bbroken down\b"
        r"|\b(?:donut|doughnut) (?:chart|graph)\b|\ben (?:beignet|anneau|secteurs)\b|\b(?:diagramme|graphique) (?:circulaire|en secteurs)\b"
        r"|\ben camembert\b|\bcamembert\b|\brepartition\b|\bse repartiss|\bquelle (?:part|proportion)\b|\bquel pourcentage\b"
        r"|\b(?:la )?(?:part|proportion|pourcentage) (?:des|de|du|d')")),
    # Phase 3 lot B: a map. Before "chart", so "plot them on a map" is the map. A question that
    # starts with "map" names the form ("Map of the filming locations", "Map the countries...");
    # mid-sentence only "a/the map of" does, so a title such as "The Map of Tiny Perfect Things"
    # can read as one, harmless on rows that are not countries. "en cartes" stays cards.
    ("map", re.compile(
        r"\bon (?:a|the) (?:world |interactive )?map\b|\bworld ?map\b|\b(?:as|in|into|onto|with) a map\b"
        r"|^(?:show (?:me )?|draw (?:me )?)?(?:a |the )?map\b|\b(?:a|the) map (?:of|showing)\b|\bmap out\b|\bmapped\b"
        r"|\bsur (?:une|la) carte\b|\bcarte du monde\b|\bplanisphere\b|\ben carte\b|\bsous forme de carte\b"
        r"|^(?:montre(?:-moi)? |dessine(?:-moi)? )?(?:une |la )?carte (?:des?|du|d')|\b(?:une|la) carte (?:des?|du|d')"
        r"|\bcartographi")),
    ("chart", re.compile(r"\bas a (?:bar )?(?:chart|graph)\b|\bbar chart\b|\bplot\b|\ben graphique\b|\bsous forme de graphique\b|\bhistogramme\b")),
    ("cards", re.compile(r"\bas cards\b|\bwith (?:the )?posters\b|\ben cartes\b|\bavec (?:les )?affiches\b")),
    # Phase 3 lot C: a grouping under a parent. Last, so an explicit table, chart or cards wins.
    # "by" or "par" alone is no grouping ("films by Nolan", "realise par"): only before the name
    # of a parent level, or in "grouped by", "regroupes par", "with the films of each".
    ("hierarchy", re.compile(
        r"\bgrouped (?:by|under|into)\b|\bgroup(?:ed)? (?:them |it |these )?by\b|\borgani[sz]ed (?:by|into)\b"
        r"|\barranged by\b|\bsorted into\b|\bbroken (?:up )?into\b"
        r"|\bby (?:trilogy|trilogies|saga|franchise|collection|universe|region|state|nation|province|county|department|phase)\b"
        r"|\bwith the \w+ (?:\w+ )?of each\b|\beach with (?:its|their)\b|\bunder each\b"
        r"|\bfor each (?:of the )?\w+(?: \w+)?,? (?:its|their|his|her)\b"
        r"|\b(?:re)?groupee?s? (?:par|sous)\b|\branges? par\b|\brangees? par\b|\borganisee?s? par\b|\breparti(?:e|s|es)? (?:par|en)\b"
        r"|\bpar (?:trilogie|saga|franchise|collection|univers|region|etat|nation|province|comte|departement)\b"
        r"|\bavec (?:les|ses|leurs) \w+ (?:\w+ )?de chacune?\b|\bpour chaque \w+(?: \w+)?,? (?:ses|son|sa|leurs?)\b")),
)

# A pie asked by name ("as a pie", "pie chart", "donut chart", "en camembert", "en beignet",
# "diagramme circulaire"). Every match is also a "share" word above, so the representation stays
# share-bar; this only sets summary_facts.share.shape to "pie" (result_shape.classify_result), the
# form the fronts draw the parts in. "pie" alone is not enough: "American Pie" is a title.
_PIE_RE = re.compile(
    r"\b(?:as|in|on) a (?:pie|donut|doughnut)\b|\bpie[ -]chart\b|\b(?:donut|doughnut) (?:chart|graph)\b"
    r"|\bcamembert\b|\ben (?:beignet|anneau|secteurs)\b|\b(?:diagramme|graphique) (?:circulaire|en secteurs)\b")


def rules_share_shape(question):
    """"pie" when the question asks for the parts as a pie or a donut, else "bar"."""
    return "pie" if _PIE_RE.search(_fold(question)) else "bar"


def _share_shape_key(question):
    """{"share_shape": "pie"} when the question asks for a pie, else nothing, so the intent keeps
    its four keys for every other question. The cache stores only those four (dumps_for_cache): the
    shape is read again from the question on every request, cache hit included."""
    return {"share_shape": "pie"} if question and rules_share_shape(question) == "pie" else {}


# Phase 3 lot E: lineage wording, read on the folded question. STRONG words ask for the lineage
# itself (a chain, a descent, a trace back to the origin) and set requested_view "chain"; WEAK words
# name one source ("based on", "adapted from", "d'apres") and only let the API walk from a work the
# question names. The direction: UP toward the sources, DOWN toward the works made from it; both
# when the question asks both ways or says neither ("the remake lineage of", "filiation").
_LINEAGE_STRONG_RE = re.compile(
    r"\blineages?\b|\bdescend(?:s|ed|ants?)?\b|\bchain of (?:remakes|adaptations)\b|\bremakes? of remakes?\b"
    r"|\bremake by remake\b|\badaptation by adaptation\b|\btrace\b.*\bback\b|\bback to (?:its|their|the) (?!future\b)\w+"
    r"|\bfamily tree\b|\bcomes? from\b.*\b(?:novel|book|play|film|movie|work)\b"
    r"|\b(?:novel|book|play|film|movie|work) (?:it|they) (?:\w+ )?comes? from\b|\breach(?:ed|es)? the screen\b"
    r"|\ba remake of\b|\bremake of\b|\bremakes of\b|\bremade\b|\bremakes? (?:included|behind)\b"
    r"|\bfiliation\b|\bdescendance\b|\bdescend(?:ent|ants)?\b|\blignee\b|\bgenealogi|\barbre genealogique\b"
    r"|\bremonte\b|\bretrace\b|\bchaine des (?:remakes|adaptations)\b|\bremakes? de remakes?\b"
    r"|\b(?:un|le|du) remake\b|\bremakes? compris\b|\bremake par remake\b|\badaptation par adaptation\b"
    r"|\barrivee? a l'ecran\b|\ben a-t-on tire\b")
_LINEAGE_WEAK_RE = re.compile(
    r"\bbased on\b|\badapted from\b|\badaptations? of\b|\binspired by\b|\bderived from\b"
    r"|\bd'apres\b|\badaptee?s? (?:de|d')|\btiree?s? (?:de|d')|\binspiree?s? (?:de|d')|\bbasee?s? sur\b"
    r"|\bde quoi\b.*\badapte|\bde quoi\b.*\bremake|\bde quel (?:film|roman|livre|oeuvre)\b.*\b(?:remake|adapte)")
_LINEAGE_UP_RE = re.compile(
    r"\bbehind\b|\bback\b|\borigins?\b|\bsources?\b|\bcomes? from\b|\bremake of\b|\bbased on\b|\badapted from\b"
    r"|\binspired by\b|\bderived from\b"
    r"|\bremonte\b|\bderriere\b|\borigine\b|\bjusqu'|\bdecoule\b|\ble remake\b|\bremake de\b"
    r"|\bd'apres\b|\badaptee?s? (?:de|d')|\btiree?s? (?:de|d')|\binspiree?s? (?:de|d')|\bbasee?s? sur\b"
    r"|\bde quoi\b|\bde quel\b")
_LINEAGE_DOWN_RE = re.compile(
    r"\bdescend(?:s|ed|ants?)?\b|\bremakes of\b|\bremade\b|\breach(?:ed|es)? the screen\b|\badaptations? of\b"
    r"|\bspawn"
    r"|\bdescendance\b|\bdescend(?:ent|ants)?\b|\barrivee? a l'ecran\b|\ben a-t-on tire\b|\bremakes de\b"
    r"|\badaptations? (?:de|du|des|d')")


def rules_lineage(question):
    """Phase 3 lot E: the lineage the question asks for, or None. "descending" and "par ordre
    descendant" are sort orders and "Back to the Future" a title, not a lineage (census of the
    1.1.20 campaigns, 2026-11-12).

    Returns {"strength": "strong" | "weak", "direction": "up" | "down" | "both"}. Strong words ask
    for the lineage itself and set requested_view "chain"; weak words name one source ("What is
    Shogun based on?") and let the API walk only from a work the question names. The direction is
    up (toward the sources: "behind", "back to its origin", "a remake of", "remonte jusqu'a"), down
    (toward the works made from it: "descend from", "the remakes of", "reach the screen",
    "descendance"), or both when the question asks both ways or names the lineage alone ("the
    remake lineage of", "filiation"). The cues are read apart from the strong and weak sets, so
    "What is it a remake of, and what was remade from it?" is both.
    """
    q = re.sub(r"\b(?:ordre|order|tri|sort(?:ed)?) (?:descendant|descending)\b", " ", _fold(question).strip())
    if not q:
        return None
    strong = bool(_LINEAGE_STRONG_RE.search(q))
    if not strong and not _LINEAGE_WEAK_RE.search(q):
        return None
    # "remakes of remakes" and "remakes de remakes" say "every generation", not a direction.
    cues = re.sub(r"\bremakes? (?:of|de) remakes?\b", " ", q)
    up = bool(_LINEAGE_UP_RE.search(cues))
    down = bool(_LINEAGE_DOWN_RE.search(cues))
    direction = "both" if up == down else ("up" if up else "down")
    return {"strength": "strong" if strong else "weak", "direction": direction}


def rules_task(question):
    """The task the keyword rules read in the question; "list" when nothing else matches.

    Order, tuned on the 82 labelled questions of TEXT2SQL-EVAL-003: a comparison and a
    trend win over everything; a superlative ranks, even with a value per item ("the
    highest-grossing films and the revenue of each"); a value per item or an aggregate wins
    over an ordering ("the Star Wars films and the budget of each, in release order"); an
    ordering is a sequence; a bare "how many" is a count.
    """
    q = _fold(question).strip()
    if not q:
        return ""
    if _COMPARE_RE.search(q):
        return "compare"
    if _TREND_RE.search(q):
        return "trend"
    if _RANK_RE.search(_NOT_RANK_RE.sub(" ", q)):
        return "rank"
    if _VALUE_RE.search(q) or _WHEN_RE.search(q):
        return "value"
    if _SEQUENCE_RE.search(q):
        return "sequence"
    if _COUNT_RE.search(q):
        return "count"
    if _RELATE_RE.search(q):
        return "relate"
    if _is_verdict(q):
        return "verdict"
    return "list"


def _is_verdict(q):
    """A yes/no question, on the folded question: an English auxiliary first, est-ce que, or a
    French inversion with no question word; never a request worded as a question."""
    if _NOT_VERDICT_RE.search(q):
        return False
    if _VERDICT_RE.search(q):
        return True
    return bool(_FR_INVERSION_RE.search(q)) and not _FR_QUESTION_WORD_RE.search(q)


def rules_focus(question):
    """Canonical focus names the question's words name, in the order they appear."""
    q = _NOT_FOCUS_RE.sub(" ", _fold(question).strip())
    hits = []
    for name, rx in _FOCUS_SYNONYM_RES.items():
        m = rx.search(q)
        if m:
            hits.append((m.start(), name))
    m = _WHEN_RE.search(q)
    if m and all(name != "release_date" for _, name in hits):
        hits.append((m.start(), "release_date"))
    return [name for _, name in sorted(hits)]


def rules_requested_view(question):
    q = _fold(question)
    view = next((view for view, rx in _VIEW_RES if rx.search(q)), "")
    # Phase 3 lot A: a scatter wins over "chart" ("Plot the budget against the revenue" is not a
    # bar chart) and over nothing; an explicit table, share or cards stays.
    if view in ("", "chart") and (_SCATTER_VIEW_RE.search(q) or (
            _SCATTER_RELATION_RE.search(q) and len(rules_focus(question)) >= 2)):
        return "scatter"
    # Phase 3 lot E: strong lineage words ask for the chain, over nothing only.
    if view == "":
        lineage = rules_lineage(question)
        if lineage and lineage["strength"] == "strong":
            return "chain"
    return view


def rules_intent(question):
    """The keyword reading of the question, as a core intent; None with no question."""
    if not (question or "").strip():
        return None
    return {
        "task": rules_task(question),
        "focus": rules_focus(question),
        "requested_view": rules_requested_view(question),
        "source": "rules",
        **_share_shape_key(question),
    }


# --- The classifier's reply ---------------------------------------------------------------
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_classifier_reply(raw, allowed_entities):
    """Read the classifier's JSON reply into (entity, core intent or None).

    The entity keeps the one-word classifier's contract: a value of `allowed_entities`, or ""
    to abstain ("unknown", a word outside the set, an unreadable reply). A reply that is a
    bare word, as the one-word prompt gave, still yields its entity, with no intent. The
    intent is None when the task is missing or outside INTENT_TASKS: the caller then falls
    back to the rules, whose task is never empty.
    """
    allowed = {str(e).strip().lower() for e in allowed_entities or [] if str(e).strip()}
    text = (raw or "").strip()
    if not text:
        return "", None
    match = _JSON_OBJECT_RE.search(text)
    payload = None
    if match:
        try:
            payload = json.loads(match.group(0))
        except (ValueError, TypeError):
            payload = None
    if not isinstance(payload, dict):
        token = re.split(r"[^a-z_]+", text.lower(), maxsplit=1)[0]
        return (token if token in allowed else ""), None

    entity = str(payload.get("entity") or "").strip().lower()
    entity = entity if entity in allowed else ""
    task = str(payload.get("task") or "").strip().lower()
    if task in ("lookup", "describe"):
        task = "list"
    if task not in INTENT_TASKS:
        return entity, None
    focus = payload.get("focus")
    if isinstance(focus, str):
        focus = [focus]
    if not isinstance(focus, list):
        focus = []
    view = str(payload.get("requested_view") or "").strip().lower()
    return entity, {
        "task": task,
        "focus": canonical_focus(focus),
        "requested_view": view if view in REQUESTED_VIEWS else "",
        "source": "llm",
    }


# --- What the response carries -------------------------------------------------------------
def core_intent(question, llm_intent=None, cached_intent=None):
    """The intent to store and emit before the result columns are known.

    Precedence: the classifier's reading of this request, then the one stored with the cached
    SQL (a cache hit skips the classifier), then the keyword rules. None with no question.
    """
    for candidate in (llm_intent, cached_intent):
        if isinstance(candidate, dict) and candidate.get("task") in INTENT_TASKS:
            view = candidate.get("requested_view") if candidate.get("requested_view") in REQUESTED_VIEWS else ""
            # Phase 2 lot C: "share" comes from the keyword rules whatever the source, since the
            # classifier is not asked for it. It wins over "" and over "chart": "as a pie" reads
            # chart to the classifier, and a pie is the share form. Phase 3 lot A: "scatter" the
            # same way ("plot X against Y" reads chart to the classifier). Phase 3 lot B: "map" too
            # ("Show on a world map..." reads "" to the classifier, "plot them on a map" chart).
            # Phase 3 lot C: "hierarchy" the same way, over "" only ("grouped by trilogy" reads ""
            # to the classifier; a chart it read stays a chart). Phase 3 lot E: "chain" the same
            # way, over "" only ("Trace Nosferatu back to its source" reads "" to the classifier).
            if view in ("", "chart") and question and rules_requested_view(question) in ("share", "scatter", "map"):
                view = rules_requested_view(question)
            elif view == "" and question and rules_requested_view(question) in ("hierarchy", "chain"):
                view = rules_requested_view(question)
            return {
                "task": candidate["task"],
                "focus": canonical_focus(candidate.get("focus") or []),
                "requested_view": view,
                "source": candidate.get("source") if candidate.get("source") in ("llm", "rules") else "llm",
                **_share_shape_key(question),
            }
    return rules_intent(question)


def response_intent(core, result_columns):
    """The `intent` object of the response: the core plus the projected focus columns."""
    if not isinstance(core, dict):
        return None
    return {
        "task": core.get("task") or "",
        "focus": list(core.get("focus") or []),
        "focus_columns": focus_columns(core.get("focus") or [], result_columns or []),
        "requested_view": core.get("requested_view") or "",
        "source": core.get("source") or "none",
    }


def dumps_for_cache(core):
    """The compact JSON stored in T_WC_T2S_CACHE.RESULT_INTENT; "" when there is nothing."""
    if not isinstance(core, dict) or core.get("task") not in INTENT_TASKS:
        return ""
    return json.dumps({k: core.get(k) for k in ("task", "focus", "requested_view", "source")},
                      ensure_ascii=False, separators=(",", ":"))


def loads_from_cache(text):
    """Read RESULT_INTENT back; None when empty or unreadable."""
    if not text:
        return None
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return None
    return value if isinstance(value, dict) and value.get("task") in INTENT_TASKS else None
