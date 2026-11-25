# Why MariaDB and not PostgreSQL, and why fuzzy matching lives in Python

A question that comes up: "why MariaDB, when PostgreSQL has fuzzy string matching built in?" And its corollary: is the BK-tree plus RapidFuzz layer of [`rapidfuzz_query.py`](../rapidfuzz_query.py) reinventing something a database already does? This page records the answer, checked on 2026-11-25 against MariaDB 12.3 LTS.

Short version: the first reason is historical, and PostgreSQL would not remove the Python layer anyway. Its native tools cover the candidate search, not the scoring, and they handle short names (Chinese, Japanese and Korean names in particular) worse than the BK-tree does.

## 1. What the Python layer does

Entity resolution matches a name from the question ("Chow Yun-fat", "周润发", "Kurosawa") against the alias tables, in two stages:

1. **Candidate search.** FULLTEXT and prefix pools on the `*_NORM` / `*_KEY` columns, plus an in-memory **BK-tree** keyed on Levenshtein distance. The BK-tree returns every name within `k` edits of the query, wherever the typo sits, including in the first characters where prefix pools fail. `k` adapts to length: 1 up to 6 characters, 2 up to 14, 3 beyond ([RAPIDFUZZ.md](RAPIDFUZZ.md), section 2.bis).
2. **Scoring and rejection.** RapidFuzz scores the candidates (`token_set_ratio` and the other scorers configured per entity), and each resolver applies a threshold measured on a bench, never chosen ([entity-resolution-thresholds.md](entity-resolution-thresholds.md)).

Names are normalized without transliteration: `normalize_name()` keeps letters, combining marks and digits of every script, so a Chinese name stays in Han characters, a Hindi name in Devanagari.

## 2. MariaDB 12.3: nothing native

MariaDB 12.3 (LTS, current release in November 2026) has no Levenshtein function, no edit-distance index and no fuzzy search on InnoDB tables. The 12.3 release notes list an XML data type, Oracle compatibility functions (`TO_DATE`, `TO_NUMBER`, `TRUNC`), join order hints and vector search optimizations; nothing on string similarity.

The only near miss is **Mroonga**, a storage engine shipped with MariaDB and built on Groonga, which has a fuzzy search. Three things rule it out:

- Groonga flags its fuzzy search as **experimental**.
- It only works on a Mroonga table, so the name columns would have to be duplicated into a separate table and kept in sync at every load.
- It is reached through the `mroonga_command()` UDF, which **bypasses MariaDB privilege control**: incompatible with the restricted accounts the stack relies on.

`SOUNDEX` (phonetic, English-centric) and the `VECTOR` index (approximate semantic neighbours, not edit distance) answer other questions.

## 3. PostgreSQL: the candidate search, not the whole job

PostgreSQL does ship what MariaDB lacks, as official extensions bundled with the server:

| extension | what it brings | Python equivalent here |
|---|---|---|
| `pg_trgm` | trigram similarity (`similarity`, `word_similarity`, operator `%`), **GIN and GiST indexes** on trigrams, nearest-neighbour ordering (`ORDER BY name <-> 'query' LIMIT 20`, GiST) | FULLTEXT pools + BK-tree |
| `fuzzystrmatch` | `levenshtein()`, `levenshtein_less_equal(a, b, k)` (stops once the distance exceeds `k`), `soundex`, `metaphone`, `daitch_mokotoff` | `rapidfuzz.distance.Levenshtein` |
| `unaccent` | accent stripping | the accent normalizers |

With them, one indexed SQL query would do roughly what the BK-tree and the first RapidFuzz filter do today. Three things it would not do.

### 3.1 Short names, and CJK names first of all

Trigram similarity collapses on short strings, because one wrong character destroys most of the few trigrams a short name has. Chinese names are the extreme case: two to four characters, written without spaces, so the whole name is a single word.

Worked example, `周润发` (Chow Yun-fat, 3 characters) typed with one wrong character as `周闰发`. `pg_trgm` pads each word with two spaces before and one after, which gives 4 trigrams per name; the two names share only one of them (`"  周"`). Similarity = shared / union = 1 / 7 ≈ 0.14, far below the default threshold of 0.3: the right person is not even a candidate. The BK-tree, at `k = 1` for a 3-character query, finds it at distance 1, and RapidFuzz's plain ratio still scores it 67.

Lowering the trigram threshold to catch it would flood every query with noise. The same holds for short Latin names ("Ozu", "Tati", "Lynch") and for Korean and Japanese names written in their own scripts.

A second, quieter trap: `pg_trgm` keeps only the characters the database locale (`LC_CTYPE`) classifies as alphanumeric. Under a `C` locale, non-ASCII letters can be dropped entirely, so multilingual matching depends on choosing the locale right at database creation.

### 3.2 The scoring stage stays in Python

`similarity()` is one fixed measure. The resolvers rely on RapidFuzz's family of scorers (token-sorted, token-set, partial ratios) and on thresholds measured per entity against a bench. None of that has a PostgreSQL equivalent; the second stage would stay in Python whatever the engine.

### 3.3 The migration cost

The whole stack is written for the MariaDB dialect: crawlers and `LOAD DATA LOCAL INFILE` loaders, generated columns, the SQL that the text2sql models generate from MariaDB schema prompts, the evaluation bench that scores that SQL. Changing engines would mean rewriting all of it and re-measuring every threshold, to replace one in-memory index that costs neither noticeable memory nor startup time.

## 4. The other families

- **Elasticsearch / OpenSearch**: `fuzzy` queries built on Levenshtein automata, very fast, but capped at an edit distance of 2, and one more service to run and feed.
- **Meilisearch / Typesense**: typo tolerance out of the box, with limited control over how it ranks, and one more service.
- **SQLite** (`spellfix1`), **ClickHouse** (`ngramDistance`): exist, irrelevant here.

## 5. Conclusion

The BK-tree plus RapidFuzz layer is not a reinvented wheel. It is a Python rebuild of what `pg_trgm` and `fuzzystrmatch` give PostgreSQL, with a better handling of short and non-Latin names, and a scoring stage no database offers. MariaDB stays for historical reasons and because nothing in PostgreSQL would retire this layer. If the stack ever changed engines for other reasons, `pg_trgm` would be a good occasion to simplify the candidate search; it is not a reason to change engines.

## Sources

- [MariaDB 12.3 Changes & Improvements](https://mariadb.com/docs/release-notes/community-server/12.3/mariadb-12.3-changes-and-improvements)
- [MariaDB Server 12.3 LTS Released](https://mariadb.org/mariadb-server-12-3-lts-released/)
- [About Mroonga](https://mariadb.com/docs/server/server-usage/storage-engines/mroonga/about-mroonga) and [`mroonga_command`](https://mariadb.com/docs/server-1/server-usage/storage-engines/mroonga/mroonga-user-defined-functions/mroonga_command)
- [Groonga fuzzy search, experimental since 13.0.8 (issue on redmine_full_text_search)](https://www.github.com/clear-code/redmine_full_text_search/issues/117)
- PostgreSQL documentation: [`pg_trgm`](https://www.postgresql.org/docs/current/pgtrgm.html), [`fuzzystrmatch`](https://www.postgresql.org/docs/current/fuzzystrmatch.html), [`unaccent`](https://www.postgresql.org/docs/current/unaccent.html)
