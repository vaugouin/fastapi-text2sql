"""Offline regression for the generated SQL execution boundary (-113).

Run from the repository root: uv run checks/verif-113.py
"""

import ast
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from generated_sql_guard import (  # noqa: E402
    GeneratedSqlRejected,
    READ_MODEL_TABLES,
    validate_generated_sql,
)


ALLOWED = [
    "SELECT 1",
    "SELECT 4 AS ANSWER FROM DUAL",
    "SELECT COUNT(*) FROM T_WC_T2S_MOVIE",
    "SELECT YEAR(CURDATE()) - DAT_RELEASE AS AGE FROM T_WC_T2S_MOVIE LIMIT 10",
    "SELECT 'DROP; DELETE' AS WORDS FROM T_WC_T2S_MOVIE",
    "SELECT ID_MOVIE FROM T_WC_T2S_MOVIE UNION SELECT ID_MOVIE FROM T_WC_T2S_MOVIE_SIMILAR",
    "WITH x AS (SELECT ID_MOVIE FROM T_WC_T2S_MOVIE) SELECT * FROM x",
    "WITH RECURSIVE x AS (SELECT ID_MOVIE FROM T_WC_T2S_MOVIE UNION ALL SELECT ID_MOVIE FROM x) SELECT * FROM x",
    "SELECT * FROM (SELECT ID_MOVIE FROM T_WC_T2S_MOVIE) AS x",
    "SELECT CASE WHEN ID_MOVIE > 0 AND EXISTS (SELECT 1 FROM T_WC_T2S_MOVIE) OR ID_MOVIE = 0 THEN CAST(ID_MOVIE AS CHAR) ELSE 'none' END FROM T_WC_T2S_MOVIE",
]

REJECTED = {
    "": "empty_sql",
    "/* comment only */": "not_one_select",
    "SELECT 1 /*!50000 INTO OUTFILE '/tmp/x' */": "sql_comment",
    "SELECT FROM": "table_not_allowed",
    "SELECT 1; SELECT 2": "not_one_select",
    "DELETE FROM T_WC_T2S_CACHE": "not_one_select",
    "UPDATE T_WC_T2S_CACHE SET DELETED = 1": "not_one_select",
    "INSERT INTO T_WC_T2S_CACHE VALUES (1)": "not_one_select",
    "CREATE TABLE x (id INT)": "not_one_select",
    "CALL dangerous()": "not_one_select",
    "SET @x = 1": "not_one_select",
    "SELECT * FROM T_WC_T2S_CACHE": "table_not_allowed",
    "SELECT * FROM T_WC_T2S_FEEDBACK": "table_not_allowed",
    "SELECT * FROM information_schema.tables": "qualified_table",
    "SELECT * FROM other_db.T_WC_T2S_MOVIE": "qualified_table",
    "SELECT * FROM T_WC_T2S_MOVIE FOR UPDATE": "prohibited_construct",
    "SELECT * FROM T_WC_T2S_MOVIE LOCK IN SHARE MODE": "prohibited_construct",
    "SELECT @x": "prohibited_construct",
    "SELECT @@version": "prohibited_construct",
    "SELECT LOAD_FILE('/etc/passwd')": "prohibited_function",
    "SELECT SLEEP(1)": "prohibited_function",
    "SELECT BENCHMARK(1000, 1)": "prohibited_function",
    "SELECT GET_LOCK('x', 1)": "prohibited_function",
    "SELECT RELEASE_LOCK('x')": "prohibited_function",
    "SELECT 1 INTO OUTFILE '/tmp/x'": "prohibited_construct",
    "SELECT 1 INTO DUMPFILE '/tmp/x'": "prohibited_construct",
}


