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
- **A backup table before any write**, named `<TABLE>_<PURPOSE>_<YYYYMMDD>`, the
  convention already used by `T_WC_T2S_CACHE_PURGE_20260803`. The undo statement
  goes in the file, not in a chat log.
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

## Files

- `cache-jumelles-et-empoisonnees.sql` — twin rows, and the subset poisoned by an
  empty extraction that still returns zero rows to users. Read sections run
  2026-08-21, write sections deliberately not run: 0 poisoned entries, 1 twin
  pair that the payload guard correctly refuses. Its section 1 doubles as a
  regression check on the write-side guard, with a measured baseline of one pair.
- `cache-jumelle-charges-divergentes.sql` — read-only diagnostic on that single
  pair, whose two rows carry different payloads. Explained on 2026-08-21: entity
  extraction returned the key `Serie_genre1` **without** substituting the
  placeholder into the question, which the prompt forbids. So a twin forms for
  two reasons, not one: nothing extracted, or a key extracted without the
  question being anonymized. The second case leaves an unresolved
  `'{{Serie_genre1}}'` in the cached SQL, silently returning zero rows.
- `eval-executions-retirer-1-1-17.sql` — retires the 1.1.17 execution rows so the
  evaluation suite actually re-runs. Not housekeeping: `text2sql-eval.py` skips
  any evaluation that already has a live execution row for the same version,
  models and language, so a "full re-run" over a populated version runs almost
  nothing. Read the trap section before choosing to keep recent rows.
- `serie-type-contre-serie-genre.sql` — read-only, decides a modelling question
  rather than cleaning anything. `Documentary`, `News`, `Reality` and `Talk` sit
  in BOTH the `Serie_type` and `Serie_genre` vocabularies, so one word maps to
  two placeholders and two columns with nothing to arbitrate. The agreed
  direction is to make the vocabularies disjoint, dropping those four from
  `Serie_type` and keeping `Miniseries`, which is a format no genre expresses.
  These queries confirm the two columns cover the same series before anything
  is routed from one to the other.
