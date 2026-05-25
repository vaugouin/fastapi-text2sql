# SEASONS_AND_EPISODES.md

Design notes and pending decisions for exposing TV-series **seasons** and **episodes** as first-class entities in the API.

**Status (2026-05-25):** `/seasons/{id_serie}/{season_number}` and `/episodes/{id_serie}/{season_number}/{episode_number}` have shipped as TMDb-sourced endpoints. They satisfy the API shape proposed in §3 (with the documented signature change: composite key on `(ID_SERIE, SEASON_NUMBER[, EPISODE_NUMBER])` rather than the surrogate `ID_SEASON` / `ID_EPISODE`). They will be migrated to the T2S read model once the prerequisite tables in §4 land — see §6.1 for the registered call sites. Outstanding work: the §4 prerequisite tables, the §5.x open questions (videos / translations / `IMDB_RATING_WEIGHTED` retrofit), and MCP `get_season` / `get_episode` tool wrappers per §5.x.

> **Migration rule (load-bearing):** every place in the codebase that currently reads from a `T_WC_TMDB_*` table because no T2S equivalent exists **must** be migrated to the equivalent `T_WC_T2S_*` table as soon as that table is available. This is a hard requirement, not a follow-up question. The known call sites are tracked in §6.1; when the corresponding T2S table lands, every row keyed to it must be migrated and the affected README sections updated in the same change. The same rule applies to any new endpoint we ship before the prerequisites in §4 are met — if you have to reach into `T_WC_TMDB_*` to ship, add the call site to §6.1 so the migration sweep catches it.

---

## 1. What already shipped

