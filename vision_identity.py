"""Identity check of the vision pre-stage (FASTAPI-TEXT2SQL-307).

The vision model can recognise a film with no hesitation, and the question composed from its
reading (``Movie Taxi Driver released in 1976``) can still match two rows: title plus year is
not a unique key in TMDb. Scorsese's *Taxi Driver* and the Turkish *Taksi Şoförü*, whose English
title is also "Taxi Driver", both came out in 1976.

This module decides, among the rows that share the identified title and year, which one the
image meant, using only what the vision model already said:

- the faces it read on the image (``people``), evidence SEEN, strong on a frame;
- the credits it knows for the work (``known_credits``), evidence KNOWN, strong on a poster
  with no face: directors, lead cast, original title, original language.

It is pure on purpose: no database, no model, standard library only, so that the decision is
pinned by ``checks/test-vision-homonyms.py`` on any machine. The caller fetches the candidate
rows and their credits, and applies the decision.

Two rules the decision never breaks:

1. **It only chooses among the candidates.** It never returns an empty list, so an error of
   the vision model on a name costs a disambiguation, never the right film.
2. **Popularity never decides.** A still from the obscure film must return the obscure film.
"""
import re
import unicodedata

# Weights. A face is seen, a known director is specific to one work: both weigh 2. A lead
# actor and the original title weigh 1. The original language weighs 1 too, which lets it break
# the Taxi Driver tie on its own (en vs tr) but never outweigh a contradicting face or director.
WEIGHT_FACE = 2
WEIGHT_DIRECTOR = 2
WEIGHT_LEAD_CAST = 1
WEIGHT_ORIGINAL_TITLE = 1
WEIGHT_ORIGINAL_LANGUAGE = 1

# Types the identity check applies to: the two kinds of work a title plus year designates.
IDENTITY_CHECK_TYPES = ("movie", "serie")

# Letters NFKD does not decompose into a base letter plus a mark. The dotless i is the case
# that matters here (Turkish names: "Kadir İnanır").
_EXTRA_FOLD = str.maketrans({"ı": "i", "ø": "o", "đ": "d", "ł": "l", "ß": "ss", "æ": "ae", "œ": "oe"})


def normalize_person_name(value) -> str:
    """Fold a name for comparison: accents, case, punctuation and spacing removed.

    ``"Şerif Gören"`` and ``"serif goren"`` both become ``"serif goren"``.
    """
    text = str(value or "").strip().casefold().translate(_EXTRA_FOLD)
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def _names(values) -> list:
    if not isinstance(values, (list, tuple)):
        return []
    out = []
    for v in values:
        n = normalize_person_name(v)
        if n and n not in out:
            out.append(n)
    return out


def identity_check_applies(selection) -> bool:
    """True when the vision selection is one work the identity check can confirm.

    ``selection`` is the dict returned by ``text2sql.select_vision_candidates``. The check only
    makes sense when ONE work dominates: with several close candidates the question already
    lists them all, and the client asks which one is meant.
    """
    if not isinstance(selection, dict) or not selection.get("dominant"):
        return False
    selected = selection.get("selected")
    if not isinstance(selected, dict):
        return False
    return str(selected.get("type") or "").strip().lower() in IDENTITY_CHECK_TYPES


def discriminators_from_vision(selected, people) -> dict:
    """Collect the discriminators of the selected work from the vision payload.

    ``selected`` is the work item (with its optional ``known_credits`` block), ``people`` the
    list of person items read on the image.
    """
    credits = selected.get("known_credits") if isinstance(selected, dict) else None
    credits = credits if isinstance(credits, dict) else {}
    faces = [p.get("value") for p in (people or []) if isinstance(p, dict)]
    return {
        "faces": faces,
        "directors": credits.get("directors") or [],
        "lead_cast": credits.get("lead_cast") or [],
        "original_title": credits.get("original_title") or "",
        "original_language": credits.get("original_language") or "",
    }


def _has_discriminator(disc) -> bool:
    return bool(_names(disc.get("faces")) or _names(disc.get("directors"))
                or _names(disc.get("lead_cast"))
                or normalize_person_name(disc.get("original_title"))
                or str(disc.get("original_language") or "").strip())