def check_validator():
    assert len(READ_MODEL_TABLES) == 65
    prompt_tables = set(re.findall(r"\bT_WC_T2S_[A-Z0-9_]+\b", (ROOT / "data" / "text_to_sql.md").read_text(encoding="utf-8")))
    assert READ_MODEL_TABLES == prompt_tables, (sorted(READ_MODEL_TABLES - prompt_tables), sorted(prompt_tables - READ_MODEL_TABLES))
    assert "T_WC_T2S_CACHE" not in READ_MODEL_TABLES
    for query in ALLOWED:
        validate_generated_sql(query)
    for query, reason in REJECTED.items():
        try:
            validate_generated_sql(query)
        except GeneratedSqlRejected as exc:
            assert str(exc) == reason, (query, str(exc), reason)
            if len(query) > 20:
                assert query not in str(exc)
        else:
            raise AssertionError(f"Unsafe SQL passed: {query}")


def check_central_helper():
    """Exercise the real helper without importing the API or opening a DB."""
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_run_generated_sql")
    module = ast.Module(body=[function], type_ignores=[])
    import pymysql
    namespace = {
        "validate_generated_sql": validate_generated_sql,
        "SQL_MAX_STATEMENT_TIME": 60,
        "_MARIADB_STATEMENT_TIMEOUT": 1969,
        "SqlTimeout": type("SqlTimeout", (Exception,), {}),
        "pymysql": pymysql,
        "os": os,
        "_TimedDictCursor": object,
    }
    exec(compile(module, str(ROOT / "main.py"), "exec"), namespace)
    run = namespace["_run_generated_sql"]

    class Cursor:
        def __init__(self):
            self.commands = []
            self.fail_query = False

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute(self, sql):
            self.commands.append(sql)
            if self.fail_query and sql.startswith("SET STATEMENT"):
                raise pymysql.err.ProgrammingError(1146, "synthetic query error")

        def fetchall(self):
            return [{"ok": 1}]

    class Connection:
        def __init__(self):
            self.cur = Cursor()
            self.rollbacks = 0
            self.closed = False

        def cursor(self):
            return self.cur

        def rollback(self):
            self.rollbacks += 1

        def close(self):
            self.closed = True

    db = Connection()
    for query in REJECTED:
        try:
            run(db, query)
        except GeneratedSqlRejected:
            pass
        else:
            raise AssertionError(f"Unsafe SQL reached cursor: {query}")
    assert db.cur.commands == []
    assert db.rollbacks == 0

    assert run(db, "SELECT 1") == [{"ok": 1}]
    assert db.cur.commands == [
        "START TRANSACTION READ ONLY",
        "SET STATEMENT max_statement_time=60 FOR SELECT 1",
    ]
    assert db.rollbacks == 1

    db.cur.fail_query = True
    try:
        run(db, "SELECT 1")
    except pymysql.err.ProgrammingError:
        pass
    else:
        raise AssertionError("Synthetic database error did not propagate")
    assert db.rollbacks == 2, "Read-only transaction remained open after SQL error"

    # When configured, generated SQL must use a distinct connection and close
    # it. The application connection remains available for cache writes.
    dedicated = Connection()
    real_connect = pymysql.connect
    settings = {"DB_GENERATED_USER": "query_ro", "DB_GENERATED_PASSWORD": "test_only",
                "DB_HOST": "localhost", "DB_PORT": "3306", "DB_NAME": "test"}
    try:
        pymysql.connect = lambda **kwargs: dedicated
        namespace["os"] = type("Environment", (), {"getenv": staticmethod(lambda key, default=None: settings.get(key, default))})
        assert run(db, "SELECT 1") == [{"ok": 1}]
    finally:
        pymysql.connect = real_connect
        namespace["os"] = os
    assert dedicated.cur.commands == ["START TRANSACTION READ ONLY",
                                      "SET STATEMENT max_statement_time=60 FOR SELECT 1"]
    assert dedicated.rollbacks == 1 and dedicated.closed
    assert not db.closed and db.rollbacks == 2


if __name__ == "__main__":
    check_validator()
    check_central_helper()
    print(f"FASTAPI-TEXT2SQL-113: {len(ALLOWED)} accepted, {len(REJECTED)} rejected, central cursor gate passed")