### 1.1 `seasons` array on `GET /series/{id}`
- [`GET /series/{id}`](main.py#L1795) returns a `seasons` array — see [main.py:1914-1922](main.py#L1914-L1922) for the query and [main.py:1933](main.py#L1933) for the response wiring.
- Source table: `T_WC_TMDB_SEASON` (TMDb source — there is no `T_WC_T2S_SEASON` yet).
- Field set exposed per season: `ID_SEASON, SEASON_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, POSTER_PATH, EPISODE_COUNT, VOTE_AVERAGE, ID_IMDB, ID_WIKIDATA, ID_TVDB`.
- Order: `SEASON_NUMBER ASC`. No `DELETED` filter (matches the rest of `/series/{id}`).
- Docs: README field table at [README.md:611](README.md#L611) and MCP `get_series` docstring.

### 1.2 `GET /seasons/{id_serie}/{season_number}`
- Full season detail endpoint, keyed on the composite `(ID_SERIE, SEASON_NUMBER)` rather than the surrogate `ID_SEASON`.
- Returns the full `T_WC_TMDB_SEASON` row plus `cast`, `crew`, `posters`, `backdrops`, a `series` navigation stub, an `episodes` summary array, and `wikipedia_images` / `wikipedia_content`.
- `episodes` is a summary list ordered by `EPISODE_NUMBER ASC` whose length matches `EPISODE_COUNT` on the season row; each row carries `ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB`. Full episode payload (cast/crew/stills/Wikipedia) lives on `/episodes/{id_serie}/{season_number}/{episode_number}` — this resolves §5.2.
- Sources: `T_WC_TMDB_SEASON`, `T_WC_TMDB_PERSON_SEASON`, `T_WC_TMDB_SEASON_IMAGE`, `T_WC_TMDB_EPISODE` (for the `episodes` summary), `T_WC_T2S_PERSON` (for display fields), `T_WC_T2S_SERIE` (navigation stub).
- Docs: README field table.

### 1.3 `GET /episodes/{id_serie}/{season_number}/{episode_number}`
- Full episode detail endpoint, keyed on the composite `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)` rather than the surrogate `ID_EPISODE`.
- Returns the full `T_WC_TMDB_EPISODE` row plus `cast`, `crew`, `stills`, `season` and `series` navigation stubs, and `wikipedia_images` / `wikipedia_content` (almost always empty for episodes).
- Sources: `T_WC_TMDB_EPISODE`, `T_WC_TMDB_PERSON_EPISODE`, `T_WC_TMDB_EPISODE_IMAGE`, `T_WC_TMDB_SEASON` (for the season navigation stub), `T_WC_T2S_PERSON` (for display fields), `T_WC_T2S_SERIE` (navigation stub).
- Docs: README field table.

### 1.4 Why these endpoints currently read from `T_WC_TMDB_*`
These are the only endpoints in [main.py](main.py) that read from `T_WC_TMDB_*` tables. Every other entity endpoint goes through the T2S read model — these queries are an **intentional, temporary exception** that exists only because the corresponding `T_WC_T2S_*` tables do not yet exist. Every read site is registered in §6.1 and **must** be swapped to its T2S equivalent as soon as that table lands. Until then, do not treat these endpoints as a template for new code — reaching into `T_WC_TMDB_*` is a last resort, not a pattern.

---

## 2. Data-model facts

Both season and episode are already first-class in the schema. Each has its own surrogate PK and a full set of satellite tables, parallel to how `T_WC_T2S_MOVIE` / `T_WC_T2S_SERIE` are structured.

| | Season | Episode |
|---|---|---|
| Row | `T_WC_TMDB_SEASON.ID_SEASON` (PK) | `T_WC_TMDB_EPISODE.ID_EPISODE` (PK) |
| Parent FK | `ID_SERIE` | `ID_SERIE`, `ID_SEASON` |
| Cast / crew | `T_WC_TMDB_PERSON_SEASON` (`CREDIT_TYPE`, `CREW_DEPARTMENT`, `CREW_JOB`, `CAST_CHARACTER`, `DISPLAY_ORDER`) | `T_WC_TMDB_PERSON_EPISODE` (same columns) |
| Images | `T_WC_TMDB_SEASON_IMAGE` (typed via `TYPE_IMAGE`, e.g. `poster`) | `T_WC_TMDB_EPISODE_IMAGE` (stills — episodes carry `STILL_PATH` directly on the row) |
| Translations | `T_WC_TMDB_SEASON_LANG` (`LANG`, `TITLE`, `OVERVIEW`) | `T_WC_TMDB_EPISODE_LANG` (same shape) |
| Videos | `T_WC_TMDB_SEASON_VIDEO` | `T_WC_TMDB_EPISODE_VIDEO` |
| External IDs | `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB` | `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB` |

Episode-only columns of note: `RUNTIME`, `PRODUCTION_CODE`, `EPISODE_TYPE`, `STILL_PATH`, `VOTE_AVERAGE`, `VOTE_COUNT`.

Person-season / person-episode credit rows join back to `T_WC_T2S_PERSON` for display fields (`PERSON_NAME`, `PROFILE_PATH`) — same pattern as the existing series-credits query at [main.py:1828-1833](main.py#L1828-L1833).

---

## 3. API shape

Mirrors the existing `/movies/{id}` and `/series/{id}` pattern. The signatures below are what shipped; the only intentional drift from earlier drafts is that both endpoints key on the natural composite (series id + season/episode number) rather than the surrogate `ID_SEASON` / `ID_EPISODE`, because clients drilling down from `/series/{id}` know the parent series id and the season/episode index but rarely the TMDb surrogate.

### `GET /seasons/{id_serie}/{season_number}` *(shipped)*
- Base row from `T_WC_TMDB_SEASON` keyed on `(ID_SERIE, SEASON_NUMBER)`. **Migrate to `T_WC_T2S_SEASON` once it exists** — see §6.1.
- Nested arrays:
  - `cast` — `T_WC_TMDB_PERSON_SEASON` JOIN `T_WC_T2S_PERSON`, filtered `CREDIT_TYPE = 'cast'`, ordered by `DISPLAY_ORDER`.
  - `crew` — same join, filtered `CREDIT_TYPE = 'crew'`.
  - `posters` / `backdrops` — `T_WC_TMDB_SEASON_IMAGE` split by `TYPE_IMAGE`, ordered by `DISPLAY_ORDER` (mirrors series).
  - `episodes` — summary rows from `T_WC_TMDB_EPISODE` keyed on `ID_SEASON`, ordered by `EPISODE_NUMBER ASC`. Field set: `ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB`. Length matches the season's `EPISODE_COUNT`; the full episode payload is at `/episodes/{id_serie}/{season_number}/{episode_number}`.
  - `wikipedia_images` / `wikipedia_content` — via `_fetch_wikipedia_images(...)` / `_fetch_wikipedia_content(...)` on the season's `ID_WIKIDATA`. Many seasons do not have an `ID_WIKIDATA`; degrade to empty list.
- Navigation stub:
  - `series` — `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }` so the frontend can render breadcrumbs without a second `/series/{id}` round trip.
- Not yet exposed (open questions):
  - `videos` (`T_WC_TMDB_SEASON_VIDEO`) and `translations` (`T_WC_TMDB_SEASON_LANG`) — see §5.5.

### `GET /episodes/{id_serie}/{season_number}/{episode_number}` *(shipped)*
- Base row from `T_WC_TMDB_EPISODE` keyed on `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)`. **Migrate to `T_WC_T2S_EPISODE` once it exists** — see §6.1.
- Nested arrays:
  - `cast` / `crew` — from `T_WC_TMDB_PERSON_EPISODE` JOIN `T_WC_T2S_PERSON`, same split as above. `DISPLAY_ORDER` upstream — confirm population at migration time per §5.9.
  - `stills` — `T_WC_TMDB_EPISODE_IMAGE`, all rows ordered by `DISPLAY_ORDER`. Episode's canonical frame remains on the base row as `STILL_PATH`.
  - `wikipedia_images` / `wikipedia_content` — via the standard helpers. Almost always empty for episodes.
- Navigation stubs:
  - `season` — `{ ID_SEASON, SEASON_NUMBER, TITLE, POSTER_PATH }` (currently sourced from `T_WC_TMDB_SEASON`; migrates with §6.1).
  - `series` — `{ ID_SERIE, SERIE_TITLE, POSTER_PATH }`.
- Not yet exposed (open questions): videos (`T_WC_TMDB_EPISODE_VIDEO`), translations (`T_WC_TMDB_EPISODE_LANG`) — see §5.5.

### MCP coverage *(not yet shipped)*
- Add `get_season` and `get_episode` tools that proxy to the HTTP endpoints, following the pattern at [main.py:2624-2642](main.py#L2624-L2642). The tool parameter shape should match the HTTP routes: `(id_serie, season_number)` and `(id_serie, season_number, episode_number)`.
- Update the `context://database-scope` MCP resource description to mention the new entities.

### Frontend drill-down this enables
`/series/{id}` (already exposes `seasons[]` with `ID_SEASON`) → click → `/seasons/{id}` (full season + `episodes[]` summary) → click → `/episodes/{id}` (full episode with its own cast/crew/stills). Each level fetches only what it needs; long shows (400+ episodes) don't bloat the `/series` payload.

---

## 4. Prerequisites (blockers)

These need to land before implementation can start. None of them are owned by this work — they are upstream.

- **`T_WC_T2S_SEASON`** — read-model table, copied/derived from `T_WC_TMDB_SEASON`. Should add the curated columns the T2S model usually carries (e.g. weighted rating, popularity — see open question §5.1).
- **`T_WC_T2S_EPISODE`** — same, from `T_WC_TMDB_EPISODE`.
- **`T_WC_T2S_PERSON_SEASON`** and **`T_WC_T2S_PERSON_EPISODE`** — credits tables. Need at minimum `ID_PERSON`, `ID_SEASON` / `ID_EPISODE`, `CREDIT_TYPE`, `CAST_CHARACTER`, `CREW_DEPARTMENT`, `CREW_JOB`, `DISPLAY_ORDER`.
- **`T_WC_T2S_SEASON_IMAGE`** and **`T_WC_T2S_EPISODE_IMAGE`** — images, typed via `TYPE_IMAGE` (poster/backdrop/still as appropriate).
- **`T_WC_T2S_SEASON_LANG`** / **`T_WC_T2S_EPISODE_LANG`** — translations (optional for v1 — see §5.5).
- **`T_WC_T2S_SEASON_VIDEO`** / **`T_WC_T2S_EPISODE_VIDEO`** — videos (optional for v1 — see §5.5).

Once these exist, update [doc/sql/T2S-tables.sql](doc/sql/T2S-tables.sql) so the schema reference reflects them.

---

## 5. Pending questions to resolve at implementation time

### 5.1 Should `T_WC_T2S_SEASON` / `T_WC_T2S_EPISODE` carry `IMDB_RATING_WEIGHTED` and `POPULARITY`?
Other T2S entity tables do (see `T_WC_T2S_MOVIE`, `T_WC_T2S_SERIE`). If yes, ranking / sorting endpoints become possible (e.g. "best-rated episodes of a series"). If no, only `VOTE_AVERAGE` and `VOTE_COUNT` (from TMDb) are available — workable but loses parity with the rest of the T2S surface.

Default suggestion: yes, compute them. Cheap to add, expensive to retrofit later.

### 5.2 ~~Inline episode list inside `/seasons/{id}` — summary or full?~~ **Resolved 2026-05-25 — summary, shipped.**

`/seasons/{id_serie}/{season_number}` now returns an `episodes` array with summary rows only: `ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB`, ordered by `EPISODE_NUMBER ASC`. Full episode payload (cast/crew/stills/Wikipedia) remains on `/episodes/{id_serie}/{season_number}/{episode_number}`. Field set is slightly broader than the original §3 draft (added `ID_EPISODE`, `OVERVIEW`, `AIR_YEAR/MONTH/DAY`, `EPISODE_TYPE`, `ID_IMDB`, `ID_WIKIDATA`, `ID_TVDB`) to cover navigation, season-grid rendering, and external-id linking without forcing a second call. Listed here only so the numbering of the original questions stays stable.

### 5.3 Keep `seasons[]` inline on `/series/{id}` once `/seasons/{id}` exists?
Two options:
- **Keep inline summary** (current behavior). Frontend can render the season grid on the series page without a second call. Slight payload overhead.
- **Replace with link list** (`[{ID_SEASON, SEASON_NUMBER}]` only). Forces a second call to render the season grid.

Recommendation: keep the current inline summary. The payload size is bounded (most series have <20 seasons) and it preserves the one-call season grid.

### 5.4 `DELETED` filter — what's the policy?
Current `/series/{id}` and the shipped `seasons` query in (1) do not filter `DELETED`. Episodes inherit row-level `DELETED` from TMDb too. Decision needed: stay consistent with existing endpoints (no filter) or tighten across all new endpoints (filter `DELETED = 0 OR DELETED IS NULL`). The wider question affects all T2S endpoints, not just these.

Default suggestion: stay consistent (no filter) until there's a reason to change.

### 5.5 Videos and translations in v1, or defer?
Both have clear analogues (`T_WC_TMDB_SEASON_VIDEO`, `T_WC_TMDB_SEASON_LANG`, and episode equivalents) but no other endpoint exposes them today. Including them creates new precedent (the only existing video-like surface is `wikipedia_images`).

Default suggestion: defer videos to v2; include translations only if the frontend has a confirmed multilingual need at launch.

### 5.6 ~~Question~~ — covered by the migration rule at the top of this document
Not actually open. The migration rule (top callout) and the registered migration site in §6.1 make this binding: the `seasons` query in (1) must move from `T_WC_TMDB_SEASON` to `T_WC_T2S_SEASON` the moment that table exists, and the README note at [README.md:611](README.md#L611) must be updated at the same time. Listed here only so the numbering of the original questions stays stable.

### 5.7 MCP tool descriptions and `context://database-scope`
The `context://database-scope` resource currently lists series-level fields including `NUMBER_OF_SEASONS` / `NUMBER_OF_EPISODES`. When seasons/episodes become first-class, add brief sections under "TV Series" describing the new tables so MCP clients know they can drill in.

### 5.8 Text-to-SQL placeholder support
Should the LLM be able to filter by episode-level facts (e.g. "episodes of *Breaking Bad* season 5 directed by Vince Gilligan")? That implies:
- Adding the season/episode tables to [data/text_to_sql.md](data/text_to_sql.md) schema section.
- Possibly new placeholders (`Season_number`, `Episode_number`) handled via the regex branch in [entity.py](entity.py).

Recommendation: defer. Endpoints first; LLM coverage is a separate scope and would need a `strapiversion` bump.

### 5.9 Sort order for credits
For season cast/crew the TMDb feed exposes `DISPLAY_ORDER` per credit row — match the series pattern ([main.py:1832](main.py#L1832)). For episode credits, confirm whether `DISPLAY_ORDER` is populated upstream; if not, fall back to `CREDIT_TYPE` then person popularity.

### 5.10 Wikipedia images availability
Most TMDb seasons and almost no episodes will have an `ID_WIKIDATA`. The `wikipedia_images` field should still be defined (consistency with `/series/{id}`) but expect it to be empty for the vast majority of rows.

---

## 6. Touchpoints when implementation happens

### 6.1 Migration sites (TMDb → T2S) — must be swept whenever a T2S table lands

Registered call sites where the code reads from `T_WC_TMDB_*` because the T2S equivalent does not yet exist. Per the migration rule at the top of this document, each entry **must** be migrated to the T2S table as soon as that table is available, in the same change that introduces the T2S table.

| Site | Current source | Target | Notes |
|---|---|---|---|
| `seasons` array in [`GET /series/{id}`](main.py#L1914-L1922) | `T_WC_TMDB_SEASON` | `T_WC_T2S_SEASON` | Also update the README row at [README.md:611](README.md#L611) (drop the "TMDb source" caveat). Re-check the column list against §5.1 if `IMDB_RATING_WEIGHTED` / `POPULARITY` are added on the T2S side. |
| Base row in [`GET /seasons/{id_serie}/{season_number}`](main.py) | `T_WC_TMDB_SEASON` | `T_WC_T2S_SEASON` | The endpoint keys on `(ID_SERIE, SEASON_NUMBER)` and returns all season columns via `SELECT *`; recheck the field surface against §5.1 (`IMDB_RATING_WEIGHTED` / `POPULARITY`) when migrating. |
| `cast` / `crew` arrays in [`GET /seasons/{id_serie}/{season_number}`](main.py) | `T_WC_TMDB_PERSON_SEASON` | `T_WC_T2S_PERSON_SEASON` | Joins `T_WC_T2S_PERSON` for display fields (`PERSON_NAME`, `PROFILE_PATH`); split on `CREDIT_TYPE`, ordered by `DISPLAY_ORDER`. |
| `posters` / `backdrops` arrays in [`GET /seasons/{id_serie}/{season_number}`](main.py) | `T_WC_TMDB_SEASON_IMAGE` | `T_WC_T2S_SEASON_IMAGE` | Split by `TYPE_IMAGE` (`poster` vs `backdrop`), ordered by `DISPLAY_ORDER`. |
| `episodes` summary array in [`GET /seasons/{id_serie}/{season_number}`](main.py) | `T_WC_TMDB_EPISODE` | `T_WC_T2S_EPISODE` | Summary rows only (`ID_EPISODE, EPISODE_NUMBER, TITLE, OVERVIEW, DAT_AIR, AIR_YEAR, AIR_MONTH, AIR_DAY, RUNTIME, EPISODE_TYPE, STILL_PATH, VOTE_AVERAGE, VOTE_COUNT, ID_IMDB, ID_WIKIDATA, ID_TVDB`) keyed on `ID_SEASON`, ordered by `EPISODE_NUMBER ASC`. Migrates in the same change as the `/episodes/{...}` base row site below. Re-check the column list against §5.1 if `IMDB_RATING_WEIGHTED` / `POPULARITY` are added on the T2S side. |
| Base row in [`GET /episodes/{id_serie}/{season_number}/{episode_number}`](main.py) | `T_WC_TMDB_EPISODE` | `T_WC_T2S_EPISODE` | The endpoint keys on `(ID_SERIE, SEASON_NUMBER, EPISODE_NUMBER)` and returns all episode columns via `SELECT *`; recheck the field surface against §5.1 (`IMDB_RATING_WEIGHTED` / `POPULARITY`) when migrating. |
| `cast` / `crew` arrays in [`GET /episodes/{id_serie}/{season_number}/{episode_number}`](main.py) | `T_WC_TMDB_PERSON_EPISODE` | `T_WC_T2S_PERSON_EPISODE` | Joins `T_WC_T2S_PERSON` for display fields (`PERSON_NAME`, `PROFILE_PATH`); split on `CREDIT_TYPE`, ordered by `DISPLAY_ORDER`. Confirm `DISPLAY_ORDER` is populated upstream per §5.9 — if not, fall back to `CREDIT_TYPE` then person popularity at migration time. |
| `stills` array in [`GET /episodes/{id_serie}/{season_number}/{episode_number}`](main.py) | `T_WC_TMDB_EPISODE_IMAGE` | `T_WC_T2S_EPISODE_IMAGE` | Returns all `TYPE_IMAGE` rows, not just stills, in case other image types appear upstream; ordered by `DISPLAY_ORDER`. |
| `season` navigation stub in [`GET /episodes/{id_serie}/{season_number}/{episode_number}`](main.py) | `T_WC_TMDB_SEASON` | `T_WC_T2S_SEASON` | Single-row `{ID_SEASON, SEASON_NUMBER, TITLE, POSTER_PATH}` lookup by `ID_SEASON`. Migrates in the same change as the `seasons` array site above. |

If a new endpoint ships before its T2S table exists and ends up reading from `T_WC_TMDB_*`, **append a row here** in the same commit so the next migration sweep catches it. An untracked TMDb read is a bug.

### 6.2 Endpoint work, once §6.1 is clear and the T2S tables exist

1. **[main.py](main.py)** — add `get_season()` and `get_episode()` endpoints (mirror the layout of `get_series` at [main.py:1795-1937](main.py#L1795-L1937)). Add MCP `get_season` / `get_episode` tools after the existing `get_series` tool at [main.py:2624-2642](main.py#L2624-L2642).
2. **[README.md](README.md)** — add field tables for `/seasons/{id}` and `/episodes/{id}` near the existing `/series/{id}` table around [README.md:611](README.md#L611).
3. **[doc/sql/T2S-tables.sql](doc/sql/T2S-tables.sql)** — should already reflect the new T2S tables (this is a prerequisite per §4, not part of the endpoint work).
4. **No edits to [data/text_to_sql.md](data/text_to_sql.md)** unless §5.8 is also pursued — endpoints alone don't change the text-to-SQL surface.
5. **No `strapiversion` bump** — pure additive endpoint work, Python-only restart picks it up. The cache key is for `/search/text2sql` only.

---

## 7. Out of scope (do not pursue without separate ask)

- Season/episode placeholders in text-to-SQL (see §5.8).
- A new ChromaDB collection for seasons/episodes. They are not searched by name today and the parent series collection already covers the common "show me X" query.
- Closed-vocab handling for `EPISODE_TYPE` (`pilot`, `finale`, `mid_season`, etc.). Worth doing only if user questions start filtering on it.
