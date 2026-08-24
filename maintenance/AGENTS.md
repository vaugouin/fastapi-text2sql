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
- `eval-executions-retirer-1-1-17.sql` : retires the 1.1.17 execution rows so the
  evaluation suite actually re-runs. Not housekeeping: `text2sql-eval.py` skips
  any evaluation that already has a live execution row for the same version,
  models and language, so a "full re-run" over a populated version runs almost
  nothing. Read the trap section before choosing to keep recent rows.
- `serie-type-contre-serie-genre.sql` : read-only, decides a modelling question
  rather than cleaning anything. `Documentary`, `News`, `Reality` and `Talk` sit
  in BOTH the `Serie_type` and `Serie_genre` vocabularies, so one word maps to
  two placeholders and two columns with nothing to arbitrate. The agreed
  direction is to make the vocabularies disjoint, dropping those four from
  `Serie_type` and keeping `Miniseries`, which is a format no genre expresses.
  These queries confirm the two columns cover the same series before anything
  is routed from one to the other.