def score_candidate(candidate, disc) -> dict:
    """Score one candidate row against the discriminators.

    ``candidate`` keys: ``id``, ``original_title``, ``original_language``, ``directors`` (the
    directors of a film, the creators of a series), ``cast`` (every credited actor, in billing
    order). Returns ``{"score": int, "matches": [str, ...]}``.
    """
    directors = set(_names(candidate.get("directors")))
    cast = set(_names(candidate.get("cast")))
    people = directors | cast
    score = 0
    matches = []
    for face in _names(disc.get("faces")):
        # A face may belong to a director who appears on screen: any credit counts.
        if face in people:
            score += WEIGHT_FACE
            matches.append(f"face {face}")
    for director in _names(disc.get("directors")):
        if director in directors:
            score += WEIGHT_DIRECTOR
            matches.append(f"director {director}")
    faces = set(_names(disc.get("faces")))
    for actor in _names(disc.get("lead_cast")):
        # An actor already counted as a face is not counted twice.
        if actor in cast and actor not in faces:
            score += WEIGHT_LEAD_CAST
            matches.append(f"cast {actor}")
    known_title = normalize_person_name(disc.get("original_title"))
    if known_title and known_title == normalize_person_name(candidate.get("original_title")):
        score += WEIGHT_ORIGINAL_TITLE
        matches.append(f"original title {known_title}")
    known_lang = str(disc.get("original_language") or "").strip().lower()
    if known_lang and known_lang == str(candidate.get("original_language") or "").strip().lower():
        score += WEIGHT_ORIGINAL_LANGUAGE
        matches.append(f"original language {known_lang}")
    return {"score": score, "matches": matches}


def pick_vision_identity(candidates, disc, require_person_match: bool = False) -> dict:
    """Decide which of the rows sharing the identified title and year the image meant.

    Returns ``{"decision", "kept", "scores"}``:

    - ``single``: zero or one candidate, nothing to decide, every candidate kept;
    - ``no_discriminator``: the vision payload carries nothing to compare, all kept;
    - ``picked``: one candidate scores strictly above every other one, it alone is kept;
    - ``undecided``: no candidate scores, or the best score is shared, all kept.

    ``kept`` holds candidate ids in input order and is never empty when candidates exist.
    """
    rows = [c for c in (candidates or []) if isinstance(c, dict)]
    ids = [c.get("id") for c in rows]
    if len(rows) <= 1:
        return {"decision": "single", "kept": ids, "scores": {}}
    disc = disc if isinstance(disc, dict) else {}
    if not _has_discriminator(disc):
        return {"decision": "no_discriminator", "kept": ids, "scores": {}}
    scores = {c.get("id"): score_candidate(c, disc) for c in rows}
    ranked = sorted(scores.values(), key=lambda s: -s["score"])
    best = ranked[0]["score"]
    if best <= 0 or ranked[1]["score"] == best:
        return {"decision": "undecided", "kept": ids, "scores": scores}
    winner = next(cid for cid in ids if scores[cid]["score"] == best)
    # FASTAPI-TEXT2SQL-322. Without a year the namesakes span decades, and the original title
    # and language are shared by every version made in that language (five French "Les
    # Misérables"). A win on those alone is a guess, so the winner must also match a person:
    # a face, a director or a lead actor.
    if require_person_match and not any(
            m.split(" ", 1)[0] in ("face", "director", "cast") for m in scores[winner]["matches"]):
        return {"decision": "undecided", "kept": ids, "scores": scores}
    return {"decision": "picked", "kept": [winner], "scores": scores}


def _matched_names(wanted, held) -> list:
    """The names of ``wanted`` (as the model wrote them) whose folded form is in ``held``."""
    held_folded = set(_names(held))
    out = []
    for name in wanted if isinstance(wanted, (list, tuple)) else []:
        text = str(name or "").strip()
        if text and normalize_person_name(text) in held_folded and text not in out:
            out.append(text)
    return out


def _join(names, conjunction) -> str:
    if len(names) <= 1:
        return "".join(names)
    return ", ".join(names[:-1]) + f" {conjunction} " + names[-1]


def discriminator_phrase(candidate, disc, item_type: str = "movie") -> dict:
    """Phrase the credit that told the winning candidate apart, in English and French.

    ``{"en": "directed by Martin Scorsese", "fr": "réalisé par Martin Scorsese"}``. A matched
    director (creator for a series) comes first because it is specific to one work; failing
    that, a matched face or lead actor. A decision won on the title or the language alone
    yields empty strings: there is no credit to name.
    """
    candidate = candidate if isinstance(candidate, dict) else {}
    disc = disc if isinstance(disc, dict) else {}
    directors = _matched_names(disc.get("directors"), candidate.get("directors"))
    if directors:
        if str(item_type or "").strip().lower() == "serie":
            return {"en": f"created by {_join(directors, 'and')}",
                    "fr": f"créée par {_join(directors, 'et')}"}
        return {"en": f"directed by {_join(directors, 'and')}",
                "fr": f"réalisé par {_join(directors, 'et')}"}
    people = list(candidate.get("directors") or []) + list(candidate.get("cast") or [])
    actors = _matched_names(list(disc.get("faces") or []) + list(disc.get("lead_cast") or []), people)
    if actors:
        return {"en": f"starring {_join(actors[:2], 'and')}",
                "fr": f"avec {_join(actors[:2], 'et')}"}
    return {"en": "", "fr": ""}


