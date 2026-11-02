"""Lexical title resolution for movies and series (FASTAPI-TEXT2SQL-360).

An in-memory index of every surface form of a title table (EN, FR and original title), built from
MariaDB in a background thread, that replaces the ChromaDB shortlist for ``Movie_title`` and
``Serie_title``. The offline bench (``checks/bench-lexical-360.py``) runs this same module on an
exported pool, so the bench measures the production algorithm.

Search, in order, stopping at the first stage that finds something:
  exact    the folded mention equals a folded form; candidates whose form only matches once a
           leading article is dropped on both sides join the same set, ranked after the exact
           ones ('Babysitter' stays 'Babysitter', but 'The Diary of a Chambermaid' of the
           extracted year beats 'Diary of a Chambermaid' of another year);
  prefix   the mention starts a form, the rest a subtitle left out ('noroit' -> 'noroit une
           vengeance', 'dr strangelove' -> 'doctor strangelove or how i learned...'); never for a
           single short word, and a mention that carries its article must match it;
  fuzzy    RapidFuzz ``ratio`` over every distinct form, at the strategy's ``min_fuzz_ratio``; a
           form whose numbers differ from the mention's is refused ('24 heures pour tuer' is not
           '3 heures pour tuer').
Ranking: a year within one of the extracted year first (TMDb dates Casablanca 1943), then exact
before article-only, then IMDb votes, then popularity. Folding: case, accents, punctuation, ``&``,
a few abbreviations (``dr`` -> ``doctor``) and spelled-out numbers below 100 in English and French
(``twelve monkeys`` -> ``12 monkeys``, ``vingt-quatre`` -> ``24``), on both sides.

Memory: one sorted list of distinct folded forms (shared string objects for the article-stripped
list when nothing is stripped) and flat ``array`` postings; about 80 MB for 800,000 movie forms.
"""

from __future__ import annotations

import bisect
import re
import threading
import time
import unicodedata
from array import array
from typing import Iterable, Optional, Sequence

from rapidfuzz import fuzz, process

# --------------------------------------------------------------------------- folding

_UNITS_EN = ("zero one two three four five six seven eight nine ten eleven twelve thirteen "
             "fourteen fifteen sixteen seventeen eighteen nineteen").split()
_TENS_EN = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
            "eighty": 80, "ninety": 90}
_UNITS_FR = ("zero un deux trois quatre cinq six sept huit neuf dix onze douze treize quatorze "
             "quinze seize").split()
_TENS_FR = {"vingt": 20, "trente": 30, "quarante": 40, "cinquante": 50, "soixante": 60}
_NUM = {w: i for i, w in enumerate(_UNITS_EN)}
_NUM.update({w: i for i, w in enumerate(_UNITS_FR) if i > 0})
_NUM.pop("un", None)   # also the French article: kept a word
_ABBREV = {"dr": "doctor", "mr": "mister", "mrs": "missus", "st": "saint", "vs": "versus",
           "pt": "part", "vol": "volume"}
_ARTICLES = re.compile(r"^(the|a|an|le|la|les|l|un|une|des|il|lo|el|der|die|das)\s+")
_NON_WORD = re.compile(r"[^\w\s]|_")
_DIGITS = re.compile(r"\d+")


def _numbers(tokens: Sequence[str]) -> list[str]:
    out, i = [], 0
    while i < len(tokens):
        t = tokens[i]
        tens = _TENS_EN.get(t) or _TENS_FR.get(t)
        if tens:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else ""
            if nxt == "et" and i + 2 < len(tokens) and tokens[i + 2] in ("un", "une"):
                out.append(str(tens + 1))
                i += 3
                continue
            if nxt in _NUM and 0 < _NUM[nxt] < 10:
                out.append(str(tens + _NUM[nxt]))
                i += 2
                continue
            out.append(str(tens))
            i += 1
            continue
        out.append(str(_NUM[t]) if t in _NUM else t)
        i += 1
    return out


def fold(s: Optional[str]) -> str:
    s = unicodedata.normalize("NFKD", (s or "").casefold())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.replace("&", " and ").replace("œ", "oe").replace("æ", "ae")
    s = _NON_WORD.sub(" ", s)
    return " ".join(_numbers([_ABBREV.get(t, t) for t in s.split()]))


def strip_article(folded: str) -> str:
    return _ARTICLES.sub("", folded)


# --------------------------------------------------------------------------- year of a title

def _year_value(v) -> Optional[int]:
    try:
        y = int(str(v).strip()[:4])
    except (TypeError, ValueError):
        return None
    return y if 1800 <= y <= 2200 else None


