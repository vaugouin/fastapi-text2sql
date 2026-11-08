#!/usr/bin/env python3
"""Offline check of FASTAPI-TEXT2SQL-353: result_intent.py and the RESULT_INTENT cache column.

No API, no database, no LLM call. Covers the classifier reply parser (JSON, bare word,
garbage), the keyword rules on questions that are NOT in the evaluation bank (the bank's
labels judge the live classifier in a campaign, so they are kept out of the rules' test),
the focus mapping onto projected columns, the cache round trip, and the degradation of
sql_cache.py when RESULT_INTENT (then RESULT_ENTITY) is not migrated.

    uv run checks/test-result-intent.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

import result_intent as ri  # noqa: E402
import sql_cache  # noqa: E402

failures = 0


def check(label, got, want):
    global failures
    ok = got == want
    failures += 0 if ok else 1
    print(f"{'ok  ' if ok else 'FAIL'} {label}: {got!r}" + ("" if ok else f" (want {want!r})"))


ALLOWED = ["movie", "serie", "person", "collection"]

# 1. The classifier's reply.
check("json reply", ri.parse_classifier_reply(
    '{"entity": "movie", "task": "value", "focus": ["runtime"], "requested_view": ""}', ALLOWED),
    ("movie", {"task": "value", "focus": ["runtime"], "requested_view": "", "source": "llm"}))
check("json in a code fence, focus as a French word", ri.parse_classifier_reply(
    '```json\n{"entity": "serie", "task": "rank", "focus": ["saisons"], "requested_view": "table"}\n```', ALLOWED),
    ("serie", {"task": "rank", "focus": ["seasons"], "requested_view": "table", "source": "llm"}))
check("unknown entity abstains, intent kept", ri.parse_classifier_reply(
    '{"entity": "unknown", "task": "count", "focus": [], "requested_view": ""}', ALLOWED),
    ("", {"task": "count", "focus": [], "requested_view": "", "source": "llm"}))
check("lookup folds into list", ri.parse_classifier_reply('{"entity": "movie", "task": "lookup"}', ALLOWED)[1]["task"], "list")
check("task outside the set: entity only", ri.parse_classifier_reply('{"entity": "person", "task": "explain"}', ALLOWED), ("person", None))
check("bare word (one-word prompt)", ri.parse_classifier_reply("person", ALLOWED), ("person", None))
check("garbage", ri.parse_classifier_reply("I think {it is", ALLOWED), ("", None))
check("empty", ri.parse_classifier_reply("", ALLOWED), ("", None))

# 2. The keyword rules, on questions written for this test (none is in the bank).
RULES = [
    ("Which is longer, Heat or Casino?", "compare"),
    ("Lequel a coûté le plus, Waterworld ou Cutthroat Island ?", "compare"),
    ("Did Jim Jarmusch direct more films than Wes Anderson?", "compare"),
    ("How many westerns were released per decade?", "trend"),
    ("Durée moyenne des comédies chaque année depuis 1990", "trend"),
    ("The ten longest Spielberg films", "rank"),
    ("Quelles actrices ont joué dans le plus de films de Woody Allen ?", "rank"),
    ("How many films per country, from most to least?", "rank"),
    ("How many films won the Oscar for Best Animated Feature?", "count"),
    ("The Mission: Impossible films with the runtime of each", "value"),
    ("Les films Shrek avec leur budget, par ordre de sortie", "value"),
    ("Average budget of Ridley Scott films", "value"),
    ("How many seasons does The Office have?", "value"),
    ("The Bourne films in release order", "sequence"),
    ("Les films Mad Max du premier au plus récent", "sequence"),
    ("How many films did Spike Lee direct?", "count"),
    ("Combien de séries japonaises y a-t-il ?", "count"),
    ("What do Scorsese and De Niro have in common?", "relate"),
    ("Did Kubrick direct Spartacus?", "verdict"),
    ("Movies with Brad Pitt", "list"),
    ("Film avec l'identifiant IMDb tt0110912", "list"),
]
for question, want in RULES:
    check(f"rules {question!r}", ri.rules_task(question), want)
check("rules focus", ri.rules_focus("The Shrek films with the budget and the box office of each"), ["budget", "revenue"])
check("rules focus FR", ri.rules_focus("Les séries HBO avec le nombre de saisons"), ["seasons"])
check("rules view", ri.rules_requested_view("Les films de Kubrick sous forme de tableau"), "table")
check("rules on empty", ri.rules_intent("  "), None)

# 3. Focus onto projected columns: metrics and dates only, never a title.
COLUMNS = [
    {"name": "ID_MOVIE", "role": "id", "unit": None},
    {"name": "TITLE", "role": "label", "unit": None},
    {"name": "RUNTIME", "role": "metric", "unit": "minutes"},
    {"name": "BUDGET", "role": "metric", "unit": "usd"},
    {"name": "IMDB_RATING_WEIGHTED", "role": "metric", "unit": None},
    {"name": "RELEASE_YEAR", "role": "date", "unit": None},
]
check("focus columns runtime", ri.focus_columns(["runtime"], COLUMNS), ["RUNTIME"])
check("focus columns French word", ri.focus_columns(["durée", "budget"], COLUMNS), ["RUNTIME", "BUDGET"])
check("focus columns rating", ri.focus_columns(["rating"], COLUMNS), ["IMDB_RATING_WEIGHTED"])
check("focus not projected", ri.focus_columns(["seasons"], COLUMNS), [])

# 4. Precedence and the response object.
LLM = {"task": "rank", "focus": ["runtime"], "requested_view": "", "source": "llm"}
CACHED = {"task": "value", "focus": ["budget"], "requested_view": "", "source": "llm"}
check("llm first", ri.core_intent("Movies with Brad Pitt", LLM, CACHED)["task"], "rank")
check("cached next", ri.core_intent("Movies with Brad Pitt", None, CACHED)["task"], "value")
check("rules last", ri.core_intent("Movies with Brad Pitt", None, None), {"task": "list", "focus": [], "requested_view": "", "source": "rules"})
check("response object", ri.response_intent(LLM, COLUMNS),
      {"task": "rank", "focus": ["runtime"], "focus_columns": ["RUNTIME"], "requested_view": "", "source": "llm"})
check("response None", ri.response_intent(None, COLUMNS), None)
stored = ri.dumps_for_cache(LLM)
check("cache json", stored, '{"task":"rank","focus":["runtime"],"requested_view":"","source":"llm"}')
check("cache round trip", ri.loads_from_cache(stored), LLM)
check("cache empty", (ri.dumps_for_cache(None), ri.loads_from_cache(""), ri.loads_from_cache("{bad")), ("", None, None))
check("response intent survives the retry write", ri.dumps_for_cache(ri.response_intent(LLM, COLUMNS)), stored)


# 5. The shape rules take the intent as a prior (FASTAPI-TEXT2SQL-354).
import result_shape as rs  # noqa: E402


def movie_rows(values, key="RUNTIME"):
    return [{"index": i, "data": {"ID_MOVIE": 100 + i, "MOVIE_TITLE": f"Film {i}", "DAT_RELEASE": f"200{i}-01-01",
                                  "IMDB_RATING": 7.0 + i / 10, "IMDB_RATING_WEIGHTED": 7.0 + i / 10, "RUNTIME": 100 + i,
                                  key: v}} for i, v in enumerate(values)]


HP = movie_rows([152, 161, 141, 157, 138, 153, 146, 130])
HP_SQL = "SELECT ... FROM T_WC_T2S_MOVIE ... ORDER BY T_WC_T2S_MOVIE_COLLECTION.DISPLAY_ORDER ASC LIMIT 100"
none = rs.classify_result(HP_SQL, HP, "movie")
check("no intent: unchanged grid", none["representation"], "card-grid")
check("no intent: options", none["representation_options"], ["card-grid", "table"])
value = rs.classify_result(HP_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films with the runtime of each"))
check("value per item: value-cards", value["representation"], "value-cards")
check("value per item: focus on RUNTIME", [c["name"] for c in value["columns"] if c.get("focus")], ["RUNTIME"])
check("value per item: options", value["representation_options"], ["value-cards", "card-grid", "ranked-bars", "table"])
check("summary facts", {k: value["summary_facts"][k] for k in ("count", "total", "value_column", "unit", "order")},
      {"count": 8, "total": None, "value_column": "RUNTIME", "unit": "minutes", "order": "collection"})
check("summary top is the longest", (value["summary_facts"]["top"]["label"], value["summary_facts"]["top"]["value"],
                                     value["summary_facts"]["top"]["id"]), ("Film 1", 161, 101))
table = rs.classify_result(HP_SQL, HP, "movie", intent=ri.core_intent("The Harry Potter films with their runtime, as a table"))
check("requested view table", (table["representation"], table["representation_options"][0]), ("table", "table"))
RATED = "SELECT ... ORDER BY T_WC_T2S_MOVIE.IMDB_RATING_WEIGHTED DESC LIMIT 12"
check("rank by rating named: bars", rs.classify_result(RATED, HP, "movie", intent=ri.core_intent("The 12 highest-rated Studio Ghibli films"))["representation"], "ranked-bars")
check("rank with no quantity named: grid", rs.classify_result(RATED, HP, "movie", intent=ri.core_intent("The best romance movies"))["representation"], "card-grid")
short = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.RUNTIME ASC LIMIT 5", HP, "movie", intent=ri.core_intent("The five shortest Pixar films"))
check("ascending ranking: bars, top is the minimum", (short["representation"], short["summary_facts"]["top"]["value"], short["summary_facts"]["top"]["extreme"]), ("ranked-bars", 130, "min"))
PAIR = movie_rows([194, 162])
cmp_ = rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.RUNTIME DESC", PAIR, "movie", intent=ri.core_intent("Which is longer, Titanic (1997) or Avatar (2009)?"))
check("compare: value-cards", cmp_["representation"], "value-cards")
bud = movie_rows([150, 200], key="BUDGET")
check("value ordered on itself stays a ranking", rs.classify_result("SELECT ... ORDER BY T_WC_T2S_MOVIE.BUDGET DESC", bud, "movie",
      intent=ri.core_intent("The Toy Story movies with the budget of each"))["representation"], "ranked-bars")
one = rs.classify_result("SELECT SUM(RUNTIME) AS TOTAL_RUNTIME FROM T", [{"index": 0, "data": {"TOTAL_RUNTIME": 1178}}], "", intent=ri.core_intent("How long are all the Harry Potter films?"))
check("scalar: number card, options", (one["representation"], one["representation_options"], one["summary_facts"]["unit"]), ("number-card", ["number-card", "table"], "minutes"))
check("empty: no facts", rs.classify_result("SELECT 1", [], "movie", intent=ri.core_intent("x films"))["summary_facts"], None)


# 6. sql_cache degrades column by column, newest first.
class FakeCursor:
    def __init__(self, conn):
        self.conn = conn

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params):
        for column in self.conn.missing:
            if column in query:
                raise Exception(f"(1054, \"Unknown column '{column}' in 'field list'\")")
        self.conn.queries.append((query, params))

    def fetchone(self):
        return {"QUESTION": "q", "SQL_QUERY": "SELECT 1", "RESULT_ENTITY": "movie", "RESULT_INTENT": stored} if "RESULT_INTENT" not in self.conn.missing else {"QUESTION": "q", "SQL_QUERY": "SELECT 1", "RESULT_ENTITY": "movie"}


class FakeConnection:
    def __init__(self, missing):
        self.missing = set(missing)
        self.queries = []

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        pass

    def rollback(self):
        pass


def reset_flags():
    sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE = True
    sql_cache._RESULT_INTENT_COLUMN_AVAILABLE = True


WRITE = dict(question="q", question_hashed="h", sql_query="SELECT 1", sql_processed="SELECT 1", justification="",
             api_version="001.002.000", entity_extraction_processing_time=0.0, text2sql_processing_time=0.0,
             embeddings_time=0.0, query_time=0.0, total_processing_time=0.0, is_anonymized=False,
             result_entity="movie", result_intent_json=stored)

reset_flags()
conn = FakeConnection([])
sql_cache.write_sql_cache_entry(conn, **WRITE)
query, params = conn.queries[-1]
check("write both columns", ("RESULT_ENTITY, RESULT_INTENT)" in query, params[-2:]), (True, ("movie", stored)))
check("read both columns", sql_cache.search_sql_cache_by_question_hash(conn, "h", "001.002.000")["result_intent"], stored)

reset_flags()
conn = FakeConnection(["RESULT_INTENT"])
sql_cache.write_sql_cache_entry(conn, **WRITE)
query, params = conn.queries[-1]
check("intent column missing: write keeps RESULT_ENTITY", ("RESULT_INTENT" in query, params[-1]), (False, "movie"))
check("intent column missing: read", sql_cache.search_sql_cache_by_question_hash(conn, "h", "001.002.000")["result_entity"], "movie")
check("flags after", (sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE, sql_cache._RESULT_INTENT_COLUMN_AVAILABLE), (True, False))

reset_flags()
conn = FakeConnection(["RESULT_INTENT", "RESULT_ENTITY"])
sql_cache.write_sql_cache_entry(conn, **WRITE)
check("both missing: legacy write", "RESULT_ENTITY" in conn.queries[-1][0], False)
check("flags after both", (sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE, sql_cache._RESULT_INTENT_COLUMN_AVAILABLE), (False, False))
reset_flags()

print(f"\n{'all ok' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