# FASTAPI-TEXT2SQL-372. The same decision for a PERSON the complex model rewrote as
# `Person <name> born in <year>`. Name plus birth year is not a key either (93 groups of living
# persons share both: Michael Jackson 1958 is the singer and a British television executive),
# and the model's birth year can be one or two off the base (Chris Williams 1968 for 1967, Bob
# Nelson 1956 for 1958), so the candidates are read on the name with a year window and the
# model's knowledge of the person decides:
#
# - ``known_for``: titles the person is known for, matched against the titles of the works the
#   candidate is credited on (cast or crew). Specific to one person: it weighs 2 per title.
# - ``department``: TMDb's ``KNOWN_FOR_DEPARTMENT`` (Acting, Directing, Writing...), 1.
# - ``country_of_birth``: ISO 3166-1 alpha-2, 1.
#
# Popularity never decides: on three evaluations (Alan Parker, Michael Gordon, David Grossman)
# the namesake is MORE popular than the person described.
WEIGHT_KNOWN_FOR = 2
WEIGHT_DEPARTMENT = 1
WEIGHT_COUNTRY = 1
# A title shorter than this, folded, only matches a credit exactly ("Up", "Her", "It").
_KNOWN_FOR_CONTAINMENT_MIN = 6
_TRAILING_YEAR = re.compile(r"\s*\(\s*\d{4}\s*\)\s*$")


def _fold_title(value) -> str:
    return normalize_person_name(_TRAILING_YEAR.sub("", str(value or "")))


def _title_matches(known: str, held: str) -> bool:
    """``known`` and ``held`` are folded titles. Equal, or one holds the other as whole words
    when the shorter is long enough to be specific ("thriller" in "michael jackson s thriller")."""
    if not known or not held:
        return False
    if known == held:
        return True
    short, long_ = (known, held) if len(known) <= len(held) else (held, known)
    if len(short) < _KNOWN_FOR_CONTAINMENT_MIN:
        return False
    return f" {short} " in f" {long_} "


def person_discriminators(known_credits) -> dict:
    """The person discriminators of a ``known_credits`` block (``{}`` when there are none)."""
    credits = known_credits if isinstance(known_credits, dict) else {}
    known_for = [str(t or "").strip() for t in (credits.get("known_for") or [])
                 if str(t or "").strip()] if isinstance(credits.get("known_for"), list) else []
    return {
        "known_for": known_for,
        "department": str(credits.get("department") or "").strip(),
        "country_of_birth": str(credits.get("country_of_birth") or "").strip().upper()[:2],
    }


def has_person_discriminator(disc) -> bool:
    disc = disc if isinstance(disc, dict) else {}
    return bool(disc.get("known_for") or disc.get("department") or disc.get("country_of_birth"))


def score_person_candidate(candidate, disc) -> dict:
    """Score one person row against the person discriminators.

    ``candidate`` keys: ``id``, ``department``, ``country``, ``titles`` (every title of every
    work the person is credited on, any language). Returns ``{"score", "matches"}``; the
    ``known_for`` matches keep the title as the model wrote it, for the answer line.
    """
    candidate = candidate if isinstance(candidate, dict) else {}
    held = [_fold_title(t) for t in (candidate.get("titles") or [])]
    held = [t for t in held if t]
    score = 0
    matches = []
    for title in disc.get("known_for") or []:
        folded = _fold_title(title)
        if folded and any(_title_matches(folded, h) for h in held):
            score += WEIGHT_KNOWN_FOR
            matches.append(f"known_for {_TRAILING_YEAR.sub('', str(title)).strip()}")
    dept = normalize_person_name(disc.get("department"))
    if dept and dept == normalize_person_name(candidate.get("department")):
        score += WEIGHT_DEPARTMENT
        matches.append(f"department {disc.get('department')}")
    country = str(disc.get("country_of_birth") or "").strip().upper()
    if country and country == str(candidate.get("country") or "").strip().upper():
        score += WEIGHT_COUNTRY
        matches.append(f"country {country}")
    return {"score": score, "matches": matches}