def year_for_title(entity_extraction: dict, title_key: str, year_prefix: str) -> Optional[int]:
    """The year that dates ``title_key`` ('Movie_title2') among the ``year_prefix`` keys
    ('Release_year1'...), or None.

    The extraction numbers years and titles separately ("Seven Samurai and The Magnificent Seven
    (1960)" gives Movie_title2 with Release_year1), so the index is not a link. The link is the
    anonymised question template: the year placeholder right after the title placeholder
    ('{{Movie_title2}} ({{Release_year1}})'). Without a template, the year of the same index.
    A single year with a single title dates it; anything else gives None rather than a guess."""
    if not isinstance(entity_extraction, dict):
        return None
    title_key = str(title_key or "").strip("{}")
    years = {k: _year_value(v) for k, v in entity_extraction.items()
             if isinstance(k, str) and k.startswith(year_prefix)}
    years = {k: y for k, y in years.items() if y}
    if not years:
        return None
    template = entity_extraction.get("question")
    if isinstance(template, str) and "{{" in template:
        m = re.search(r"\{\{" + re.escape(title_key) + r"\}\}[^{}]{0,4}\{\{(" + re.escape(year_prefix)
                      + r"\d*)\}\}", template)
        if m:
            return years.get(m.group(1))
    else:
        m = re.search(r"(\d+)$", title_key)
        if m and (year_prefix + m.group(1)) in years:
            return years[year_prefix + m.group(1)]
    title_prefix = re.sub(r"\d+$", "", title_key)
    ntitles = sum(1 for k in entity_extraction
                  if isinstance(k, str) and title_prefix and re.fullmatch(re.escape(title_prefix) + r"\d*", k))
    if len(years) == 1 and ntitles <= 1:
        return next(iter(years.values()))
    return None


# --------------------------------------------------------------------------- index

class TitleLexicon:
    """Index of the surface forms of one title table.

    ``rows`` yields ``(id, year, votes, popularity, form_0, form_1, ...)``; ``form_i`` comes from
    ``columns[i]``, so a hit says which column matched (``column_of``)."""

    def __init__(self, rows: Iterable[Sequence], columns: Sequence[str]):
        t0 = time.time()
        self.columns = list(columns)
        ncol = len(self.columns)
        self.ids = array("q")
        self.years = array("h")
        self.votes = array("q")
        self.pops = array("f")
        postings: dict[str, list[int]] = {}
        for r in rows:
            idx = len(self.ids)
            self.ids.append(int(r[0]))
            try:
                self.years.append(int(r[1]) if r[1] else 0)
            except (TypeError, ValueError):
                self.years.append(0)
            self.votes.append(int(r[2] or 0))
            self.pops.append(float(r[3] or 0))
            seen = set()
            for c in range(ncol):
                k = fold(r[4 + c])
                if k and k not in seen:
                    seen.add(k)
                    postings.setdefault(k, []).append(idx * 8 + c)
        self.keys: list[str] = sorted(postings)
        self.offsets = array("q", [0])
        self.codes = array("q")
        for k in self.keys:
            self.codes.extend(postings[k])
            self.offsets.append(len(self.codes))
        del postings
        # Article-stripped view: (stripped form, key index), sorted; the same string object is
        # reused when nothing is stripped.
        art = []
        for i, k in enumerate(self.keys):
            a = strip_article(k)
            art.append((a if a != k else k, i))
        art.sort()
        self.art_keys = [a for a, _ in art]
        self.art_ptr = array("q", [i for _, i in art])
        self.built_at = time.time()
        self.build_seconds = round(self.built_at - t0, 1)

    # -- helpers
    def __len__(self) -> int:
        return len(self.ids)

    def _codes_of_key(self, ki: int) -> array:
        return self.codes[self.offsets[ki]:self.offsets[ki + 1]]

    def _exact(self, q: str) -> Optional[int]:
        i = bisect.bisect_left(self.keys, q)
        return i if i < len(self.keys) and self.keys[i] == q else None

    def _art_range(self, lo_s: str, hi_s: str):
        return range(bisect.bisect_left(self.art_keys, lo_s), bisect.bisect_left(self.art_keys, hi_s))

    def _rank(self, codes: dict[int, int], year: Optional[int], preferred: set[int]) -> list[tuple[int, int]]:
        """codes: entity index -> column index. Returns [(entity index, column index)] ranked."""
        def key(e):
            yr = self.years[e]
            near = 0 if (year and yr and abs(yr - year) <= 1) else 1
            return (near if year else 0, 0 if e in preferred else 1, -self.votes[e], -self.pops[e])
        return [(e, codes[e]) for e in sorted(codes, key=key)]

    @staticmethod
    def _add(dst: dict[int, int], codes) -> None:
        for code in codes:
            e, c = divmod(code, 8)
            if e not in dst or c < dst[e]:
                dst[e] = c

    # -- search
    def search(self, mention: str, year: Optional[int] = None, min_ratio: float = 85.85) -> dict:
        """Return {stage, score, matches: [(id, column, year, votes)], form}; stage 'miss' if none."""
        q = fold(mention)
        out = {"stage": "miss", "score": 0.0, "matches": [], "form": "", "query": q}
        if not q:
            return out
        qa = strip_article(q)

        exact: dict[int, int] = {}
        ki = self._exact(q)
        if ki is not None:
            self._add(exact, self._codes_of_key(ki))
        art: dict[int, int] = {}
        for j in self._art_range(qa, qa + "\x00"):
            if self.art_keys[j] == qa:
                self._add(art, self._codes_of_key(self.art_ptr[j]))
        if exact or art:
            merged = dict(art)
            merged.update(exact)
            ranked = self._rank(merged, year, set(exact))
            return self._result(out, "exact" if ranked[0][0] in exact else "article", 100.0, ranked, q)

        if len(qa.split()) >= 2 or len(qa) >= 6:
            pre: dict[int, int] = {}
            if qa != q:   # the mention carries its article: match it on the full forms
                lo = bisect.bisect_left(self.keys, q + " ")
                hi = bisect.bisect_left(self.keys, q + " ￿")
                for ki in range(lo, hi):
                    self._add(pre, self._codes_of_key(ki))
            else:
                for j in self._art_range(qa + " ", qa + " ￿"):
                    self._add(pre, self._codes_of_key(self.art_ptr[j]))
            if pre:
                return self._result(out, "prefix", 100.0, self._rank(pre, year, set()), qa)

        hits = process.extract(q, self.keys, scorer=fuzz.ratio, limit=10, score_cutoff=min_ratio)
        qnum = _DIGITS.findall(q)
        hits = [h for h in hits if _DIGITS.findall(h[0]) == qnum]
        if hits:
            best = hits[0][1]
            fz: dict[int, int] = {}
            for _, sc, ki in hits:
                if sc >= best - 0.01:
                    self._add(fz, self._codes_of_key(ki))
            return self._result(out, "fuzzy", float(best), self._rank(fz, year, set()), hits[0][0])
        return out

    def _result(self, out, stage, score, ranked, form):
        out.update(stage=stage, score=score, form=form,
                   matches=[(self.ids[e], self.columns[c], self.years[e] or None, self.votes[e])
                            for e, c in ranked[:10]])
        out["n_candidates"] = len(ranked)
        return out


