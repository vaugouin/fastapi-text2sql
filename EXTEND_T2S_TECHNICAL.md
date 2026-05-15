# Extending `T_WC_T2S_TECHNICAL` — Impact Analysis

Status: **Analysis only — no code or schema change is proposed for this document.**
Date: 2026-05-14

---

## 1. Context & motivation

Three related changes to the `T_WC_T2S_TECHNICAL` reference model are under consideration:

1. **Move aspect ratio into `T_WC_T2S_TECHNICAL`.**
   `T_WC_T2S_MOVIE.ASPECT_RATIO` is a single VARCHAR column today. A movie can ship in several aspect ratios across versions (theatrical 2.35, home video 1.78, IMAX 1.43) — a single-valued column cannot represent that. Modeling aspect ratio as rows in `T_WC_T2S_TECHNICAL` (linked many-to-many through the existing `T_WC_T2S_MOVIE_TECHNICAL` junction) matches how every other technical attribute is already represented.

2. **Add `color_movie` / `black_and_white_movie` / `silent_movie` rows in `T_WC_T2S_TECHNICAL`.**
   The boolean flags `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT` already live on `T_WC_T2S_MOVIE`. Promoting them to technical rows lets these classifications surface inside the planned `/movies` metadata collection, alongside the other technical metadata (sound systems, film formats, etc.).

3. **Expose a metadata collection on `/movies/{id}`.**
   The endpoint already returns one-to-many collections (genres, topics, lists, collections, movements, companies, posters). It does **not** currently return anything from `T_WC_T2S_MOVIE_TECHNICAL`. This is the gap that motivates the other two changes — without exposing the junction, the data is invisible to consumers.

The user's primary concern: not breaking the existing pipeline — entity extraction, closed-vocabulary alias matching, SQL generation, entity resolution, SQL caching, the `/movies` payload, and the MCP tools. Every option below is rated on those axes.

---

## 2. Current model inventory

This is the anchor every later section refers back to. All file:line references verified at the time of writing.

### 2.1 Schema