def pick_person_identity(candidates, disc) -> dict:
    """Decide which of the persons sharing the name (and, roughly, the birth year) is meant.

    Same contract as ``pick_vision_identity``: ``single``, ``no_discriminator``, ``picked`` or
    ``undecided``, ``kept`` never empty when candidates exist. One more rule: a lone candidate
    that matches something is ``picked`` rather than ``single``, because the retry's SQL filters
    on the model's exact birth year and returns nobody when that year is off; the lone candidate
    was read with a year window, and its id is what the retry must query.
    """
    rows = [c for c in (candidates or []) if isinstance(c, dict)]
    ids = [c.get("id") for c in rows]
    disc = disc if isinstance(disc, dict) else {}
    if not rows:
        return {"decision": "single", "kept": [], "scores": {}}
    if not has_person_discriminator(disc):
        return {"decision": "single" if len(rows) == 1 else "no_discriminator",
                "kept": ids, "scores": {}}
    scores = {c.get("id"): score_person_candidate(c, disc) for c in rows}
    if len(rows) == 1:
        decision = "picked" if scores[ids[0]]["score"] > 0 else "single"
        return {"decision": decision, "kept": ids, "scores": scores}
    ranked = sorted(scores.values(), key=lambda s: -s["score"])
    best = ranked[0]["score"]
    if best <= 0 or ranked[1]["score"] == best:
        return {"decision": "undecided", "kept": ids, "scores": scores}
    winner = next(cid for cid in ids if scores[cid]["score"] == best)
    return {"decision": "picked", "kept": [winner], "scores": scores}


def person_discriminator_phrase(candidate, scores_entry) -> dict:
    """``{"en": "known for Midnight Express and Evita", "fr": "connu pour ..."}`` from the
    ``known_for`` titles that matched; empty strings when the win came from the department or
    the country alone. French agrees with TMDb's gender (1 = female)."""
    titles = [m.split(" ", 1)[1] for m in (scores_entry or {}).get("matches", [])
              if m.startswith("known_for ")][:2]
    if not titles:
        return {"en": "", "fr": ""}
    female = str((candidate or {}).get("gender") or "") == "1"
    return {"en": f"known for {_join(titles, 'and')}",
            "fr": f"{'connue' if female else 'connu'} pour {_join(titles, 'et')}"}


# FASTAPI-TEXT2SQL-321. The vision model puts names on faces, and a name it guesses can be wrong
# while the work it identifies is right. Measured on 2026-10-09: the Paris metro poster of *Les
# Misérables* (2026) came back as the right film, with "Grégory Gadebois, central figure in a long
# dark coat" among the faces and "Bernard Campan" in the lead cast. Neither is credited on the
# film; Vincent Lindon, whose printed name the photo cut off, plays Valjean. The client repeated
# the guess as a fact ("with Grégory Gadebois at its centre").
#
# Once the result is known, the credits of the returned works are the ground truth: a person
# named by the vision model survives only if those credits hold the name. The others are moved
# out of every field the client reads (people, person candidates, known credits, the faces
# hint) into ``credits_check.removed``, so the trace keeps them and the answer cannot use them.
_NAME_HEAD = re.compile(r"^[^\W\d_][\w'’.-]*(?:\s+[^\W\d_][\w'’.-]*){1,3}$")


def _looks_like_a_name(text) -> bool:
    """True for "Grégory Gadebois", False for "Other figures in nineteenth-century clothing"."""
    text = str(text or "").strip()
    if not _NAME_HEAD.match(text):
        return False
    return all(word[:1].isupper() for word in text.split())


def apply_credits_check(evidence, credited_names) -> dict:
    """Drop from ``evidence`` every person name the returned works' credits do not hold.

    ``evidence`` is the ``vision_evidence`` dict, modified in place and returned.
    ``credited_names`` is every person credited (cast and crew) on the works the search
    returned. Pure: no database, no model.
    """
    if not isinstance(evidence, dict):
        return evidence
    held = set(_names(credited_names))
    confirmed, removed = [], []

    def keep(name) -> bool:
        text = str(name or "").strip()
        if not text:
            return True
        ok = normalize_person_name(text) in held
        target = confirmed if ok else removed
        if text not in target:
            target.append(text)
        return ok

    people = evidence.get("people")
    if isinstance(people, list):
        evidence["people"] = [p for p in people
                              if not isinstance(p, dict) or keep(p.get("value"))]
    for key in ("candidates", "alternatives"):
        items = evidence.get(key)
        if isinstance(items, list):
            evidence[key] = [c for c in items if not isinstance(c, dict)
                             or str(c.get("type") or "").lower() != "person"
                             or keep(c.get("value"))]
    works = [evidence.get("selected")] + list(evidence.get("candidates") or [])
    for work in works:
        credits = work.get("known_credits") if isinstance(work, dict) else None
        if not isinstance(credits, dict):
            continue
        for field in ("directors", "lead_cast"):
            if isinstance(credits.get(field), list):
                credits[field] = [n for n in credits[field] if keep(n)]
    hints = evidence.get("hints")
    if isinstance(hints, dict) and isinstance(hints.get("faces"), list):
        faces = []
        for face in hints["faces"]:
            text = str(face or "")
            head, sep, rest = text.partition(",")
            if sep and _looks_like_a_name(head) and not keep(head):
                text = "unnamed person," + rest
            faces.append(text)
        hints["faces"] = faces
    evidence["credits_check"] = {"checked": True, "confirmed": confirmed, "removed": removed}
    return evidence
