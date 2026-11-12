#!/usr/bin/env python3
"""Offline check of FASTAPI-TEXT2SQL-353: result_intent.py and the RESULT_INTENT cache column.

No API, no database, no LLM call. Covers the classifier reply parser (JSON, bare word,
garbage), the keyword rules on questions that are NOT in the evaluation bank (the bank's
labels judge the live classifier in a campaign, so they are kept out of the rules' test),
the focus mapping onto projected columns, the cache round trip, and the degradation of
sql_cache.py when RESULT_INTENT (then RESULT_ENTITY) is not migrated.

    uv run checks/test-result-intent.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import result_intent as ri  # noqa: E402
import sql_cache  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))


ALLOWED = ["movie", "serie", "person", "collection"]

# 1. The classifier's reply.
check("json reply", ri.parse_classifier_reply(
    '{"entity": "movie", "task": "value", "focus": ["runtime"], "requested_view": ""}', ALLOWED),
    ("movie", {"task": "value", "focus": ["runtime"], "requested_view": "", "source": "llm"}))
check("json in a code fence, focus as a French word", ri.parse_classifier_reply(
    '```json\n{"entity": "serie", "task": "rank", "focus": ["saisons"], "requested_view": "table"}\n```', ALLOWED),
    ("serie", {"task": "rank", "focus": ["seasons"], "requested_view": "table", "source": "llm"}))
check("unknown entity abstains, intent kept", ri.parse_classifier_reply(
    '{"entity": "unknown", "task": "count", "focus": [], "requested_view": ""}', ALLOWED),
    ("", {"task": "count", "focus": [], "requested_view": "", "source": "llm"}))
check("lookup folds into list", ri.parse_classifier_reply('{"entity": "movie", "task": "lookup"}', ALLOWED)[1]["task"], "list")
check("task outside the set: entity only", ri.parse_classifier_reply('{"entity": "person", "task": "explain"}', ALLOWED), ("person", None))
check("bare word (one-word prompt)", ri.parse_classifier_reply("person", ALLOWED), ("person", None))
check("garbage", ri.parse_classifier_reply("I think {it is", ALLOWED), ("", None))
check("empty", ri.parse_classifier_reply("", ALLOWED), ("", None))

# 2. The keyword rules, on questions written for this test (none is in the bank).
RULES = [
    ("Which is longer, Heat or Casino?", "compare"),
    ("Lequel a coûté le plus, Waterworld ou Cutthroat Island ?", "compare"),
    ("Did Jim Jarmusch direct more films than Wes Anderson?", "compare"),
    ("How many westerns were released per decade?", "trend"),
    ("Durée moyenne des comédies chaque année depuis 1990", "trend"),
    ("The ten longest Spielberg films", "rank"),
    ("Quelles actrices ont joué dans le plus de films de Woody Allen ?", "rank"),
    ("How many films per country, from most to least?", "rank"),
    ("How many films won the Oscar for Best Animated Feature?", "count"),
    ("The Mission: Impossible films with the runtime of each", "value"),
    ("Les films Shrek avec leur budget, par ordre de sortie", "value"),
    ("Average budget of Ridley Scott films", "value"),
    ("How many seasons does The Office have?", "value"),
    ("The Bourne films in release order", "sequence"),
    ("Les films Mad Max du premier au plus récent", "sequence"),
    ("How many films did Spike Lee direct?", "count"),
    ("Combien de séries japonaises y a-t-il ?", "count"),
    ("What do Scorsese and De Niro have in common?", "relate"),
    ("Did Kubrick direct Spartacus?", "verdict"),
    ("Movies with Brad Pitt", "list"),
    ("Film avec l'identifiant IMDb tt0110912", "list"),
]
for question, want in RULES:
    check(f"rules {question!r}", ri.rules_task(question), want)
check("rules focus", ri.rules_focus("The Shrek films with the budget and the box office of each"), ["budget", "revenue"])
check("rules focus FR", ri.rules_focus("Les séries HBO avec le nombre de saisons"), ["seasons"])
check("rules view", ri.rules_requested_view("Les films de Kubrick sous forme de tableau"), "table")
check("rules on empty", ri.rules_intent("  "), None)

# 3. Focus onto projected columns: metrics and dates only, never a title.
COLUMNS = [
    {"name": "ID_MOVIE", "role": "id", "unit": None},
    {"name": "TITLE", "role": "label", "unit": None},
    {"name": "RUNTIME", "role": "metric", "unit": "minutes"},
    {"name": "BUDGET", "role": "metric", "unit": "usd"},
    {"name": "IMDB_RATING_WEIGHTED", "role": "metric", "unit": None},
    {"name": "RELEASE_YEAR", "role": "date", "unit": None},
]
check("focus columns runtime", ri.focus_columns(["runtime"], COLUMNS), ["RUNTIME"])
check("focus columns French word", ri.focus_columns(["durée", "budget"], COLUMNS), ["RUNTIME", "BUDGET"])
check("focus columns rating", ri.focus_columns(["rating"], COLUMNS), ["IMDB_RATING_WEIGHTED"])
check("focus not projected", ri.focus_columns(["seasons"], COLUMNS), [])

# 4. Precedence and the response object.
LLM = {"task": "rank", "focus": ["runtime"], "requested_view": "", "source": "llm"}
CACHED = {"task": "value", "focus": ["budget"], "requested_view": "", "source": "llm"}
check("llm first", ri.core_intent("Movies with Brad Pitt", LLM, CACHED)["task"], "rank")
check("cached next", ri.core_intent("Movies with Brad Pitt", None, CACHED)["task"], "value")
check("rules last", ri.core_intent("Movies with Brad Pitt", None, None), {"task": "list", "focus": [], "requested_view": "", "source": "rules"})
check("response object", ri.response_intent(LLM, COLUMNS),
      {"task": "rank", "focus": ["runtime"], "focus_columns": ["RUNTIME"], "requested_view": "", "source": "llm"})
check("response None", ri.response_intent(None, COLUMNS), None)
stored = ri.dumps_for_cache(LLM)
check("cache json", stored, '{"task":"rank","focus":["runtime"],"requested_view":"","source":"llm"}')
check("cache round trip", ri.loads_from_cache(stored), LLM)
check("cache empty", (ri.dumps_for_cache(None), ri.loads_from_cache(""), ri.loads_from_cache("{bad")), ("", None, None))
check("response intent survives the retry write", ri.dumps_for_cache(ri.response_intent(LLM, COLUMNS)), stored)


# 5. The shape rules take the intent as a prior (FASTAPI-TEXT2SQL-354).
import result_shape as rs  # noqa: E402


def movie_rows(values, key="RUNTIME"):
    return [{"index": i, "data": {"ID_MOVIE": 100 + i, "MOVIE_TITLE": f"Film {i}", "DAT_RELEASE": f"200{i}-01-01",
                                  "IMDB_RATING": 7.0 + i / 10, "IMDB_RATING_WEIGHTED": 7.0 + i / 10, "RUNTIME": 100 + i,
                                  key: v}} for i, v in enumerate(values)]


HP = movie_rows([152, 161, 141, 157, 138, 153, 146, 130])
HP_SQL = "SELECT ... FROM T_WC_T2S_MOVIE ... ORDER BY T_WC_T2S_MOVIE_COLLECTION.DISPLAY_ORDER ASC LIMIT 100"
none = rs.classify_result(HP_SQL, HP, "movie")
check("no intent: unchanged grid", none["representation"], "card-grid")
check("no intent: options", none["representation_options"], ["card-grid", "table"])
value = rs.classify_result(HP_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films with the runtime of each"))
check("value per item: value-cards", value["representation"], "value-cards")
check("value per item: focus on RUNTIME", [c["name"] for c in value["columns"] if c.get("focus")], ["RUNTIME"])
check("value per item: options", value["representation_options"], ["value-cards", "card-grid", "ranked-bars", "table"])
check("summary facts", {k: value["summary_facts"][k] for k in ("count", "total", "value_column", "unit", "order")},
      {"count": 8, "total": None, "value_column": "RUNTIME", "unit": "minutes", "order": "collection"})
check("summary top is the longest", (value["summary_facts"]["top"]["label"], value["summary_facts"]["top"]["value"],
                                     value["summary_facts"]["top"]["id"]), ("Film 1", 161, 101))
table = rs.classify_result(HP_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films with their runtime, as a table"))
check("requested view table", (table["representation"], table["representation_options"][0]), ("table", "table"))
RATED = "SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC LIMIT 12"
check("rank by rating named: bars", rs.classify_result(RATED, HP, "movie", intent=ri.core_intent("The 12 highest-rated Studio Ghibli films"))["representation"], "ranked-bars")
check("rank with no quantity named: grid", rs.classify_result(RATED, HP, "movie", intent=ri.core_intent("The best romance movies"))["representation"], "card-grid")
short = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.RUNTIME ASC LIMIT 5", HP, "movie", intent=ri.core_intent("The five shortest Pixar films"))
check("ascending ranking: bars, top is the minimum", (short["representation"], short["summary_facts"]["top"]["value"], short["summary_facts"]["top"]["extreme"]), ("ranked-bars", 130, "min"))
PAIR = movie_rows([194, 162])
cmp_ = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.RUNTIME DESC", PAIR, "movie", intent=ri.core_intent("Which is longer, Titanic (1997) or Avatar (2009)?"))
check("compare of two: compare-cards (phase 2 lot B)", cmp_["representation"], "compare-cards")
bud = movie_rows([150, 200], key="BUDGET")
check("value ordered on itself stays a ranking", rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.BUDGET DESC", bud, "movie",
      intent=ri.core_intent("The Toy Story movies with the budget of each"))["representation"], "ranked-bars")
one = rs.classify_result("SELECT SUM(RUNTIME) AS TOTAL_RUNTIME FROM T", [{"index": 0, "data": {"TOTAL_RUNTIME": 1178}}], "", intent=ri.core_intent("How long are all the Harry Potter films?"))
check("scalar: number card, options", (one["representation"], one["representation_options"], one["summary_facts"]["unit"]), ("number-card", ["number-card", "table"], "minutes"))
check("empty: no facts", rs.classify_result("SELECT 1", [], "movie", intent=ri.core_intent("x films"))["summary_facts"], None)

# Phase 2 lot A (2026-11-10): timeline, sequence-strip, trend-columns, and the "when" rule.
check("rules when", (ri.rules_task("When were the Alien films released?"), ri.rules_focus("When were the Alien films released?")), ("value", ["release_date"]))
check("rules quand, long metrage is no runtime", ri.rules_intent("Quand sont sortis les longs métrages réalisés par Hayao Miyazaki ?")["focus"], ["release_date"])
check("rules en quelles annees", ri.rules_task("En quelles années les films Jurassic Park sont-ils sortis ?"), "value")
check("rules when not at the start", ri.rules_task("films released when Kubrick was alive"), "list")
DATE_SQL = "SELECT ... FROM T_WC_T2S_MOVIE ... ORDER BY T_WC_T2S_MOVIE.DAT_RELEASE ASC"
tl = rs.classify_result(DATE_SQL, HP, "movie", intent=ri.core_intent("When were the Harry Potter films released?"))
check("when: timeline, date focused", (tl["representation"], [c["name"] for c in tl["columns"] if c.get("focus")]), ("timeline", ["DAT_RELEASE"]))
check("when: options", tl["representation_options"], ["timeline", "card-grid", "value-cards", "table"])
seq = rs.classify_result(DATE_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films in release order"))
check("sequence by date: strip", seq["representation"], "sequence-strip")
check("sequence by collection order: strip", rs.classify_result(HP_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films in order"))["representation"], "sequence-strip")
check("sequence ordered by rating stays a grid", rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC", HP, "movie",
      intent=ri.core_intent("The Harry Potter films in order"))["representation"], "card-grid")
check("list by date offers no strip", rs.classify_result(DATE_SQL, HP, "movie", intent=ri.core_intent("Movies with Brad Pitt"))["representation_options"], ["card-grid", "table"])
DECADES = [{"index": i, "data": {"DECADE": 1970 + 10 * i, "FILM_COUNT": n}} for i, n in enumerate([3, 9, 12, 8])]
DEC_SQL = "SELECT FLOOR(YEAR(DAT_RELEASE)/10)*10 AS DECADE, COUNT(*) AS FILM_COUNT FROM T GROUP BY DECADE ORDER BY DECADE ASC"
tr = rs.classify_result(DEC_SQL, DECADES, "", intent=ri.core_intent("How many films did Woody Allen direct per decade?"))
check("trend: columns, value, options", (tr["representation"], tr["summary_facts"]["value_column"], tr["representation_options"]),
      ("trend-columns", "FILM_COUNT", ["trend-columns", "table"]))
check("trend asked as a table", rs.classify_result(DEC_SQL, DECADES, "", intent=ri.core_intent("How many films did Woody Allen direct per decade, as a table?"))["representation"], "table")
check("grouped by decade without a trend intent stays a table", rs.classify_result(DEC_SQL, DECADES, "")["representation"], "table")

# Phase 2 lot B (2026-11-11): compare-cards, fact-card, verdict, and the yes/no rules.
VERDICT_RULES = [
    ("Did Ridley Scott direct Gladiator?", "verdict"),
    ("Can you show me the Kubrick films?", "list"),
    ("Do you have films with Brad Pitt?", "list"),
    ("Sergio Leone a-t-il réalisé Il était une fois dans l'Ouest ?", "verdict"),
    ("Heat est-il plus long que Casino ?", "verdict"),
    ("Quels films Sergio Leone a-t-il réalisés ?", "list"),
    ("Pouvez-vous lister les films de Kubrick ?", "list"),
    ("Est-ce que vous avez des films de Kubrick ?", "list"),
    ("Combien de films Kubrick a-t-il réalisés ?", "count"),
    ("Qu'y a-t-il dans la liste des 1001 films ?", "list"),
]
for question, want in VERDICT_RULES:
    check(f"rules {question!r}", ri.rules_task(question), want)
CMP_SQL = "SELECT ... ORDER BY T_WC_T2S_MOVIE.RUNTIME DESC LIMIT 50"
LLM_CMP = {"task": "compare", "focus": ["runtime"], "requested_view": "", "source": "llm"}
cc = rs.classify_result(CMP_SQL, movie_rows([175, 202]), "movie", intent=LLM_CMP)
check("compare-cards: options", cc["representation_options"], ["compare-cards", "card-grid", "value-cards", "ranked-bars", "table"])
check("compare-cards: winner is the first row of the ORDER BY", {k: cc["summary_facts"]["winners"][0][k] for k in ("column", "index", "value", "extreme", "tie")},
      {"column": "RUNTIME", "index": 0, "value": 175, "extreme": "max", "tie": False})
check("compare of five stays value-cards", rs.classify_result(CMP_SQL, movie_rows([1, 2, 3, 4, 5]), "movie", intent=LLM_CMP)["representation"], "value-cards")
tie = rs.classify_result(CMP_SQL, movie_rows([5, 5], key="NUMBER_OF_SEASONS"), "serie",
                         intent={"task": "compare", "focus": ["seasons"], "requested_view": "", "source": "llm"})
check("compare-cards: a tie has no winner", (tie["representation"], tie["summary_facts"]["winners"][0]["tie"], tie["summary_facts"]["winners"][0]["index"]), ("compare-cards", True, None))
two = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC", [
    {"index": 0, "data": {"ID_MOVIE": 1, "MOVIE_TITLE": "A", "BUDGET": 100, "REVENUE": 900}},
    {"index": 1, "data": {"ID_MOVIE": 2, "MOVIE_TITLE": "B", "BUDGET": 200, "REVENUE": 300}}], "movie",
    intent={"task": "compare", "focus": ["budget", "revenue"], "requested_view": "", "source": "llm"})
check("compare-cards: two quantities, max of each", [(w["column"], w["index"]) for w in two["summary_facts"]["winners"]], [("BUDGET", 1), ("REVENUE", 0)])
PERSONS = [{"index": i, "data": {"ID_PERSON": 10 + i, "PERSON_NAME": n, "BIRTH_YEAR": y, "BIRTH_MONTH": 1, "BIRTH_DAY": 2}}
           for i, (n, y) in enumerate([("P1", 1899), ("P2", 1915)])]
born = rs.classify_result("SELECT ... ORDER BY CASE WHEN BIRTH_YEAR IS NULL THEN 1 ELSE 0 END, T_WC_T2S_PERSON.BIRTH_YEAR ASC", PERSONS, "person",
                          intent={"task": "verdict", "focus": ["birth"], "requested_view": "", "source": "llm"})
check("yes/no comparison: compare-cards on the year, not the month", (born["representation"], [w["column"] for w in born["summary_facts"]["winners"]],
      born["summary_facts"]["winners"][0]["extreme"]), ("compare-cards", ["BIRTH_YEAR"], "earliest"))
FACT_VALUE = {"task": "value", "focus": ["runtime"], "requested_view": "", "source": "llm"}
fc = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC", movie_rows([228]), "movie", intent=FACT_VALUE)
check("fact-card: one entity, one value", (fc["representation"], fc["representation_options"], fc["summary_facts"]["fact"]["value"], fc["summary_facts"]["fact"]["others"]),
      ("fact-card", ["fact-card", "entity-page", "table"], 228, 0))
HOMONYMS = [{"index": i, "data": {"ID_MOVIE": 426 + i, "MOVIE_TITLE": t, "DAT_RELEASE": d, "IMDB_RATING_WEIGHTED": 8.1 - i}}
            for i, (t, d) in enumerate([("Vertigo", "1958-05-28"), ("Vertigo", "2016-08-10"), ("Vértigo", "1950-05-28")])]
WHEN = {"task": "value", "focus": ["release_date"], "requested_view": "", "source": "llm"}
fh = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC", HOMONYMS, "movie", intent=WHEN)
check("fact-card: homonyms of one title, first row", (fh["representation"], fh["summary_facts"]["fact"]["id"], fh["summary_facts"]["fact"]["value"], fh["summary_facts"]["fact"]["others"]),
      ("fact-card", 426, "1958-05-28", 2))
check("homonyms ordered by date stay a timeline", rs.classify_result(DATE_SQL, HOMONYMS, "movie", intent=WHEN)["representation"], "timeline")
check("distinct titles stay a timeline", tl["representation"], "timeline")
check("one entity, no value asked: entity page", rs.classify_result("SELECT ...", movie_rows([228]), "movie", intent=ri.core_intent("Movie Lawrence of Arabia"))["representation"], "entity-page")
check("fact-card as a table", rs.classify_result("SELECT ...", movie_rows([228]), "movie",
      intent={"task": "value", "focus": ["runtime"], "requested_view": "table", "source": "llm"})["representation"], "table")
YES = {"task": "verdict", "focus": [], "requested_view": "", "source": "llm"}
vy = rs.classify_result("SELECT ... WHERE ... CREW_DEPARTMENT = 'Directing'", movie_rows([124]), "movie", intent=YES)
check("verdict yes: a row exists", (vy["representation"], vy["representation_options"], vy["summary_facts"]["verdict"], vy["summary_facts"]["verdict_basis"]),
      ("verdict", ["verdict", "entity-page", "table"], "yes", "rows"))
vn = rs.classify_result("SELECT ...", [], "movie", intent=YES)
check("verdict no: no row", (vn["representation"], vn["representation_options"], vn["summary_facts"]["verdict"], vn["summary_facts"]["count"]),
      ("verdict", ["verdict", "card-grid", "table"], "no", 0))
vc = rs.classify_result("SELECT COUNT(DISTINCT ID_ROW) AS AWARD_WIN_COUNT FROM T", [{"index": 0, "data": {"AWARD_WIN_COUNT": 3}}], "award", intent=YES)
check("verdict on a count above zero", (vc["representation"], vc["representation_options"], vc["summary_facts"]["verdict"]), ("verdict", ["verdict", "number-card", "table"], "yes"))
check("verdict on a count of zero", rs.classify_result("SELECT COUNT(*) AS N FROM T", [{"index": 0, "data": {"N": 0}}], "", intent=YES)["summary_facts"]["verdict"], "no")
check("verdict on a sum: no verdict", rs.classify_result("SELECT SUM(RUNTIME) AS TOTAL_RUNTIME FROM T", [{"index": 0, "data": {"TOTAL_RUNTIME": 9}}], "", intent=YES)["representation"], "number-card")
check("empty without a verdict: no facts, no verdict", (vn["summary_facts"] is not None, rs.classify_result("SELECT 1", [], "movie")["representation"]), (True, "card-grid"))

# 5d. Phase 2 lot C: histogram, share-bar, flag-list (made-up questions and rows, not the bank's).
COUNT_TASK = {"task": "count", "focus": ["count"], "requested_view": "", "source": "llm"}
H_SQL = ("SELECT FLOOR(T_WC_T2S_MOVIE.RUNTIME / 30) * 30 AS RUNTIME_BUCKET, COUNT(DISTINCT T_WC_T2S_MOVIE.ID_MOVIE) AS FILM_COUNT "
         "FROM T_WC_T2S_MOVIE WHERE X GROUP BY FLOOR(T_WC_T2S_MOVIE.RUNTIME / 30) ORDER BY RUNTIME_BUCKET ASC LIMIT 100")
h_rows = [{"RUNTIME_BUCKET": 60, "FILM_COUNT": 4}, {"RUNTIME_BUCKET": 120, "FILM_COUNT": 2}, {"RUNTIME_BUCKET": 90, "FILM_COUNT": 7}]
h = rs.classify_result(H_SQL, h_rows, "", intent=COUNT_TASK)
hf = h["summary_facts"]["histogram"]
check("histogram: bins of a runtime plus a count", (h["representation"], h["representation_options"], hf["column"], hf["unit"], hf["width"]),
      ("histogram", ["histogram", "table"], "RUNTIME_BUCKET", "minutes", 30))
check("histogram: bins sorted by their start, never by count", [(b["low"], b["value"], b["index"]) for b in hf["bins"]],
      [(60, 4, 0), (90, 7, 2), (120, 2, 1)])
check("histogram: peak and total", (hf["peak"], hf["total"]), (1, 13))
check("histogram: no intent, same shape", rs.classify_result(H_SQL, h_rows, "")["representation"], "histogram")
gap = rs.classify_result(H_SQL, [{"RUNTIME_BUCKET": 0, "FILM_COUNT": 1}, {"RUNTIME_BUCKET": 30, "FILM_COUNT": 2}, {"RUNTIME_BUCKET": 90, "FILM_COUNT": 3}], "")["summary_facts"]["histogram"]
check("histogram: an empty bin between two filled ones is filled with 0", [(b["low"], b["value"], b["empty"]) for b in gap["bins"]],
      [(0, 1, False), (30, 2, False), (60, 0, True), (90, 3, False)])
RANGE_SQL = ("SELECT FLOOR(RUNTIME / 30) * 30 AS RUNTIME_RANGE_START, FLOOR(RUNTIME / 30) * 30 + 29 AS RUNTIME_RANGE_END, "
             "COUNT(DISTINCT ID_MOVIE) AS FILM_COUNT FROM T GROUP BY FLOOR(RUNTIME / 30) ORDER BY RUNTIME_RANGE_START")
hr = rs.classify_result(RANGE_SQL, [{"RUNTIME_RANGE_START": 90, "RUNTIME_RANGE_END": 119, "FILM_COUNT": 2},
                                    {"RUNTIME_RANGE_START": 120, "RUNTIME_RANGE_END": 149, "FILM_COUNT": 5}], "")
check("histogram: a range start and end", (hr["representation"], hr["summary_facts"]["histogram"]["high_column"],
      hr["summary_facts"]["histogram"]["bins"][0]["high"], [c.get("bin") for c in hr["columns"]]),
      ("histogram", "RUNTIME_RANGE_END", 119, ["low", "high", None]))
TEXT_BINS = ("SELECT CASE WHEN RUNTIME < 90 THEN 'under 90' ELSE '90 or more' END AS RUNTIME_RANGE, COUNT(*) AS FILM_COUNT "
             "FROM T GROUP BY 1 ORDER BY MIN(RUNTIME)")
check("histogram: text bins in the SQL's order", rs.classify_result(TEXT_BINS, [{"RUNTIME_RANGE": "under 90", "FILM_COUNT": 3},
      {"RUNTIME_RANGE": "90 or more", "FILM_COUNT": 9}], "")["representation"], "histogram")
DECADE_SQL = "SELECT DECADE, COUNT(*) AS FILM_COUNT FROM T GROUP BY DECADE ORDER BY DECADE"
check("histogram never takes a decade (trend-columns)", rs.classify_result(DECADE_SQL, [{"DECADE": 1960, "FILM_COUNT": 2}, {"DECADE": 1970, "FILM_COUNT": 5}], "",
      intent={"task": "trend", "focus": ["count"], "requested_view": "", "source": "llm"})["representation"], "trend-columns")
check("histogram never takes entity rows", rs.classify_result("SELECT ID_MOVIE, MOVIE_TITLE, RUNTIME FROM T ORDER BY RUNTIME",
      [{"ID_MOVIE": 1, "MOVIE_TITLE": "A", "RUNTIME": 90}, {"ID_MOVIE": 2, "MOVIE_TITLE": "B", "RUNTIME": 120}], "movie")["representation"] != "histogram", True)
check("histogram needs a COUNT the model wrote", rs.classify_result("SELECT RUNTIME_BUCKET, AVG(BUDGET) AS AVG_BUDGET FROM T GROUP BY RUNTIME_BUCKET",
      [{"RUNTIME_BUCKET": 60, "AVG_BUDGET": 1}, {"RUNTIME_BUCKET": 90, "AVG_BUDGET": 2}], "")["representation"], "table")

SPLIT = {"task": "count", "focus": ["count"], "requested_view": "share", "source": "rules"}
S_SQL = "SELECT T.SERIE_TYPE, COUNT(DISTINCT T.ID_SERIE) AS SERIE_COUNT FROM T GROUP BY T.SERIE_TYPE ORDER BY SERIE_COUNT DESC LIMIT 100"
s_rows = [{"SERIE_TYPE": "Scripted", "SERIE_COUNT": 6}, {"SERIE_TYPE": "Miniseries", "SERIE_COUNT": 3}, {"SERIE_TYPE": "News", "SERIE_COUNT": 1}]
sb = rs.classify_result(S_SQL, s_rows, "", intent=SPLIT)
check("share-bar: asked for, parts of a complete whole", (sb["representation"], sb["representation_options"]),
      ("share-bar", ["share-bar", "ranked-bars", "table"]))
check("share-bar: shares of the rows shown", [(p["label"], p["share"]) for p in sb["summary_facts"]["share"]["parts"]] + [sb["summary_facts"]["share"]["total"]],
      [("Scripted", 0.6), ("Miniseries", 0.3), ("News", 0.1), 10])
check("share-bar: not asked, offered beside the ranking", rs.classify_result(S_SQL, s_rows, "", intent=COUNT_TASK)["representation_options"],
      ["ranked-bars", "share-bar", "table"])
check("share-bar: never on a page or a top N", "share-bar" in rs.classify_result(S_SQL.replace("LIMIT 100", "LIMIT 3"), s_rows, "", intent=SPLIT)["representation_options"], False)
check("share-bar: never past eight parts", "share-bar" in rs.classify_result(S_SQL, [{"SERIE_TYPE": str(k), "SERIE_COUNT": 1} for k in range(9)], "", intent=SPLIT)["representation_options"], False)
GENDER_SQL = "SELECT P.GENDER, COUNT(DISTINCT P.ID_PERSON) AS CAST_COUNT FROM P GROUP BY P.GENDER"
g = rs.classify_result(GENDER_SQL, [{"GENDER": 1, "CAST_COUNT": 7}, {"GENDER": 2, "CAST_COUNT": 13}], "", intent=SPLIT)
check("share-bar: GENDER is a category, never a measure or a bin", (g["representation"], [c["role"] for c in g["columns"]], g["summary_facts"]["share"]["label_column"]),
      ("share-bar", ["label", "metric"], "GENDER"))
one = rs.classify_result("SELECT COUNT(DISTINCT CASE WHEN X THEN ID END) / NULLIF(COUNT(DISTINCT ID), 0) AS FILM_SHARE FROM T",
                         [{"FILM_SHARE": 0.74}], "", intent={"task": "value", "focus": [], "requested_view": "", "source": "llm"})
check("share-bar: one share is the part and the rest", (one["representation"], one["representation_options"], [(p["share"], p["rest"]) for p in one["summary_facts"]["share"]["parts"]]),
      ("share-bar", ["share-bar", "number-card", "table"], [(0.74, False), (0.26, True)]))
pct = rs.classify_result("SELECT 100.0 * COUNT(X) / COUNT(Y) AS PERCENT_OF_FILMS FROM T", [{"PERCENT_OF_FILMS": 27.27}], "")
check("share-bar: a percentage reads on 0 to 100", (pct["representation"], pct["summary_facts"]["share"]["scale"], pct["summary_facts"]["share"]["parts"][0]["share"]), ("share-bar", 100, 0.2727))
check("share-bar: a total is not a share", rs.classify_result("SELECT SUM(RUNTIME) AS TOTAL_RUNTIME FROM T", [{"TOTAL_RUNTIME": 900}], "")["representation"], "number-card")

C_SQL = "SELECT PC.COUNTRY_CODE, COUNT(DISTINCT M.ID_MOVIE) AS FILM_COUNT FROM PC JOIN M GROUP BY PC.COUNTRY_CODE ORDER BY FILM_COUNT DESC LIMIT 100"
fl = rs.classify_result(C_SQL, [{"COUNTRY_CODE": "JP", "FILM_COUNT": 9}, {"COUNTRY_CODE": "US", "FILM_COUNT": 2}, {"COUNTRY_CODE": "SU", "FILM_COUNT": 1}], "",
                        intent={"task": "rank", "focus": ["count"], "requested_view": "", "source": "llm"})
fc = fl["summary_facts"]["countries"]
check("flag-list: grouped country codes", (fl["representation"], fl["representation_options"], fc["source"], fc["value_column"]),
      ("flag-list", ["flag-list", "ranked-bars", "share-bar", "table"], "codes", "FILM_COUNT"))
check("flag-list: code, names, value, flag", [(c["code"], c["name"]["fr"], c["value"], c["flag"]) for c in fc["countries"]],
      [("JP", "Japon", 9, True), ("US", "États-Unis", 2, True), ("SU", "Union soviétique", 1, False)])
check("flag-list: as a chart is the ranking", rs.classify_result(C_SQL, [{"COUNTRY_CODE": "JP", "FILM_COUNT": 9}, {"COUNTRY_CODE": "US", "FILM_COUNT": 2}], "",
      intent={"task": "rank", "focus": ["count"], "requested_view": "chart", "source": "llm"})["representation"], "ranked-bars")
LOC_SQL = "SELECT DISTINCT L.ID_LOCATION, L.LOCATION_NAME, L.POSTER_PATH FROM L WHERE L.LOCATION_TYPE = 'country' ORDER BY L.LOCATION_NAME"
loc = rs.classify_result(LOC_SQL, [{"ID_LOCATION": 1, "LOCATION_NAME": "England", "POSTER_PATH": None},
                                   {"ID_LOCATION": 2, "LOCATION_NAME": "Morocco", "POSTER_PATH": None},
                                   {"ID_LOCATION": 3, "LOCATION_NAME": "Ruritania", "POSTER_PATH": None}], "location")
check("flag-list: location rows of type country, codes from the names", (loc["representation"], [(c["code"], c["label"]) for c in loc["summary_facts"]["countries"]["countries"]]),
      ("flag-list", [("GB", "England"), ("MA", "Morocco"), (None, "Ruritania")]))
check("flag-list: other locations stay a grid", rs.classify_result(LOC_SQL.replace("country", "city"), [{"ID_LOCATION": 1, "LOCATION_NAME": "Paris"}, {"ID_LOCATION": 2, "LOCATION_NAME": "Rome"}], "location")["representation"], "card-grid")
rep = rs.classify_result("SELECT M.ID_MOVIE, M.MOVIE_TITLE, PC.COUNTRY_CODE FROM M JOIN PC", [{"ID_MOVIE": 120, "MOVIE_TITLE": "X", "COUNTRY_CODE": "NZ"},
                         {"ID_MOVIE": 120, "MOVIE_TITLE": "X", "COUNTRY_CODE": "US"}], "movie")
check("flag-list: one film repeated per production country", (rep["representation"], [c["code"] for c in rep["summary_facts"]["countries"]["countries"]]), ("flag-list", ["NZ", "US"]))
check("flag-list: a person list with COUNTRY_OF_BIRTH stays a person list", rs.classify_result("SELECT ID_PERSON, PERSON_NAME, COUNTRY_OF_BIRTH FROM P",
      [{"ID_PERSON": 1, "PERSON_NAME": "A", "COUNTRY_OF_BIRTH": "GB"}, {"ID_PERSON": 2, "PERSON_NAME": "B", "COUNTRY_OF_BIRTH": "US"}], "person")["representation"], "card-grid")
check("share view words", [ri.rules_requested_view(q) for q in ("What part of the films are long?", "Show it as a pie chart", "Répartition des séries par statut en camembert",
      "Quel pourcentage de films est en couleur ?", "the posters of the films")], ["", "share", "share", "share", ""])
check("share view wins over the classifier's chart and its empty view", (ri.core_intent("Show the split as a pie", {"task": "count", "focus": [], "requested_view": "chart", "source": "llm"})["requested_view"],
      ri.core_intent("What share of these films are long?", {"task": "value", "focus": [], "requested_view": "", "source": "llm"})["requested_view"],
      ri.core_intent("Show them as a table", {"task": "list", "focus": [], "requested_view": "table", "source": "llm"})["requested_view"]),
      ("share", "share", "table"))

# 5e. Phase 3 lot A: scatter (made-up questions and rows, not the bank's).
check("scatter view words", [ri.rules_requested_view(q) for q in (
      "Scatter plot of the runtime and the rating of the Pixar films",
      "Montre la durée des films de Lynch en nuage de points",
      "Plot the budget against the revenue of the Ridley Scott films",
      "Trace la note en fonction de la durée des films de Truffaut",
      "Runtime versus rating of the Coen brothers films",
      "Is there a link between the budget and the box office of Fincher's films?",
      "Plot the ten longest films of Kurosawa",
      "Films against the war",
      "Alien versus Predator",
      "The Bergman films with their runtime and rating, as a table")],
      ["scatter", "scatter", "scatter", "scatter", "scatter", "scatter", "chart", "", "", "table"])
check("scatter view wins over the classifier's chart and its empty view", (
      ri.core_intent("Plot the budget against the revenue of Spielberg's films", {"task": "value", "focus": ["budget", "revenue"], "requested_view": "chart", "source": "llm"})["requested_view"],
      ri.core_intent("Le budget en fonction des recettes des films de Spielberg", {"task": "value", "focus": ["budget", "revenue"], "requested_view": "", "source": "llm"})["requested_view"],
      ri.core_intent("Budget against revenue of these films, as cards", {"task": "value", "focus": ["budget", "revenue"], "requested_view": "cards", "source": "llm"})["requested_view"]),
      ("scatter", "scatter", "cards"))


def scatter_rows(pairs, x="BUDGET", y="REVENUE"):
    return [{"index": i, "data": {"ID_MOVIE": 500 + i, "MOVIE_TITLE": f"Film {i}", "DAT_RELEASE": f"19{60 + i}-05-01",
                                  "IMDB_RATING": 7.1, "IMDB_RATING_WEIGHTED": 7.0, "RUNTIME": 100 + i, x: a, y: b}}
            for i, (a, b) in enumerate(pairs)]


SC_SQL = "SELECT M.ID_MOVIE, M.MOVIE_TITLE, M.BUDGET, M.REVENUE FROM M WHERE X ORDER BY M.IMDB_RATING_WEIGHTED DESC LIMIT 50"
BR = {"task": "value", "focus": ["budget", "revenue"], "requested_view": "scatter", "source": "rules"}
sc_rows = scatter_rows([(10e6, 50e6), (20e6, 30e6), (0, 80e6), (40e6, 0), (5e6, 9e6), (60e6, 200e6), (None, None), (15e6, 45e6)])
sc = rs.classify_result(SC_SQL, sc_rows, "movie", intent=BR)
sf = sc["summary_facts"]["scatter"]
check("scatter: asked for, the default", (sc["representation"], sc["representation_options"][0], "table" == sc["representation_options"][-1]), ("scatter", "scatter", True))
check("scatter: budget across, revenue up, linear", (sf["x"]["column"], sf["x"]["unit"], sf["x"]["scale"], sf["y"]["column"], sf["y"]["unit"]),
      ("BUDGET", "usd", "linear", "REVENUE", "usd"))
check("scatter: a 0 or NULL is missing, counted per axis", (sf["count"], sf["plotted"], sf["left_out"], sf["missing"]), (8, 5, 3, {"x": 2, "y": 2}))
check("scatter: points keep the row index, label and id", sf["points"][0], {"index": 0, "label": "Film 0", "id": 500, "x": 10000000, "y": 50000000})
check("scatter: extremes index the points", (sf["points"][sf["extremes"]["y_max"]]["label"], sf["points"][sf["extremes"]["x_min"]]["label"]), ("Film 5", "Film 4"))
not_asked = rs.classify_result(SC_SQL, sc_rows, "movie", intent={"task": "value", "focus": ["budget", "revenue"], "requested_view": "", "source": "llm"})
check("scatter: not asked, offered beside the cards", (not_asked["representation"], "scatter" in not_asked["representation_options"], "scatter" in not_asked["summary_facts"]),
      ("value-cards", True, True))
check("scatter: a relation is the default", rs.classify_result(SC_SQL, sc_rows, "movie", intent={"task": "relate", "focus": ["budget", "revenue"], "requested_view": "", "source": "llm"})["representation"], "scatter")
check("scatter: a chart of two quantities is a scatter, a ranking stays bars", (
      rs.classify_result(SC_SQL, sc_rows, "movie", intent={"task": "value", "focus": ["budget", "revenue"], "requested_view": "chart", "source": "llm"})["representation"],
      rs.classify_result(SC_SQL.replace("IMDB_RATING_WEIGHTED", "REVENUE"), sc_rows, "movie", intent={"task": "rank", "focus": ["budget", "revenue"], "requested_view": "chart", "source": "llm"})["representation"]),
      ("scatter", "ranked-bars"))
check("scatter: fewer than five points is no scatter", "scatter" in rs.classify_result(SC_SQL, sc_rows[:6], "movie", intent=BR)["representation_options"], False)
check("scatter: one quantity is no scatter", "scatter" in rs.classify_result(SC_SQL, sc_rows, "movie", intent={"task": "value", "focus": ["budget"], "requested_view": "scatter", "source": "rules"})["representation_options"], False)
check("scatter: three quantities is no scatter", "scatter" in rs.classify_result(SC_SQL, sc_rows, "movie", intent={"task": "value", "focus": ["budget", "revenue", "runtime"], "requested_view": "scatter", "source": "rules"})["representation_options"], False)
RR = {"task": "relate", "focus": ["runtime", "rating"], "requested_view": "", "source": "llm"}
rr = rs.classify_result(SC_SQL, scatter_rows([(1, 1)] * 6), "movie", intent=RR)["summary_facts"]["scatter"]
check("scatter: IMDB_RATING over its weighted twin, runtime across", (rr["x"]["column"], rr["y"]["column"], rr["y"]["unit"]), ("RUNTIME", "IMDB_RATING", "rating"))
YR = {"task": "trend", "focus": ["rating", "release_date"], "requested_view": "scatter", "source": "llm"}
yr = rs.classify_result(SC_SQL, scatter_rows([(1, 1)] * 6), "movie", intent=YR)["summary_facts"]["scatter"]
check("scatter: a date string gives its year, across", (yr["x"]["column"], yr["x"]["unit"], yr["points"][2]["x"], yr["y"]["column"]), ("DAT_RELEASE", "year", 1962, "IMDB_RATING"))
VR = {"task": "value", "focus": ["votes", "rating"], "requested_view": "scatter", "source": "llm"}
vr = rs.classify_result(SC_SQL, scatter_rows([(30, 6.1), (900, 6.5), (25000, 7.2), (800000, 8.1), (2100000, 8.8)], x="IMDB_VOTES", y="IMDB_RATING"), "movie", intent=VR)["summary_facts"]["scatter"]
check("scatter: votes over two orders of magnitude are a log axis", (vr["x"]["column"], vr["x"]["unit"], vr["x"]["scale"], vr["y"]["scale"]), ("IMDB_VOTES", "votes", "log", "linear"))
vl = rs.classify_result(SC_SQL, scatter_rows([(3e5, 6.1), (4e5, 6.5), (5e5, 7.2), (8e5, 8.1), (9e5, 8.8)], x="IMDB_VOTES", y="IMDB_RATING"), "movie", intent=VR)["summary_facts"]["scatter"]
check("scatter: close votes stay linear", vl["x"]["scale"], "linear")


# 6. sql_cache degrades column by column, newest first.
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params):
        for column in self.conn.missing:
            if column in query:
                raise Exception(f"(1054, \"Unknown column '{column}' in 'field list'\")")
        self.conn.queries.append((query, params))

    def fetchone(self):
        return {"QUESTION": "q", "SQL_QUERY": "SELECT 1", "RESULT_ENTITY": "movie", "RESULT_INTENT": stored} if "RESULT_INTENT" not in self.conn.missing else {"QUESTION": "q", "SQL_QUERY": "SELECT 1", "RESULT_ENTITY": "movie"}


class FakeConnection:
    def __init__(self, missing):
        self.missing = set(missing)
        self.queries = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


def reset_flags():
    sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE = True
    sql_cache._RESULT_INTENT_COLUMN_AVAILABLE = True


WRITE = dict(question="q", question_hashed="h", sql_query="SELECT 1", sql_processed="SELECT 1", justification="",
             api_version="001.002.000", entity_extraction_processing_time=0.0, text2sql_processing_time=0.0,
             embeddings_time=0.0, query_time=0.0, total_processing_time=0.0, is_anonymized=False,
             result_entity="movie", result_intent_json=stored)

reset_flags()
conn = FakeConnection([])
sql_cache.write_sql_cache_entry(conn, **WRITE)
query, params = conn.queries[-1]
check("write both columns", ("RESULT_ENTITY, RESULT_INTENT)" in query, params[-2:]), (True, ("movie", stored)))
check("read both columns", sql_cache.search_sql_cache_by_question_hash(conn, "h", "001.002.000")["result_intent"], stored)

reset_flags()
conn = FakeConnection(["RESULT_INTENT"])
sql_cache.write_sql_cache_entry(conn, **WRITE)
query, params = conn.queries[-1]
check("intent column missing: write keeps RESULT_ENTITY", ("RESULT_INTENT" in query, params[-1]), (False, "movie"))
check("intent column missing: read", sql_cache.search_sql_cache_by_question_hash(conn, "h", "001.002.000")["result_entity"], "movie")
check("flags after", (sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE, sql_cache._RESULT_INTENT_COLUMN_AVAILABLE), (True, False))

reset_flags()
conn = FakeConnection(["RESULT_INTENT", "RESULT_ENTITY"])
sql_cache.write_sql_cache_entry(conn, **WRITE)
check("both missing: legacy write", "RESULT_ENTITY" in conn.queries[-1][0], False)
check("flags after both", (sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE, sql_cache._RESULT_INTENT_COLUMN_AVAILABLE), (False, False))
reset_flags()

print(f"\n{'all ok' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