| Concern | Today | File:line |
|---|---|---|
| Aspect ratio (per movie) | `T_WC_T2S_MOVIE.ASPECT_RATIO varchar(20)`, indexed | [doc/sql/T2S-tables.sql:653](doc/sql/T2S-tables.sql#L653), [:703](doc/sql/T2S-tables.sql#L703) |
| Color flag | `T_WC_T2S_MOVIE.IS_COLOR int(11)`, indexed | [doc/sql/T2S-tables.sql:647](doc/sql/T2S-tables.sql#L647), [:698](doc/sql/T2S-tables.sql#L698) |
| Black & white flag | `T_WC_T2S_MOVIE.IS_BLACK_AND_WHITE int(11)`, indexed | [doc/sql/T2S-tables.sql:648](doc/sql/T2S-tables.sql#L648), [:699](doc/sql/T2S-tables.sql#L699) |
| Silent flag | `T_WC_T2S_MOVIE.IS_SILENT int(11)`, indexed | [doc/sql/T2S-tables.sql:649](doc/sql/T2S-tables.sql#L649), [:700](doc/sql/T2S-tables.sql#L700) |
| 3D flag | `T_WC_T2S_MOVIE.IS_3D int(11)`, indexed | [doc/sql/T2S-tables.sql:650](doc/sql/T2S-tables.sql#L650), [:701](doc/sql/T2S-tables.sql#L701) |
| Technical reference table | `T_WC_T2S_TECHNICAL(ID_TECHNICAL, DESCRIPTION, TECHNICAL_TYPE, …)` — 56 rows | [doc/sql/T2S-tables.sql:1987-2008](doc/sql/T2S-tables.sql#L1987-L2008) |
| Junction | `T_WC_T2S_MOVIE_TECHNICAL(ID_MOVIE, ID_TECHNICAL, …)` | [doc/sql/T2S-tables.sql:1013-1035](doc/sql/T2S-tables.sql#L1013-L1035) |
| Series-side junction | **Does not exist yet.** | — |

`TECHNICAL_TYPE` value counts today:

| TECHNICAL_TYPE | Count |
|---|---|
| `color_technology` | 16 |
| `film_format` | 6 |
| `film_technology` | 18 |
| `sound_system` | 9 |
| `sound_technology` | 7 |
| **Total** | **56** |

### 2.2 The two resolver paths

The pipeline already implements two distinct resolution strategies for closed vocabularies; understanding which path each entity uses is essential for the impact analysis below.

**ID-based path (`Technical_format`):**
- Canonical map loaded once at startup: `SELECT ID_TECHNICAL AS id, DESCRIPTION AS name FROM T_WC_T2S_TECHNICAL WHERE DESCRIPTION IS NOT NULL AND (DELETED = 0 OR DELETED IS NULL)` — [closed_vocab.py:191-194](closed_vocab.py#L191-L194), [:250-254](closed_vocab.py#L250-L254).
- `resolve_technical(raw_value)` returns an integer ID using RapidFuzz with `SCORE_CUTOFF=85` and `SCORE_MARGIN=5` — [closed_vocab.py:340-355](closed_vocab.py#L340-L355).
- Substitution branch in [entity.py:380-386](entity.py#L380-L386): converts ID to string and replaces `'{{Technical_format1}}'` and `{{Technical_format1}}` with the bare integer (no quotes). The SQL uses `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL = 27`.

**String-canonical path (`Aspect_ratio`, `Status_name`, `Serie_type`, `Department_name`):**
- Canonical map loaded once: `SELECT DISTINCT ASPECT_RATIO AS V FROM T_WC_T2S_MOVIE WHERE ASPECT_RATIO IS NOT NULL AND ASPECT_RATIO REGEXP '^[0-9]+,[0-9]+$'` — [closed_vocab.py:162-172](closed_vocab.py#L162-L172), [:220-224](closed_vocab.py#L220-L224). The REGEXP filter is deliberate: it admits only well-formed comma-decimal values like `'1,33'`, `'1,85'`, `'2,35'`, excluding noisy DB variants like `'4:3'`, `'4/3'`, `'16:9'`, `'235:1'` so those fall through to the JSON alias layer.
- `closed_vocab.resolve("Aspect_ratio", raw_value)` returns the canonical comma-decimal string — [closed_vocab.py:293](closed_vocab.py#L293).
- Substitution branch in [entity.py:388-421](entity.py#L388-L421): wraps the canonical in single quotes. The SQL ends up with `T_WC_T2S_MOVIE.ASPECT_RATIO = '1,85'`.

### 2.3 Aliases (`data/closed_vocabularies.json`)

- `Aspect_ratio` block — [data/closed_vocabularies.json:106-172](data/closed_vocabularies.json#L106-L172): 54 aliases targeting comma-decimal canonicals (`"1.85" → "1,85"`, `"4:3" → "1,33"`, `"widescreen" → "1,85"`, `"Academy ratio" → "1,37"`, `"16:9" → "1,78"`, etc.). The header comment at [data/closed_vocabularies.json:107](data/closed_vocabularies.json#L107) explains the REGEXP filtering rationale and **explicitly states** that `anamorphic` / `scope` / `cinemascope` belong under `Technical_format`, not here.
- `Technical_format` block — [data/closed_vocabularies.json:205-237](data/closed_vocabularies.json#L205-L237): aliases targeting canonical `DESCRIPTION` strings (`"35mm" → "35 mm"`, `"scope" → "cinemascope"`, `"imax format" → "imax"`, `"5.1 surround" → "5.1"`, etc.).

### 2.4 Prompts

- **Entity extraction** ([data/entity_extraction.md](data/entity_extraction.md)):
  - `Aspect_ratio` placeholder defined at [lines 193-209](data/entity_extraction.md#L193-L209): "extract only when the question filters or asks about the movie's aspect ratio".
  - `Technical_format` placeholder defined at [lines 231-249](data/entity_extraction.md#L231-L249): covers sound systems, color technologies, film technologies, sound technologies, film formats.
  - **The prompt teaches the LLM that these are two distinct entity types**, and downstream prompts assume the split.

- **Text-to-SQL** ([data/text_to_sql.md](data/text_to_sql.md)):
  - Schema dump exposes `ASPECT_RATIO VARCHAR(20)`, `IS_COLOR INT`, `IS_BLACK_AND_WHITE INT`, `IS_SILENT INT` as columns on `T_WC_T2S_MOVIE` — [lines 81-83](data/text_to_sql.md#L81-L83).
  - Junction `T_WC_T2S_MOVIE_TECHNICAL(ID_ROW, ID_MOVIE, ID_TECHNICAL)` shown at [lines 276-280](data/text_to_sql.md#L276-L280).
  - Color/B&W/silent SQL rule at [lines 736-739](data/text_to_sql.md#L736-L739): "Use `IS_COLOR = 1` for color movies … `IS_BLACK_AND_WHITE = 1` for black and white … `IS_SILENT = 1` for silent movies."
  - `Technical_format` placeholder substitution rule at [lines 276-279](data/text_to_sql.md#L276-L279), [:776-779](data/text_to_sql.md#L776-L779): `T_WC_T2S_MOVIE_TECHNICAL.ID_TECHNICAL = '{{Technical_format1}}'`.

### 2.5 `/movies/{id}` endpoint

- Defined at [main.py:1620-1742](main.py#L1620-L1742). Top of the function does `SELECT * FROM T_WC_T2S_MOVIE WHERE ID_MOVIE = %s` — every column comes for free, including `ASPECT_RATIO`, `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT`, `IS_3D`.
- Already returns: `genres`, `companies`, `production_countries`, `spoken_languages`, `topics`, `lists`, `collections`, `movements`, `credits`, `nominations`, `posters` ([main.py:1654-1714](main.py#L1654-L1714)).
- **No `technicals` collection today.** A natural insertion point exists between [main.py:1698](main.py#L1698) and [main.py:1712](main.py#L1712).

### 2.6 MCP exposure

- The MCP tool `get_movie` wraps `/movies/{id}` and documents the inline payload at [MCP.md:445-448](MCP.md#L445-L448) (including `"ASPECT_RATIO": "2.35"`, `"IS_COLOR": 1`, etc.).
- `get_movie` docstring at [main.py:2680](main.py#L2680) lists the same fields.
- **No `get_technical` tool exists** — the entity getters cover movie / series / person / company / network / collection / topic / list / movement / group / death / award / nomination / location, but not technical.

### 2.7 SQL cache

- The `/search/text2sql` pipeline ([main.py:407-480](main.py#L407-L480)) caches resolved SQL by question hash. Any change to a column referenced by cached SQL silently invalidates those rows: subsequent cache hits return SQL that no longer matches the schema.

---

## 3. Proposal A — Aspect ratio in `T_WC_T2S_TECHNICAL`

Two options are documented below. The user has not committed to either.

### 3.1 Option A.1 — Full migration to ID-based resolution

**Model change**
- Insert ~12 rows in `T_WC_T2S_TECHNICAL` with `TECHNICAL_TYPE='aspect_ratio'`, one per canonical ratio (`1.33`, `1.37`, `1.66`, `1.78`, `1.85`, `2.20`, `2.35`, `2.39`, `2.40`, `2.55`, IMAX `1.43`, anamorphic widths if relevant).
- Convention recommendation: use **dot-decimal** `DESCRIPTION` (e.g. `"1.85"`) to align with the existing readable-canonical style of `T_WC_T2S_TECHNICAL`. Comma-decimal is a French SQL-storage detail that should not leak into a normalized reference table.
- Backfill `T_WC_T2S_MOVIE_TECHNICAL` from existing `T_WC_T2S_MOVIE.ASPECT_RATIO` values, normalizing comma → dot and mapping noisy forms (`'4:3' → 1.33`, `'235:1' → 2.35`, `'16:9' → 1.78`).
- Drop or deprecate `T_WC_T2S_MOVIE.ASPECT_RATIO` and its index.

**Pipeline impact (Option A.1)**

| Stage | Change | File:line |
|---|---|---|
| Schema | Drop `ASPECT_RATIO` column + index; insert ~12 rows in `T_WC_T2S_TECHNICAL`; backfill rows in `T_WC_T2S_MOVIE_TECHNICAL` | [doc/sql/T2S-tables.sql:653](doc/sql/T2S-tables.sql#L653), [:703](doc/sql/T2S-tables.sql#L703), [:1987](doc/sql/T2S-tables.sql#L1987) |
| Canonical loader | Delete `_ASPECT_RATIO_QUERY` block; delete the `loaded["Aspect_ratio"] = …` block. New rows arrive automatically through the existing `Technical_format` canonical map. | [closed_vocab.py:162-172](closed_vocab.py#L162-L172), [:220-224](closed_vocab.py#L220-L224) |
| Aliases JSON — Decision point | (a) Fold all 54 `Aspect_ratio` aliases into the `Technical_format` block, retargeting from comma-decimal to dot-decimal DESCRIPTIONs (`"4:3" → "1.33"`, `"widescreen" → "1.85"`). OR (b) Keep `Aspect_ratio` as a separate alias namespace whose values now reference DESCRIPTIONs. Option (a) is cleaner and removes the rationale documented at line 107; option (b) preserves extraction-time separation but adds dispatch complexity. **The 107 comment will need to be rewritten or removed in both cases.** | [data/closed_vocabularies.json:106-172](data/closed_vocabularies.json#L106-L172) |
| Entity extraction prompt — Decision point | (a) Retire the `Aspect_ratio` placeholder entirely; everything resolves to `Technical_format`. (b) Keep `Aspect_ratio` as a placeholder sub-type for prompt readability; resolver must dispatch it to `resolve_technical` rather than `resolve("Aspect_ratio", …)`. Option (a) is simpler. | [data/entity_extraction.md:193-209](data/entity_extraction.md#L193-L209) |
| Resolver dispatch | Remove `Aspect_ratio` from the string-canonical branch in `resolve_entities`. If the placeholder is kept (extraction-prompt option b), add a forwarding rule: `key.startswith("Aspect_ratio")` → `resolve_technical(raw_value)` → numeric ID substitution. If the placeholder is retired, no resolver code change is required. | [entity.py:388-421](entity.py#L388-L421) |
| Text-to-SQL prompt | Remove `ASPECT_RATIO VARCHAR(20)` from the schema dump. Update the placeholder substitution rule from single-quoted string to numeric ID. Add a worked example of `JOIN T_WC_T2S_MOVIE_TECHNICAL mt ON mt.ID_MOVIE = m.ID_MOVIE JOIN T_WC_T2S_TECHNICAL t ON t.ID_TECHNICAL = mt.ID_TECHNICAL WHERE t.TECHNICAL_TYPE = 'aspect_ratio' AND t.ID_TECHNICAL = …`. The LLM also needs guidance that aspect_ratio is now `TECHNICAL_TYPE='aspect_ratio'` rather than a column. | [data/text_to_sql.md:81](data/text_to_sql.md#L81), [:276-280](data/text_to_sql.md#L276-L280), [:776-779](data/text_to_sql.md#L776-L779) |
| `/movies/{id}` | Remove `ASPECT_RATIO` from the row payload, or compute a primary ratio from the technicals collection for backward compat. | [main.py:1641](main.py#L1641) |
| MCP docs | Remove `"ASPECT_RATIO"` from the inline JSON at [MCP.md:445-448](MCP.md#L445-L448) and from the docstring listing at [MCP.md:560](MCP.md#L560), [main.py:2680](main.py#L2680). | as listed |
| SQL cache | **All cached SQL referencing `T_WC_T2S_MOVIE.ASPECT_RATIO` becomes wrong.** Flush via `DELETE FROM <cache_table> WHERE SQL_QUERY LIKE '%ASPECT_RATIO%'` before deploy, or accept a cache cold period. | (cache impl in [main.py:407-480](main.py#L407-L480)) |
| Evaluation | Run `eval/text2sql-eval.py` against questions covering aspect ratio (Academy ratio, widescreen, 2.35, "shot in scope") and noisy aliases (`4:3`, `16:9`). Add at least one regression where a single movie has multiple ratios. | [eval/](eval/) |
| AGENTS.md / closed-vocab-entity-plan.md | Both reference `Aspect_ratio` as a "string-canonical lookup entity" / "**SHIPPED**" pattern. Both need updating to reflect the new path. | [AGENTS.md:44](AGENTS.md#L44), [:128](AGENTS.md#L128), [:298-300](AGENTS.md#L298-L300); [closed-vocab-entity-plan.md:67-72](closed-vocab-entity-plan.md#L67-L72), [:204-206](closed-vocab-entity-plan.md#L204-L206), [:295](closed-vocab-entity-plan.md#L295) |

**Risks (Option A.1)**
- **Alias retargeting must be exhaustive.** All 54 `Aspect_ratio` aliases currently target comma-decimal canonicals. Each must be remapped to a dot-decimal `DESCRIPTION` value. Missing one breaks resolution silently — the LLM emits `{{Aspect_ratio1}}` and the resolver leaves it unresolved.
- **The REGEXP filter at [closed_vocab.py:171](closed_vocab.py#L171) is no longer needed**, but its role (excluding noisy DB values from canonicals so aliases fire) is still required during backfill — `'4:3'`, `'235:1'`, etc. must be normalized when inserting into `T_WC_T2S_MOVIE_TECHNICAL`, not carried over verbatim.
- **The SQL-prompt change is the largest lift**: the LLM has been trained over many evaluation iterations to write `T_WC_T2S_MOVIE.ASPECT_RATIO = '1,85'`. Switching to a JOIN pattern requires re-running evals end-to-end to confirm no regressions.
- **Two evaluation-pinned questions** in `eval/data/evaluation/` may have expected-SQL strings that reference the old column directly; those golden files would need updating.

### 3.2 Option A.2 — Dual model (column stays, junction added)

**Model change**
- Keep `T_WC_T2S_MOVIE.ASPECT_RATIO` as the primary/theatrical ratio (fast single-value indexed filter, no JOIN).
- Add aspect-ratio rows to `T_WC_T2S_TECHNICAL` *and* link via `T_WC_T2S_MOVIE_TECHNICAL` **only when a movie has multiple ratios**. Single-ratio movies stay column-only.
- `/movies/{id}` returns both: top-level `ASPECT_RATIO` (primary) plus an `aspect_ratios` array (full set, when present).

**Pipeline impact (Option A.2)**

| Stage | Change |
|---|---|
| Schema | Additive only — new rows in `T_WC_T2S_TECHNICAL` and `T_WC_T2S_MOVIE_TECHNICAL`. Column and index preserved. |
| Canonical loader | Unchanged. Both `Aspect_ratio` (column-derived) and `Technical_format` (table-derived) maps continue to exist. Sync risk: if a ratio is only ever in `T_WC_T2S_TECHNICAL` (never in `T_WC_T2S_MOVIE.ASPECT_RATIO`), the `Aspect_ratio` canonical map won't know about it. Mitigation: backfill the column with the primary ratio whenever a movie has at least one. |
| Aliases JSON | Unchanged. |
| Entity extraction prompt | Unchanged. |
| Resolver dispatch | Unchanged. |
| Text-to-SQL prompt | **Riskiest change in this option.** Adding the junction path as a *second* way to filter aspect ratio invites LLM inconsistency. Recommendation: do NOT mention the junction path for aspect ratio in the SQL prompt; the column path remains the only documented filter, and the junction exists purely to back the `/movies` metadata collection. |
| `/movies/{id}` | Add an `aspect_ratios` array alongside the existing `ASPECT_RATIO` field. |
| MCP docs | Add description of the new collection field. |
| SQL cache | Unaffected. |
| Evaluation | Add one regression case for a multi-ratio movie's `/movies/{id}` response. No text2sql regressions expected. |

**Risks (Option A.2)**
- **Two sources of truth** for the same concept. A film whose primary theatrical ratio is 2.35 and whose home video is 1.78 has `ASPECT_RATIO='2,35'` in the column *and* both 2.35 and 1.78 in the junction. A reader has to know which to trust for which purpose.
- **Mild sync burden**: any backfill or ingestion job that writes aspect ratios has to write to both places, or write to the junction first and derive the column.
- **No SQL-prompt risk if the junction path is explicitly hidden from the SQL prompt.** The user keeps full backward compatibility with every existing alias, the REGEXP filter, the entity extraction prompt, and the cached SQL.

### 3.3 A.1 vs A.2 — recommendation

**Ship A.2 first.** It is additive, low-risk, and unlocks the metadata collection (the user's stated goal) immediately. Defer A.1 until either (a) the column starts feeling like dead weight (rarely happens once it serves "primary ratio"), or (b) data-quality issues force normalization. The conceptual cleanliness of A.1 is real but does not outweigh the pipeline risk today.

---

## 4. Proposal B — Color / B&W / Silent in `T_WC_T2S_TECHNICAL`

### 4.1 Option B.1 — Keep flags AND add technical rows

**Model change**
- Insert three rows in `T_WC_T2S_TECHNICAL`. Suggested values:

  | `DESCRIPTION` | `TECHNICAL_TYPE` |
  |---|---|
  | `color_movie` | `medium_format` |
  | `black_and_white_movie` | `medium_format` |
  | `silent_movie` | `medium_format` |

  Rationale: `medium_format` reads parallel to `film_format` (which is a physical format) without colliding with it. Alternative naming under discussion: `movie_classification`. The user should pick one before insertion.
- Backfill `T_WC_T2S_MOVIE_TECHNICAL` from the existing flags: every movie with `IS_COLOR=1` gets a row pointing at the `color_movie` ID, etc.
- **Keep the flag columns and their indexes** on `T_WC_T2S_MOVIE`.

**Pipeline impact (Option B.1)**

| Stage | Change | File:line |
|---|---|---|
| Schema | Insert 3 rows in `T_WC_T2S_TECHNICAL`; backfill `T_WC_T2S_MOVIE_TECHNICAL` from flags; columns + indexes preserved. | [doc/sql/T2S-tables.sql:1987](doc/sql/T2S-tables.sql#L1987) |
| Canonical loader | **Unchanged.** New rows are picked up automatically by `_TECHNICAL_CANONICALS_QUERY` at startup. | [closed_vocab.py:191-194](closed_vocab.py#L191-L194) |
| Aliases JSON | Add to the `Technical_format` block: `"color" → "color_movie"`, `"colour" → "color_movie"`, `"in color" → "color_movie"`, `"color film" → "color_movie"`, `"black and white" → "black_and_white_movie"`, `"black-and-white" → "black_and_white_movie"`, `"B&W" → "black_and_white_movie"`, `"BW" → "black_and_white_movie"`, `"monochrome" → "black_and_white_movie"`, `"silent" → "silent_movie"`, `"silent film" → "silent_movie"`. Avoid adding `"talkie"` as a negation alias — the resolver is positive-match only, and negation should stay in the SQL prompt. | [data/closed_vocabularies.json:205-237](data/closed_vocabularies.json#L205-L237) |
| Entity extraction prompt | **Important risk.** Today the LLM is taught at [data/text_to_sql.md:736-739](data/text_to_sql.md#L736-L739) to translate "color movies" / "B&W films" / "silent films" directly into `IS_COLOR = 1` etc. at SQL-generation time — they are not extracted as placeholders. If we now extend `Technical_format` extraction at [data/entity_extraction.md:231-249](data/entity_extraction.md#L231-L249) to include "color movie" / "B&W film" / "silent film", the LLM might extract a placeholder where the existing rule expects raw words. Two paths exist (see below). Recommended: leave the extraction prompt unchanged; the new technical rows are **only** for the metadata collection, not for filtering. |
| Text-to-SQL prompt | **Two valid sub-options:** (i) Leave the rule at [lines 736-739](data/text_to_sql.md#L736-L739) untouched; `IS_COLOR = 1` remains the only documented filter path; the junction rows exist purely for `/movies` payload. (ii) Document both paths and mark `IS_COLOR = 1` as preferred. Sub-option (i) is dramatically safer for evaluation. |
| Resolver dispatch | **Unchanged.** Even if the SQL prompt eventually documents the junction path, `Technical_format` already dispatches to `resolve_technical()` for the new rows. | [entity.py:380-386](entity.py#L380-L386) |
| `/movies/{id}` | Color / B&W / silent now appear in two places: top-level `IS_COLOR / IS_BLACK_AND_WHITE / IS_SILENT` flags AND the new technicals collection. Decision: include in both (recommended for backward compat with existing MCP consumers) or only the collection (cleaner but breaks anyone reading the flags directly). | [main.py:1620-1742](main.py#L1620-L1742) |
| MCP docs | Update payload example at [MCP.md:445-448](MCP.md#L445-L448) to show both the flags AND the new technicals array. Update docstring at [main.py:2680](main.py#L2680). | as listed |
| SQL cache | **Unaffected.** Existing `IS_COLOR = 1` SQL stays valid. |
| Evaluation | Add regression: "color movies of 1939" must still generate `IS_COLOR = 1`; "silent films of the 1920s" → `IS_SILENT = 1`; "black and white movies with Bogart" → `IS_BLACK_AND_WHITE = 1`. Add a `/movies/{id}` payload assertion that the technicals array includes the matching row. | [eval/](eval/) |

**Risks (Option B.1)**
- Mostly: **the LLM might start picking the junction path inconsistently** if the SQL prompt ever documents it. Mitigation: don't document it. The flags stay the sole filter path; the junction is metadata-collection-only.
- **Backfill drift**: if `IS_COLOR` is later updated for a movie but the junction row isn't rewritten, the two diverge. Mitigation: add a one-shot backfill script; if the data is mutable later, consider a DB trigger or fold the update into the ingestion path.

### 4.2 Option B.2 — Full migration (drop flags)

**Model change**
- Drop the columns `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT` and their indexes.
- All filtering goes through the junction.

**Pipeline impact (Option B.2)**

Everything in B.1 *plus*:

| Stage | Change |
|---|---|
| Schema | Drop three columns + three indexes. Backfill the junction *exhaustively* (B.1 does this too, but here the flags are no longer the safety net). |
| Text-to-SQL prompt | Rewrite the rules at [data/text_to_sql.md:736-739](data/text_to_sql.md#L736-L739) entirely. Every "color movie" / "B&W" / "silent" question now requires a JOIN. The LLM must be taught the new pattern. |
| SQL cache | **All cached SQL referencing `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT` becomes wrong.** Flush via `DELETE … WHERE SQL_QUERY LIKE '%IS_COLOR%' OR SQL_QUERY LIKE '%IS_BLACK_AND_WHITE%' OR SQL_QUERY LIKE '%IS_SILENT%'`. The "color movies of 1939" question is *extremely* common — this is a high-impact cache cold. |
| Performance | Every color/B&W/silent filter now does a JOIN instead of a single indexed column scan. Not catastrophic, but measurable on large result sets. |
| MCP docs | The inline `"IS_COLOR": 1` payload at [MCP.md:446](MCP.md#L446) is gone. Any downstream consumer reading these fields breaks silently. |

**Risks (Option B.2)**
- High SQL-cache churn for very common queries.
- Performance regression for the most common filters in the corpus.
- Breaking change for MCP / API consumers reading the flags directly.

### 4.3 B.1 vs B.2 — recommendation

**B.1 is the strongly recommended path.** The flags are cheap, well-indexed, well-loved by the LLM, and exposed inline on `/movies/{id}` for backward compat. Adding three rows + ~few thousand junction entries costs nothing and unlocks the metadata collection. B.2 is conceptually cleaner but trades real performance and stability for that cleanliness.

---

## 5. Proposal C — Metadata collection on `/movies/{id}`

This is the unifying change. It is **independent of Proposals A and B** — it can ship today against the current 56 rows of `T_WC_T2S_TECHNICAL`, and is the lowest-risk piece of the whole plan.

### 5.1 Response shape

Insert a new `technicals` field in the JSON response, between the existing collections (between `movements` and `nominations`):

```json
"technicals": [
  {"id_technical": 12, "description": "technicolor", "technical_type": "color_technology"},
  {"id_technical": 27, "description": "70 mm",       "technical_type": "film_format"},
  {"id_technical": 41, "description": "dolby",       "technical_type": "sound_system"}
]
```

Once Proposals A and B are added, the same array starts surfacing `aspect_ratio` and `medium_format` rows automatically — no further endpoint changes needed.

### 5.2 Impact

- **Endpoint code**: one new query block in [main.py:1620-1742](main.py#L1620-L1742), between [main.py:1698](main.py#L1698) and [main.py:1712](main.py#L1712):
  ```sql
  SELECT mt.ID_TECHNICAL, t.DESCRIPTION, t.TECHNICAL_TYPE
  FROM T_WC_T2S_MOVIE_TECHNICAL mt
  JOIN T_WC_T2S_TECHNICAL t ON t.ID_TECHNICAL = mt.ID_TECHNICAL
  WHERE mt.ID_MOVIE = %s AND (mt.DELETED = 0 OR mt.DELETED IS NULL)
    AND (t.DELETED = 0 OR t.DELETED IS NULL)
  ORDER BY t.TECHNICAL_TYPE, mt.DISPLAY_ORDER, t.DESCRIPTION
  ```
- **MCP docstring**: add `technicals` to the field listing at [main.py:2680](main.py#L2680) and the example payload at [MCP.md:445-448](MCP.md#L445-L448).
- **No prompt change.** No resolver change. No closed-vocab change. No cache invalidation. No SQL-generation risk.
- **Optional follow-up**: add `get_technical(id)` MCP tool for symmetry. Implementation: a `/technicals/{id}` route that returns `DESCRIPTION`, `TECHNICAL_TYPE`, plus reverse listings of movies bearing that technical. Useful for "what other Technicolor films are there?" walks, but not required for the metadata collection itself.
- **Series side**: `/series/{id}` does **not** yet have a junction (`T_WC_T2S_SERIE_TECHNICAL` does not exist). Flag as out-of-scope; the metadata-collection pattern would mirror Proposal C once that junction is added.

---

## 6. Additional metadata candidates worth adding to `T_WC_T2S_TECHNICAL`

The user explicitly asked. Ranked by fit:

1. **`IS_3D` → `3d_movie` technical row** ([doc/sql/T2S-tables.sql:650](doc/sql/T2S-tables.sql#L650)). Direct analog of Proposal B. Same B.1 / B.2 tradeoff applies; same recommendation (keep the flag, add the technical row). High value, low risk.

2. **Frame rate / HFR (high frame rate)**. No flag exists today. Pure addition. Modern releases (48 fps, 60 fps, 120 fps) are increasingly distinctive metadata for cinephile audiences. Safe to add as `TECHNICAL_TYPE='frame_rate'` rows.

3. **Stereoscopic / VR formats**. Pure addition. Same rationale as HFR.

4. **Color spaces** (Rec. 709, Rec. 2020, DCI-P3). Relevant for 4K HDR releases and restorations. Pure addition; `TECHNICAL_TYPE='color_space'`.

5. **HDR formats** (Dolby Vision, HDR10, HDR10+, HLG). Pure addition; `TECHNICAL_TYPE='hdr_format'`.

What does **not** fit `T_WC_T2S_TECHNICAL`:

- **`IS_DOCUMENTARY` / `IS_SHORT_FILM`** ([doc/sql/T2S-tables.sql:658-659](doc/sql/T2S-tables.sql#L658-L659)). These are genre/format classifications, not technical attributes. They belong with the existing genre model or on `T_WC_T2S_MOVIE` itself. Documenting this consideration here means it won't be raised again next quarter.
- **Decade / runtime bucket / release-window** classifications. Derivable from `RELEASE_YEAR` and `RUNTIME` columns. Materializing them in a reference table provides no benefit.
- **Language / country**. Already in dedicated tables (`T_WC_T2S_MOVIE_SPOKEN_LANGUAGE`, `T_WC_T2S_MOVIE_PRODUCTION_COUNTRY`).
- **Genre**. Already in `T_WC_TMDB_GENRE` and `T_WC_T2S_MOVIE_GENRE`.

### 6.1 Cleanup opportunity surfaced during analysis

`T_WC_T2S_MOVIE` carries four denormalized text columns that duplicate data already in `T_WC_T2S_TECHNICAL`:

- `COLOR_TECHNOLOGY varchar(100)` ([doc/sql/T2S-tables.sql:651](doc/sql/T2S-tables.sql#L651))
- `FILM_TECHNOLOGY mediumtext` ([:652](doc/sql/T2S-tables.sql#L652))
- `FILM_FORMAT varchar(50)` ([:654](doc/sql/T2S-tables.sql#L654))
- `SOUND_SYSTEM mediumtext` ([:655](doc/sql/T2S-tables.sql#L655))
- `SOUND_TECHNOLOGY varchar(200)` ([:656](doc/sql/T2S-tables.sql#L656))

These hold free-text duplicates of what the junction already represents canonically. They are the strongest candidates for deletion in a future cleanup pass. Risk profile is identical to Option B.2: every column is in the SQL-generation schema dump ([data/text_to_sql.md](data/text_to_sql.md)) and almost certainly referenced in cached SQL. Flag as a deliberate follow-up, not part of this work.

---

## 7. Cross-cutting impacts

These apply across most of the options above:

- **Closed-vocab startup log** at [closed_vocab.py:257-258](closed_vocab.py#L257-L258) prints a per-entity count summary. Useful smoke check: after deploying Proposals B + new aspect-ratio rows, the `Technical_format` count should jump by exactly the number of inserted rows.
- **`data_watcher` hot-reload** at [closed_vocab.py:144](closed_vocab.py#L144). Alias JSON changes hot-reload at runtime. Schema changes (new DB rows) do not — they require a restart because canonicals are loaded only by `init()`.
- **Series side blind spot**. Proposals A and B operate only on movies. `T_WC_T2S_SERIE_TECHNICAL` does not exist; series cannot carry aspect ratio or color/B&W/silent metadata today. If technical metadata becomes a first-class concern, the series-side junction is the natural next step.
- **Backward compat with MCP consumers**. Any MCP client (web UI, third-party agents using `get_movie`) reading `ASPECT_RATIO`, `IS_COLOR`, `IS_BLACK_AND_WHITE`, `IS_SILENT` from the inline movie payload will break silently under Options A.1 and B.2. The recommended path (A.2 + B.1) keeps every existing field intact.
- **AGENTS.md** at [lines 44, 128, 298-300](AGENTS.md#L44) and **closed-vocab-entity-plan.md** at [lines 67-72, 204-206, 295](closed-vocab-entity-plan.md#L67-L72) both reference `Aspect_ratio` as a string-canonical lookup; both need updates if Proposal A.1 ships.

---

## 8. Recommendation

Ship the smallest change that unlocks the user's primary goal (the `/movies` metadata collection), then layer the rest only as data and need warrant.

1. **Now — Proposal C.** Add the `technicals` collection to `/movies/{id}`. Junction already exists; just expose it. Zero risk to entity extraction, SQL generation, resolution, cache. Immediate value.
2. **Next — Proposal B.1.** Insert color_movie / black_and_white_movie / silent_movie rows, backfill the junction, add aliases under `Technical_format`. Keep the boolean flags. No SQL-prompt change; no cache impact; the metadata collection automatically gains the new rows.
3. **Optional next — `IS_3D → 3d_movie`** following the same B.1 pattern.
4. **Later — Proposal A.2 (dual model)** *if and when* multi-aspect-ratio data becomes available for ingestion. Additive only. Do not document the junction path to the SQL prompt; the column stays the documented filter path.
5. **Eventual cleanup** — retire the denormalized `COLOR_TECHNOLOGY / FILM_TECHNOLOGY / FILM_FORMAT / SOUND_SYSTEM / SOUND_TECHNOLOGY` text columns on `T_WC_T2S_MOVIE`. Same risk profile as B.2; defer until SQL-cache churn is acceptable.

A.1 (full aspect-ratio migration to ID-based resolution) is deliberately **not** in the recommended sequence. Its conceptual cleanliness is real, but the cost — 54 alias retargets, SQL-prompt rewrite, cache flush, evaluation re-runs, AGENTS.md updates — does not pay for itself unless and until the dual model from A.2 becomes visibly redundant.

---

## 9. Phased migration sequence (per-PR breakdown)

| PR | Scope | Files touched | Risk |
|---|---|---|---|
| PR-1 | Add `technicals` collection to `/movies/{id}` | [main.py:1620-1742](main.py#L1620-L1742), [MCP.md:445-448](MCP.md#L445-L448), [main.py:2680](main.py#L2680) | None — purely additive |
| PR-2 | Insert color_movie / black_and_white_movie / silent_movie rows; backfill junction from flags; add `Technical_format` aliases | DB migration + [data/closed_vocabularies.json](data/closed_vocabularies.json); no prompt change, no code change | Low — new rows appear in metadata collection only |
| PR-3 (optional) | Same pattern for `IS_3D → 3d_movie` | DB migration + [data/closed_vocabularies.json](data/closed_vocabularies.json) | Low |
| PR-4 (deferred) | Aspect-ratio rows + junction backfill (A.2 dual model) | DB migration + [main.py](main.py) (extend `/movies` collection); no prompt change; no resolver change | Low if SQL prompt is *not* updated to mention the junction |
| PR-5 (speculative) | Add `get_technical(id)` MCP tool and `/technicals/{id}` route | New route in [main.py](main.py), new MCP docstring | Low — net-new surface area |

Future cleanup pass (B.2-style migration of flags, A.1-style migration of aspect ratio, retirement of denormalized text columns) is out of scope for this analysis and should each warrant its own design pass when prioritized.

---

## 10. Verification plan

For each PR:

- **Closed-vocab init smoke**: restart the service; confirm the per-entity count summary printed at [closed_vocab.py:257-258](closed_vocab.py#L257-L258) reflects the expected `Technical_format` delta (e.g., `+3` after PR-2).
- **`/movies/{id}` manual probe**: pick a movie ID known to carry rich technical metadata (a Technicolor 70mm Dolby Stereo release like *Lawrence of Arabia* or *2001*); verify the `technicals` array is populated with the correct rows and `technical_type` values.
- **MCP smoke**: call `mcp__claude_ai_text2sql__get_movie` for the same ID; verify the new field surfaces in the MCP response.
- **Eval baseline**: `python eval/text2sql-eval.py` against the full evaluation set; diff CSV output against the previous baseline. **Expectation under the recommended path: zero text2sql regressions** because no prompt is changed.
- **Targeted NL queries** (manual or scripted):
  - "color films of 1939" → SQL should still use `IS_COLOR = 1` (flag path, not junction).
  - "silent films of the 1920s" → `IS_SILENT = 1`.
  - "black and white movies with Bogart" → `IS_BLACK_AND_WHITE = 1`.
  - "Technicolor films" → `T_WC_T2S_MOVIE_TECHNICAL` JOIN with the technicolor ID (junction path, unchanged).
  - Each query's `/movies/{id}` follow-up should now show the relevant rows in the `technicals` collection.

---

## 11. Open questions for follow-up

These are intentionally left open in this analysis — they are decisions, not impacts:

1. **`DESCRIPTION` convention for aspect-ratio rows.** Dot-decimal (`"1.85"`) is recommended for alignment with the rest of `T_WC_T2S_TECHNICAL`. Alternative: named convention (`"Widescreen 1.85"`). The choice affects aliases and SQL JOIN output ergonomics.
2. **`TECHNICAL_TYPE` for color / B&W / silent rows.** Recommended: `medium_format`. Alternatives: `movie_classification`, `presentation_format`. Pick one before PR-2.
3. **Dual exposure on `/movies/{id}`** (Option B.1): keep `IS_COLOR / IS_BLACK_AND_WHITE / IS_SILENT` flags inline *and* in the technicals array, or only in the array? Recommended: keep both for backward compat.
4. **`get_technical(id)` MCP tool** symmetry — ship as part of PR-1, or defer? Recommended: defer; not needed for the metadata collection.
5. **Series side** (`T_WC_T2S_SERIE_TECHNICAL`): in scope for this initiative, or a separate workstream? Recommended: separate workstream.
