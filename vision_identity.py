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
pinned by ``eval/test-vision-homonyms.py`` on any machine. The caller fetches the candidate
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


def pick_vision_identity(candidates, disc) -> dict:
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
