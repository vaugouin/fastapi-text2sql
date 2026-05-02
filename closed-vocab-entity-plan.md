# New Entity Candidates for Entity Extraction Pipeline

## Context

Today the pipeline manages 16 entity types: 14 declared in [data/entity_resolution.json](data/entity_resolution.json) and 2 special placeholders (`Release_year`, `Genre_name`) handled in code at [entity.py:138-193](entity.py#L138).

The user asked whether more entities could be derived from what's already documented in the entity-extraction prompt and the text-to-SQL prompt. The audit below enumerates candidates surfaced from both files. It is intentionally exhaustive — final selection is up to the user.

Key insight from the audit: **the entity-extraction prompt already teaches the LLM to extract more entity types than entity_resolution.json knows how to resolve.** Several placeholders are extracted today but pass through resolution untouched (raw fallback).

---

## Tier A — Already extracted by [data/entity_extraction.md](data/entity_extraction.md), missing resolver

These are **the highest-priority gaps**: the LLM produces these placeholders but no `entity_resolution.json` entry exists, so they fall through with raw substitution.

### A1. `Serie_type` — closed vocabulary (7 values)
- Defined in [data/entity_extraction.md:164-176](data/entity_extraction.md#L164)
- Schema column: `T_WC_T2S_SERIE.SERIE_TYPE` ([data/text_to_sql.md:126](data/text_to_sql.md#L126), enumerated at line 855)
- Allowed values: `Documentary, Miniseries, News, Reality, Scripted, Talk Show, Video`
- Resolution: closed-vocabulary lookup; substitute the canonical exact-cased string
- Suggested implementation: special-case in `entity.py` like `_resolve_genre_id`, since values are simple strings (no ID lookup), but the placeholder must be matched case/spelling-exactly per the prompt rule at line 856

### A2. `Character_name` — embeddings or fuzzy on a (currently absent) collection
- Defined in [data/entity_extraction.md:55-57](data/entity_extraction.md#L55)
- The `characters` ChromaDB collection is initialized in [main.py:124-143](main.py#L124) but no `entity_resolution.json` rule references it
- No clear schema column for canonical character names exists in [data/text_to_sql.md](data/text_to_sql.md); `T_WC_T2S_PERSON_MOVIE.CAST_CHARACTER` may be the closest field
- Worth confirming with the user whether `characters` collection is populated and what it points to before wiring resolution

### A3. ID-style placeholders (raw substitution today, possibly fine as-is)
All defined in [data/entity_extraction.md:63-85](data/entity_extraction.md#L63):
- `IMDb_ID` (e.g., `tt0038355`) → matches `T_WC_T2S_MOVIE.ID_IMDB` / `T_WC_T2S_SERIE.ID_IMDB`
- `IMDb_person_ID` (e.g., `nm0000007`) → matches `T_WC_T2S_PERSON.ID_IMDB`
- `Wikidata_ID` (e.g., `Q28385`) → matches `T_WC_T2S_*.ID_WIKIDATA`
- `Wikidata_property_ID` (e.g., `P17`) → matches `T_WC_WIKIDATA_ITEM_PROPERTY.ID_PROPERTY`
- `TMDb_ID` (e.g., `550`) → primary keys
- `Criterion_spine_ID`

These don't strictly need resolvers (raw substitution works) but a lightweight regex-validation entry — like `Release_year` — would harden the pipeline against malformed IDs and let the JSON config record their canonical regex shapes.

---

## Tier B — Schema-enumerated fields not yet extracted

These are columns whose allowed values are explicitly listed in [data/text_to_sql.md](data/text_to_sql.md). Each is a strong candidate for a closed-vocabulary entity.

### B1. `Status_name` — closed vocabulary (6 values)
- Columns: `T_WC_T2S_MOVIE.STATUS`, `T_WC_T2S_SERIE.STATUS`
- Allowed values listed at [data/text_to_sql.md:733](data/text_to_sql.md#L733): `Canceled, In Production, Planned, Post Production, Released, Rumored`
- User phrasings: "released movies", "canceled series", "movies in production"
- Implementation: closed-vocabulary string substitution (same shape as A1)

### B2. `Department_name` — closed vocabulary (~12 values)
- Columns: `T_WC_T2S_PERSON_MOVIE.CREW_DEPARTMENT`, `T_WC_T2S_PERSON_SERIE.CREW_DEPARTMENT`, `T_WC_T2S_PERSON.KNOWN_FOR_DEPARTMENT`
- Allowed values at [data/text_to_sql.md:868-871](data/text_to_sql.md#L868): `Art, Camera, Costume & Make-Up, Crew, Directing, Editing, Lighting, Production, Sound, Visual Effects, Writing` (+ `Creator` for series, + `Acting` for KNOWN_FOR)
- Subtle: same vocabulary, two different columns chosen by question intent ("films directed by" → `CREW_DEPARTMENT='Directing'`, "directors" without films → `KNOWN_FOR_DEPARTMENT='Directing'`). The text-to-SQL prompt already encodes that disambiguation, so an entity placeholder just needs to surface the canonical value.

### B3. `Technical_format` — closed vocabulary (56 values, name → integer ID)
- Column: `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL`
- Mapping listed at [data/text_to_sql.md:765-778](data/text_to_sql.md#L765): `1: dolby, 4: technicolor, 29: imax, 50: franscope, 51: 35 mm, 52: digital, 54: 70 mm, 56: dcp, …`
- This is the **closest analog to `Genre_name`**: name → integer ID, fixed list. Pattern matches `_resolve_genre_id` exactly.
- Note: prompt today says (line 229) "Do not extract these as entities… technical formats or technologies such as `Technicolor`, `Dolby`, `IMAX`, `35 mm`" — so adding this entity would require **removing or inverting that rule** in [data/entity_extraction.md:229](data/entity_extraction.md#L229).

### B4. `Aspect_ratio` — closed vocabulary (~6 values)
- Column: `T_WC_T2S_MOVIE.ASPECT_RATIO` (VARCHAR)
- Listed at [data/text_to_sql.md:751](data/text_to_sql.md#L751): `1.37, 2.35, 1.85, 1.33, 1.66, 2.39`
- Stored as string; users may say "2.35:1", "16:9", "Academy ratio" → would need a normalizer mapping common phrasings to the stored decimal form. Possibly low ROI given the small handful of natural user queries, but the user explicitly raised this as the example.

### B5. `Country_name` and `Language_name` — ISO code lookup
- Country columns: `T_WC_T2S_COMPANY.ORIGIN_COUNTRY`, `T_WC_T2S_NETWORK.ORIGIN_COUNTRY`, `T_WC_T2S_*_PRODUCTION_COUNTRY.COUNTRY_CODE`, `T_WC_T2S_PERSON.COUNTRY_OF_BIRTH` — 2-letter ISO codes ([data/text_to_sql.md:730](data/text_to_sql.md#L730))
- Language columns: `T_WC_T2S_*.ORIGINAL_LANGUAGE`, `T_WC_T2S_*_SPOKEN_LANGUAGE.SPOKEN_LANGUAGE` — 2-letter ISO codes ([data/text_to_sql.md:723](data/text_to_sql.md#L723))
- **Currently explicitly excluded** by [data/entity_extraction.md:227-231](data/entity_extraction.md#L227): "Do not extract these as entities — spoken languages, countries or nationalities used only as descriptive filters." Adding them would require relaxing that rule. Implementation would be ISO 3166 / ISO 639 lookup tables (could live in code like `MOVIE_GENRE_NAME_TO_ID`, with multilingual aliases: `France→FR`, `French→fr`, `français→fr`).

### B6. `Gender` — boolean-style
- Column: `T_WC_T2S_PERSON.GENDER` (1 = female, 2 = male, [data/text_to_sql.md:732](data/text_to_sql.md#L732))
- Probably not worth a placeholder — text-to-SQL handles "actresses" vs "actors" inline. Listed for completeness.

### B7. `Credit_type` — `cast` vs `crew`
- Columns: `T_WC_T2S_PERSON_MOVIE.CREDIT_TYPE`, `T_WC_T2S_PERSON_SERIE.CREDIT_TYPE`
- Two values enumerated at [data/text_to_sql.md:864](data/text_to_sql.md#L864); phrasing rules ("with X" → cast, "by X" → crew) at [data/text_to_sql.md:760-761](data/text_to_sql.md#L760). Nearly always inferred from question phrasing — not worth a placeholder.

---

## Tier C — Open-vocabulary columns that could become embedding-resolved entities

These have many values and would need a ChromaDB collection (or fuzzy text match) rather than a fixed lookup.

### C1. `Cast_character` — character names as they appear in casts
- Column: `T_WC_T2S_PERSON_MOVIE.CAST_CHARACTER`, `T_WC_T2S_PERSON_SERIE.CAST_CHARACTER`
- This is the actual landing place for the `Character_name` placeholder (A2). Resolution would either fuzzy-match the column or use the existing `characters` ChromaDB collection if populated.

### C2. `Crew_job` — fine-grained job titles
- Column: `T_WC_T2S_PERSON_SERIE.CREW_JOB` ([data/text_to_sql.md:183](data/text_to_sql.md#L183))
- Hundreds of values, no vocabulary in the prompt. Likely too noisy for an entity; better left to text-to-SQL.

### C3. `Image_type` — `poster, logo, backdrop, profile`
- Column: `TYPE_IMAGE` in image tables ([data/text_to_sql.md:878](data/text_to_sql.md#L878))
- Closed but unlikely to surface in user questions — internal column.

### C4. `Video_type` / `Video_site`
- Columns in `T_WC_T2S_MOVIE_VIDEO` / `T_WC_T2S_SERIE_VIDEO`
- Vocabulary not enumerated in the prompt; rare in NLQ.

### C5. `Wikidata_property_label`
- Wikidata properties (`P840` narrative location, `P915` filming location) are referenced by ID in the location endpoint but a name → ID map (the small subset actually used) could let users say "filming locations" naturally. Probably premature.

---

## Tier D — Numeric/range entities (regex-only)

Following the `Release_year` precedent in [entity.py](entity.py):

### D1. `Birth_year` / `Death_year` — 4-digit year
- Columns: `T_WC_T2S_PERSON.BIRTH_YEAR`, `T_WC_T2S_PERSON.DEATH_YEAR`
- Same shape as `Release_year`. Useful for "actors born in 1962", "directors who died in 1980".

### D2. `Decade` — `1970s`, `1990s`
- Could normalize "1970s" → `BETWEEN 1970 AND 1979`. Trivial regex; could live as a `Release_decade`/`Birth_decade` placeholder or be left to text-to-SQL.

### D3. `Runtime`, `IMDB_rating`, `Vote_average`, `Budget`, `Revenue`
- All numeric, all currently handled by text-to-SQL inline. Probably not worth dedicated placeholders.

---

## Recommended ordering (if implementing later)

1. **`Serie_type` (A1)** — already extracted, trivial closed-vocab resolver, immediate win
2. **`Status_name` (B1)** — natural user query, 6 values, trivial resolver
3. **`Department_name` (B2)** — high practical value (filtering directors / cinematographers), 12 values
4. **`Birth_year` / `Death_year` (D1)** — copy of `Release_year`
5. **`Technical_format` (B3)** — high precision but requires inverting an extraction rule
6. **`Aspect_ratio` (B4)** — user's own example; small but tidy
7. **`Character_name` (A2/C1)** — needs decision on whether to use the existing `characters` collection or fuzzy on `CAST_CHARACTER`
8. **`Country_name` / `Language_name` (B5)** — biggest scope (ISO + multilingual aliases) and conflicts with current extraction rule

## Resolution strategy for closed-vocabulary entities (typo-tolerant, no ChromaDB)

For Tier A1, Tier B (all), and the existing `Genre_name`, use a **three-stage in-memory matcher** built on RapidFuzz (already a project dependency, see [rapidfuzz_query.py](rapidfuzz_query.py)). No ChromaDB collection, no SQL round-trip.

```
raw_value
  → Stage 1: normalize (lower + strip + collapse spaces + strip accents)
            exact lookup in canonical dict + alias dict
  → Stage 2: rapidfuzz.process.extract over canonical+alias keys
            scorer=fuzz.WRatio, score_cutoff=85, margin >= 5 over runner-up
  → Stage 3: fail → mark ambiguous_question_for_text2sql = True
```

Thresholds mirror [rapidfuzz_query.py](rapidfuzz_query.py) (`AUTO_SCORE=90`, `MIN_MARGIN=5`), slightly relaxed to 85 because matching against a ≤60-item curated vocabulary has a much lower collision rate than against a 900k-row table.

### Data shape — canonicals from DB, aliases from JSON

Two sources of truth, layered:

**1. Canonical values: loaded from the database at startup (no hard-coded lists in `entity.py`)**

A new module `closed_vocab.py` exposes `load_canonicals(connection)` and caches the result; `data_watcher` is not used here because schema-derived values rarely change, but a manual reload helper (`closed_vocab.refresh()`) lets the user trigger a refresh without restart.

| Entity | SQL query (run once at startup) |
|---|---|
| `Status_name` | `SELECT DISTINCT STATUS FROM T_WC_T2S_MOVIE WHERE STATUS IS NOT NULL UNION SELECT DISTINCT STATUS FROM T_WC_T2S_SERIE WHERE STATUS IS NOT NULL` |
| `Serie_type` | `SELECT DISTINCT SERIE_TYPE FROM T_WC_T2S_SERIE WHERE SERIE_TYPE IS NOT NULL` |
| `Aspect_ratio` | `SELECT DISTINCT ASPECT_RATIO FROM T_WC_T2S_MOVIE WHERE ASPECT_RATIO IS NOT NULL` |
| `Department_name` (CREW) | `SELECT DISTINCT CREW_DEPARTMENT FROM T_WC_T2S_PERSON_MOVIE WHERE CREW_DEPARTMENT IS NOT NULL UNION SELECT DISTINCT CREW_DEPARTMENT FROM T_WC_T2S_PERSON_SERIE WHERE CREW_DEPARTMENT IS NOT NULL` |
| `Department_name` (KNOWN_FOR) | `SELECT DISTINCT KNOWN_FOR_DEPARTMENT FROM T_WC_T2S_PERSON WHERE KNOWN_FOR_DEPARTMENT IS NOT NULL` |

For each, the loader produces a normalized dict: `{"canceled": "Canceled", "in production": "In Production", ...}` — keys are `_normalize(value)` (lower + accent-strip + whitespace-collapse), values are the canonical row exactly as stored.

**Genre and Technical_format have no `id ↔ name` reference table** (verified against the `CREATE TABLE` list at [data/text_to_sql.md:56-689](data/text_to_sql.md#L56)). For these two, the recommended option — least intrusive, doesn't require a DB schema change — is to **parse the canonical mapping out of `data/text_to_sql.md`** at startup (the lists at lines 765-778 for Technical and 926+ for Genre) and register the parser with `data_watcher` so prompt edits hot-reload the canonical maps too. This keeps `entity.py` clean (no hard-coded `MOVIE_GENRE_NAME_TO_ID` / `SERIE_GENRE_NAME_TO_ID` dicts) and makes the prompt the single source of truth.

If the user prefers a real DB-driven solution for Genre and Technical, the alternative is to add `T_WC_T2S_GENRE(ID_GENRE, GENRE_NAME, GENRE_TYPE)` and `T_WC_T2S_TECHNICAL(ID_TECHNICAL, TECHNICAL_NAME)` reference tables — a one-time schema migration; the loader pattern is then identical to the table above.

**2. Aliases: hot-reloaded JSON config file `data/closed_vocabularies.json`**

Synonyms aren't in the database and shouldn't be in source code either. A new file `data/closed_vocabularies.json` holds aliases per entity, registered via `data_watcher.register("closed_vocabularies.json", …)` so editors can add aliases without restart:

```json
{
  "Status_name": {
    "aliases": {
      "cancelled": "Canceled",
      "annulé": "Canceled",
      "sorti": "Released",
      "en production": "In Production"
    }
  },
  "Serie_type": {
    "aliases": {
      "doc": "Documentary",
      "documentaire": "Documentary",
      "mini-série": "Miniseries",
      "talk-show": "Talk Show"
    }
  },
  "Aspect_ratio": {
    "aliases": {
      "academy": "1.37",
      "academy ratio": "1.37",
      "widescreen": "1.85",
      "anamorphic": "2.35",
      "16:9": "1.85",
      "4:3": "1.33"
    }
  },
  "Technical_format": {
    "aliases": {
      "35mm": "35 mm",
      "70mm": "70 mm",
      "scope": "cinemascope",
      "imax format": "imax"
    }
  },
  "Department_name": { "aliases": {} },
  "Genre_name": {
    "aliases": {
      "sci fi": "Sci-Fi",
      "scifi": "Sci-Fi",
      "rom-com": "Romance"
    }
  }
}
```

Alias values point to the canonical (case-exact) values; the matcher then maps that canonical back to its DB-stored form (or to the integer ID for Genre/Technical).

### One generic resolver, all entities reuse it (alias-aware for every entity)

```python
def _resolve_closed_vocab(raw, canonical, aliases=None,
                          score_cutoff=85, margin=5):
    """
    canonical : dict[normalized_key -> canonical_value]
    aliases   : dict[normalized_key -> canonical_value]   # may be None
    Returns the canonical value, or None if no confident match.
    """
    norm = _normalize(raw)
    if norm in canonical: return canonical[norm]
    if aliases and norm in aliases: return aliases[norm]
    keys = list(canonical) + list(aliases or [])
    top = process.extract(norm, keys, scorer=fuzz.WRatio, limit=2)
    if top and top[0][1] >= score_cutoff and (
        len(top) == 1 or top[0][1] - top[1][1] >= margin
    ):
        hit = top[0][0]
        return aliases[hit] if (aliases and hit in aliases) else canonical[hit]
    return None
```

Every entity goes through this same function — alias resolution and typo tolerance are uniform. Per-entity dispatch in `resolve_entities()` looks like:

```python
canonical, aliases = closed_vocab.get("Status_name")          # DB + JSON
resolved = _resolve_closed_vocab(raw_value, canonical, aliases)
```

For Genre/Technical the canonical dict's value is the integer ID rather than a string — same code path, the substituted SQL fragment is just unquoted.

### Loader skeleton (`closed_vocab.py`)

```python
_CACHE = {}                                # entity → (canonical, aliases)
_ALIASES = {}                              # loaded by data_watcher

def _load_distinct(conn, query):
    with conn.cursor() as cur:
        cur.execute(query)
        return {_normalize(r[0]): r[0] for r in cur.fetchall() if r[0]}

def init(connection):
    _CACHE["Status_name"]      = _load_distinct(connection, STATUS_QUERY)
    _CACHE["Serie_type"]       = _load_distinct(connection, SERIE_TYPE_QUERY)
    _CACHE["Aspect_ratio"]     = _load_distinct(connection, ASPECT_QUERY)
    _CACHE["Department_name"]  = _load_distinct(connection, DEPARTMENT_QUERY)
    _CACHE["Genre_name"]       = _parse_genre_from_prompt()        # or DB if reference table added
    _CACHE["Technical_format"] = _parse_technical_from_prompt()    # or DB if reference table added

def _on_aliases_change(content):
    global _ALIASES
    _ALIASES = json.loads(content)

data_watcher.register("closed_vocabularies.json", _on_aliases_change)

def get(entity):
    return _CACHE.get(entity, {}), (_ALIASES.get(entity, {}) or {}).get("aliases", {})
```

`init(connection)` is called once at FastAPI startup with a short-lived DB connection.

### Side benefit: retrofit `Genre_name` removes hard-coded dicts

Today's `MOVIE_GENRE_NAME_TO_ID` / `SERIE_GENRE_NAME_TO_ID` at [entity.py:138-178](entity.py#L138) are deleted; `_resolve_genre_id` is rewritten to call `_resolve_closed_vocab` with the prompt-parsed (or DB-loaded) canonical. The movie-vs-serie context disambiguation at [entity.py:181-193](entity.py#L181) still applies, but operates on the loaded canonical map instead of inline dicts. The current strict dict lookup also becomes typo-tolerant ("sciience fiction" → `Science Fiction`) for free.

### Why not ChromaDB for these

- Overkill for ≤60 values — one in-memory dict + two RapidFuzz calls beats a network hop and avoids embedding cost
- No collection to manage, populate, or version
- Thresholds are deterministic and tunable per entity (status can be strict; technical-format names benefit from a looser cutoff)

---

## Critical files for any future implementation

- **NEW** `closed_vocab.py` — DB-driven canonical loader + JSON-driven alias loader; exposes `init(connection)` and `get(entity)`; uses `data_watcher` for the alias JSON
- **NEW** `data/closed_vocabularies.json` — hot-reloaded alias config (one entry per closed-vocab entity)
- [data/entity_resolution.json](data/entity_resolution.json) — add new resolver entries (embeddings/rapidfuzz cases) for non-closed-vocab entities only
- [entity.py](entity.py) — delete `MOVIE_GENRE_NAME_TO_ID` / `SERIE_GENRE_NAME_TO_ID` ([entity.py:138-178](entity.py#L138)); replace `_resolve_genre_id` with a `_resolve_closed_vocab`-based version; add new closed-vocab branches alongside the existing `Genre_name` branch at [entity.py:302-319](entity.py#L302)
- [main.py](main.py) — call `closed_vocab.init(connection)` at startup (next to ChromaDB collection initialization at [main.py:124-143](main.py#L124))
- [data/entity_extraction.md](data/entity_extraction.md) — add placeholder definitions, examples, and (for B3/B5) lift the current "do not extract" rules
- [data/text_to_sql.md](data/text_to_sql.md) — only edited if the user picks the alternative of adding `T_WC_T2S_GENRE` / `T_WC_T2S_TECHNICAL` reference tables; otherwise no change needed (the existing prompt sections become the parser input)

## Verification approach (for whichever subset is chosen)

1. Bump `strapiversion` in [main.py:54](main.py#L54) (cache key includes version, so a parity flip also moves Blue/Green)
2. Confirm `closed_vocab.init()` ran cleanly at startup by logging the loaded canonical maps (sizes per entity); a non-zero count proves the DB queries returned real data
3. Add concrete questions to the eval set in [eval/](eval/) covering each new placeholder, including **typo / alias variants** (e.g. "sciience fiction", "Documentaire", "annulé", "academy ratio") to exercise the alias + RapidFuzz paths
4. Hot reload picks up `data/closed_vocabularies.json` edits within 5 s — restart only required for `closed_vocab.py` / `entity.py` changes; canonical refresh from DB requires a manual `closed_vocab.refresh(connection)` call (or a restart)
5. Manual smoke tests with curl against `/search/text2sql`, asserting:
   - the new placeholder appears in `entity_extraction`
   - the resolved canonical value substitutes correctly into `sql_query`
   - alias inputs map to the same canonical as the canonical input
   - typo inputs above the threshold also map; below-threshold typos correctly set `ambiguous_question_for_text2sql = true`
6. Verify cache hits on a second identical request (`cached_anonymized_question = true`)

---

## Note on next steps

This file is a discovery catalog, not a build order. The natural next step is for the user to pick which tiers/items to implement. Because plan mode requires a single recommended approach for ExitPlanMode, the recommendation is: **implement Tier A1 (`Serie_type`) and Tier B1 (`Status_name`) first as a small, low-risk pilot**, then revisit the rest based on real eval impact. Other items can be planned in follow-up sessions.
