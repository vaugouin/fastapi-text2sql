# maintenance/

## Role

One-shot **operational SQL** run by hand against the production MariaDB: cleanups,
migrations of stored data, and diagnostics that do not belong to any code path.

Not to be confused with two neighbours that also hold `.sql`:

- `doc/sql/*.sql` is **reference DDL**, a schema dump. Read-only unless the user
  explicitly asks for a schema-doc change.
- `eval/assertions-*.sql` writes to the **evaluation bank**
  (`T_WC_T2S_EVALUATION`). It shapes what the harness measures.

This folder writes to **operational** tables, `T_WC_T2S_CACHE` first among them.

A `.sql` may be accompanied by the output of its run, named `<file>-<YYYYMMDD>.txt`, as
`vision-recognition-cache-20260920.txt` is. That is what turns "applied" from a claim into
evidence, and it is what the inventory below dates. Keep such a file to the output of the
verification queries: it is read by someone deciding whether to trust the table, not by someone
replaying the migration.

## Conventions

- **Read-only sections first, writes last, numbered.** A file opens with counts
  and detail queries and only then offers the `UPDATE`. When two cleanups touch
  overlapping rows, the required order is stated in the section titles, not left
  to the reader.
- **Soft delete, never `DELETE`.** Every cache lookup already filters on
  `(DELETED IS NULL OR DELETED = 0)`, so `SET DELETED = 1` retires a row and one
  `UPDATE` brings it back. A destructive statement in this folder wants an
  explicit reason in the header.
- **A backup table before any write**, named `<TABLE>_<PURPOSE>_<YYYYMMDD>`. The undo
  statement goes in the file, not in a chat log. A backup is not free either: the nightly
  dump resolves its tables by `LIKE 'T_WC_T2S_%'`, so every backup is copied every night
  until it is dropped. Drop it once the cleanup is settled, write down what it held before
  it goes, and say next to the undo statement that the statement can no longer run.
- **The header carries the reasoning, not just the SQL.** These files are read
  months later by someone who no longer remembers why a row was suspect. State
  what the marker is and why it is exact.
- **Say what was not verified.** Nothing here is executed from a developer
  machine: the DB is not reachable outside the VPS. Files are validated for
  syntax only, and the header must say so rather than imply a passing run.
- **Backslashes are doubled in string literals.** MariaDB treats backslash as an
  escape inside literals, so a regex written `\\.` in the file lands as `\.` in
  the column. Same convention as `eval/assertions-year-bounds.sql`.
- **Text comparison on questions is forced to `utf8mb4_bin`.** The table
  collation is `utf8mb4_unicode_ci` and would call two questions equal when they
  differ only by case or accent. Acceptable to count, not to delete.

## The API account is read-only, except on the cache tables

`moviematchro`, the account the API connects with, holds **read rights only**, deliberately, so
that a defect in the application cannot damage the database. Write rights are granted **table by
table**, and the only tables that carry them are the **cache** tables, which are the only ones
the API is supposed to fill.

**So a `CREATE TABLE` in this folder is not finished when the table exists.** The creation runs
as an administrator, through `runsqlvaugouindb.sh` of the `tools` repository, and creating a
table grants nothing to anybody. A new cache table is therefore born readable and not writable,
which is the most misleading state possible: every `SELECT` works, every `INSERT` answers
**error 1142**, and an application that treats a cache failure as non-fatal, as it should,
carries on as if the cache were merely empty.

Measured on 2026-09-20, and it is the reason this section exists.
`T_WC_T2S_VISION_CACHE` was created at 12:53 and granted at 15:4x. In between, eight vision
requests each paid about 4 cents for an identification they could not store, four of them on a
photo already read minutes earlier, and nothing in the JSON logs said so: the failure reached
only the container's stdout. The application code now reports the reason in its response
messages, and this folder now ends every cache-table creation with its grant.

```sql
GRANT SELECT, INSERT, UPDATE ON vaugouindb.<TABLE> TO 'moviematchro'@'%';
FLUSH PRIVILEGES;
```

`DELETE` is deliberately absent: the soft delete of this folder is an `UPDATE` on `DELETED`,
run by an administrator, never by the API. A table that is **not** a cache gets no grant at all,
which is the rule rather than an omission.

## Key facts about the cache

- `T_WC_T2S_CACHE` holds two rows per request, the raw question and the
  anonymized one, distinguished only by `IS_ANONYMIZED`.
- **Every anonymized row carries `QUESTION_HASHED` of its ORIGINAL question**,
  not a hash of its own `QUESTION`. Joining on the hash alone pairs every
  request's two rows; the `QUESTION` text equality is what isolates the twins.