# --------------------------------------------------------------------------- registry (API side)

_LEXICONS: dict[tuple, TitleLexicon] = {}
_BUILDING: set[tuple] = set()
_LOCK = threading.Lock()


def lexicon_key(cfg: dict) -> tuple:
    langs = cfg.get("languages") or {}
    cols = tuple(dict.fromkeys(c for c in langs.values() if c))
    return (cfg.get("strtablename"), cfg.get("strtableid"), cols,
            cfg.get("lexicon_year_column"), cfg.get("lexicon_votes_column"),
            cfg.get("order_by") or "POPULARITY")


def build_from_db(connection, cfg: dict) -> TitleLexicon:
    table, idcol, cols, yearcol, votescol, popcol = lexicon_key(cfg)
    sel = ", ".join([f"`{idcol}`",
                     f"`{yearcol}`" if yearcol else "NULL",
                     f"COALESCE(`{votescol}`, 0)" if votescol else "0",
                     f"COALESCE(`{popcol}`, 0)"] + [f"`{c}`" for c in cols])
    sql = f"SELECT {sel} FROM `{table}` WHERE COALESCE(`DELETED`, 0) = 0"
    import pymysql.cursors  # local: the bench builds from a file and needs no driver
    cur = connection.cursor(pymysql.cursors.SSCursor)
    try:
        cur.execute(sql)
        lex = TitleLexicon(cur, cols)
    finally:
        cur.close()
    return lex


def get(cfg: dict) -> Optional[TitleLexicon]:
    """The built lexicon for this strategy, or None while it is not built yet."""
    return _LEXICONS.get(lexicon_key(cfg))


def ensure(connection_factory, cfg: dict, refresh_hours: float = 24.0) -> Optional[TitleLexicon]:
    """Return the lexicon if built; start a background (re)build when missing or older than
    ``refresh_hours``. Never blocks a request: a missing lexicon makes the strategy fall
    through to the next one."""
    key = lexicon_key(cfg)
    lex = _LEXICONS.get(key)
    stale = lex is not None and refresh_hours and (time.time() - lex.built_at) > refresh_hours * 3600
    if lex is None or stale:
        with _LOCK:
            if key in _BUILDING:
                return lex
            _BUILDING.add(key)

        def _build():
            conn = None
            try:
                conn = connection_factory()
                new = build_from_db(conn, cfg)
                _LEXICONS[key] = new
                print(f"[lexicon] {key[0]}: {len(new)} rows, {len(new.keys)} forms, built in "
                      f"{new.build_seconds}s", flush=True)
            except Exception as e:
                print(f"[lexicon] build failed for {key[0]}: {type(e).__name__}: {e}", flush=True)
            finally:
                with _LOCK:
                    _BUILDING.discard(key)
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass

        threading.Thread(target=_build, name=f"lexicon-{key[0]}", daemon=True).start()
    return lex


def prebuild(connection_factory, config: list) -> None:
    """Start the builds of every lexicon strategy of entity_resolution.json (startup)."""
    for entry in config or []:
        for s in entry.get("search_list") or []:
            if (s.get("search_mode") or "").strip().lower() == "lexicon" and s.get("enabled") is not False:
                ensure(connection_factory, s, float(s.get("lexicon_refresh_hours") or 24))


def status() -> dict:
    return {k[0]: {"rows": len(v), "forms": len(v.keys), "built_at": int(v.built_at)}
            for k, v in _LEXICONS.items()}