- A **twin pair**, two live rows sharing `QUESTION` and `QUESTION_HASHED`, is the
  exact after-the-fact signature of "entity extraction extracted nothing on this
  question". Both halves of that bug are fixed in code (see `main.py` around the
  anonymized write, and `sql_cache.py` `_ANONYMIZED_CLAUSE`), so **no new twin
  should form**. Section 1 of `cache-jumelles-et-empoisonnees.sql` returning rows
  again means that guard regressed.
- Lookups are keyed on `API_VERSION`, so a stale entry survives a prompt fix
  until either the version is bumped or the row is retired. Bumping
  `strapiversion` also flips Blue/Green via `_mcp_patch % 2`, so it is a
  deployment gesture, not only a cache one. Prefer retiring rows.

## The DATABASE() trap in the read sections

Every migration here opens with an INFORMATION_SCHEMA query filtered on
`TABLE_SCHEMA = DATABASE()`, and those queries are the convention: look before you write, and
read zero rows as "not there yet".

`DATABASE()` returns the **currently selected** database, which is right in a `mysql` session
where the schema was chosen, and wrong in phpMyAdmin whenever the session sits on
INFORMATION_SCHEMA (browsing its `COLUMNS` table is enough). The comparison then reads
`TABLE_SCHEMA = 'information_schema'`, matches nothing, and returns zero rows whatever the real
state of the table.

That is a silent false negative, and the worst kind: the query succeeds, and its answer means
"absent" by this folder's own convention. It happened on 2026-08-24, where
eval-executions-scores-correspondance.sql had already been applied and the check reported the
columns missing; the ALTER was replayed and only then failed, on columns that existed all along.

When a read section disagrees with what you expect, name the schema explicitly before believing
it: `WHERE TABLE_SCHEMA = 'vaugouindb'`. The ALTER statements themselves are unaffected, since
they address the table directly.

## Files

- `cache-jumelles-et-empoisonnees.sql` : twin rows, and the subset poisoned by an
  empty extraction that still returns zero rows to users. Read sections run
  2026-08-21, write sections deliberately not run: 0 poisoned entries, 1 twin
  pair that the payload guard correctly refuses. Its section 1 doubles as a
  regression check on the write-side guard, with a measured baseline of one pair.
- `cache-jumelle-charges-divergentes.sql` : read-only diagnostic on that single
  pair, whose two rows carry different payloads. Explained on 2026-08-21: entity
  extraction returned the key `Serie_genre1` **without** substituting the
  placeholder into the question, which the prompt forbids. So a twin forms for
  two reasons, not one: nothing extracted, or a key extracted without the
  question being anonymized. The second case leaves an unresolved
  `'{{Serie_genre1}}'` in the cached SQL, silently returning zero rows.
- `cache-retirer-tables-de-sauvegarde.sql` : drops the cache backup tables once
  their cleanups are settled, run 2026-08-24. The only destructive file here that
  removes tables rather than rows, so it carries its reasoning at length. Two
  lessons are recorded in it. Backups are not free, since
  `backupvaugouindb-t2s.sh` (repo tmdb-front) resolves its tables by
  `LIKE 'T_WC_T2S_%'` and copies every one of them into every nightly dump until
  dropped, which is also the only way back afterwards. And its section 5 stands as
  a warning: two of the three were removed before anyone wrote down what they
  held, so that knowledge now exists only inside dumps predating the drop.
- `eval-executions-scores-correspondance.sql` : adds `ENTITY_MATCH_WORST_DISTANCE` and
  `ENTITY_MATCH_WORST_FUZZ_RATIO`, the calibration material for FASTAPI-TEXT2SQL-206. Twelve of
  the fourteen resolvers carry no rejection threshold, so an embeddings search accepts its
  nearest neighbour however far it sits, and nothing recorded how far because the code only
  measured when a threshold existed. Read its header before using the two columns: they hold the
  WEAKEST accepted match of a request, not an average, because a threshold cuts the weakest link;
  and the two run in opposite directions, distance being a dissimilarity and ratio a similarity.
- `eval-executions-nouveaux-indicateurs.sql` : adds five indicator columns to
  `T_WC_T2S_EVALUATION_EXECUTION`, run 2026-08-23 (FASTAPI-TEXT2SQL-203). Follows
  the standing rule that every indicator must reach both the JSON response and the
  database, since campaigns are extracted from the database, not from the responses.
- `eval-executions-chronometre-complexe.sql` : adds
  `COMPLEX_QUESTION_PROCESSING_TIME`, run 2026-08-23 (FASTAPI-TEXT2SQL-204). Kept
  separate from the file above rather than appended to it, because that one had
  already run and replaying it would fail on existing columns. Each migration stays
  replayable on its own. Read its header before comparing durations across
  versions: on a retried row, rows written before the fix carry only the second
  pass and understate their cost.
- `eval-executions-cause-escalade.sql` : adds `FIRST_PASS_FAILURE_CODE` and `QUERY_MODE`,
  the escalation **cause** where FASTAPI-TEXT2SQL-257 had recorded only its existence
  (FASTAPI-TEXT2SQL-271). **Section 2 run 2026-09-18**, so the two columns exist in production;
  section 3, the optional backfill of earlier campaigns, is still open. Two things in its header
  are worth reading before using the columns. The column alone would have been useless: `main.py` filed
  `descriptive_identification` and Text2SQL's own `requires_complex_resolution` under the same
  value until the same commit, so rows written earlier carry the mixed label and its section 3
  offers to split them from `first_pass_failure_reason`. And `QUERY_MODE` must be read from
  `first_pass_entity_extraction`, not from `entity_extraction`, which on a retried row describes
  the rewritten question and reads `named_entity_query` in 27 of 30 measured cases.
- `eval-mode-de-resolution.sql` : adds `RESOLUTION_MODE` to `T_WC_T2S_EVALUATION` and four
  columns to `T_WC_T2S_EVALUATION_EXECUTION`, so that a campaign can say which path was
  SUPPOSED to resolve a question and not only which one did (FASTAPI-TEXT2SQL-257). Written
  2026-09-14, **section 2 run 2026-09-20 at 13:24:33**, output beside it in
  `eval-mode-de-resolution-20260920.txt`: the five columns exist. Two of them,
  `RESOLUTION_MODE` on the bank and `COMPLEX_MODEL_USED` on the executions, answered
  `ERROR 1060 Duplicate column name`, so an earlier run had added them and nobody wrote it down;
  the run used `--force`, so what followed each error still went through. **Replaying this file
  now yields five such errors**, harmless with `--force` and a full stop without it. Its section
  1 also no longer reproduces the figure its own comment announces: 26 escalations seen by the
  JSON against 15 by the time column on 1704 rows, where 2026-09-14 recorded 46 against 34, so
  the row population moved. Three more things in its header are worth reading first. The verdict deliberately stays OUT of
  `ASSERTIONS_TOTAL_SCORE`, which is the one measure that makes a campaign comparable to the
  previous one, and lives in `RESOLUTION_MODE_RESPECTED` instead. The mode is copied onto the
  execution as well as declared on the evaluation, so re-qualifying a question later does not
  rewrite the meaning of campaigns already played. And two of the five columns exist only
  because the recording was a quarter short: measured on campaign `001.001.018`,
  `complex_model_used` is true on 46 executions where `COMPLEX_QUESTION_PROCESSING_TIME` sees
  only 34, the missing twelve being the direct scalar answer, which banks into its own timer.
- `eval-executions-retirer-1-1-17.sql` : retires the 1.1.17 execution rows so the
  evaluation suite actually re-runs. Not housekeeping: `text2sql-eval.py` skips
  any evaluation that already has a live execution row for the same version,
  models and language, so a "full re-run" over a populated version runs almost
  nothing. Read the trap section before choosing to keep recent rows.
- `vision-recognition-cache.sql` : creates `T_WC_T2S_VISION_CACHE`, the recognition cache of the
  picture-based search, **run 2026-09-20 at 12:53:25** (FASTAPI-TEXT2SQL-114). Its output is kept
  beside it in `vision-recognition-cache-20260920.txt` and matches the DDL column for column and
  index for index; the engine and the collation are the one thing it does not show, the query
  that reads them being in section 1, which runs before the creation. Two things in its header
  are worth reading before using the table. The key is the MD5 of the image bytes, which the
  deposit filename already carries, so the same photo re-deposited hits the same row under a new
  name. And only the question-independent half of an identification is stored, `about_image` and
  `image_answer` being dropped by `vision_cache.identification_payload`: putting a
  question-dependent field back in there would make the cache serve yesterday's answer to today's
  question. It is also the only file here whose `DROP` asks for no backup, and the header says
  why: the table is entirely rebuildable by repaying the vision calls.
- `serie-type-contre-serie-genre.sql` : read-only, decides a modelling question
  rather than cleaning anything. `Documentary`, `News`, `Reality` and `Talk` sit
  in BOTH the `Serie_type` and `Serie_genre` vocabularies, so one word maps to
  two placeholders and two columns with nothing to arbitrate. The agreed
  direction is to make the vocabularies disjoint, dropping those four from
  `Serie_type` and keeping `Miniseries`, which is a format no genre expresses.
  These queries confirm the two columns cover the same series before anything
  is routed from one to the other.
