#!/usr/bin/env python3
"""Offline checks for wikipedia_format=md and the mention lists of the detail endpoints.

    uv run checks/test-wikipedia-md-mentions.py

main.py cannot be imported without its environment (database, keys, ChromaDB), so the helpers
are lifted out of its source with ``ast`` and run alone, with a fake cursor:
- normalize_wikipedia_format, _wikipedia_md_absolute_links
- _fetch_wikipedia_content: text unchanged; md per section with references; English fallback
- _wikipedia_mention_collections: six registry entries that obey the registry contract
  (_TOTAL_COUNT, a unique tiebreaker in ORDER BY, no outer LIMIT, no semicolon)
- every one of the 16 Wikipedia-carrying endpoints and MCP tools takes wikipedia_format, passes
  it on, registers the mention lists and attaches them.
The SQL itself was run on the database by wikipedia-crawler/doc/sql/check-mention-queries.sql.
"""
import ast
import re
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = (ROOT / "main.py").read_text(encoding="utf-8")
TREE = ast.parse(SRC)

WANTED_FUNCS = {"normalize_wikipedia_format", "_wikipedia_md_absolute_links", "_fetch_wikipedia_content",
                "_wikipedia_mention_collections", "_attach_wikipedia_mentions"}
WANTED_NAMES = {"WIKIPEDIA_FORMATS", "_MD_LINK", "WIKIPEDIA_MENTION_COLLECTIONS", "_MENTION_KINDS"}

ns = {"re": re, "urllib": urllib, "DEFAULT_UI_LANGUAGE": "en",
      "normalize_ui_language": lambda v: "fr" if str(v or "").lower().startswith("fr") else "en"}
for node in TREE.body:
    if isinstance(node, ast.FunctionDef) and node.name in WANTED_FUNCS:
        exec(compile(ast.Module([node], []), "main.py", "exec"), ns)
    elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id in WANTED_NAMES for t in node.targets):
        exec(compile(ast.Module([node], []), "main.py", "exec"), ns)
missing = (WANTED_FUNCS | WANTED_NAMES) - set(ns)
assert not missing, f"not found in main.py: {missing}"

checks = 0
failures = 0


def check(label, actual, expected):
    global checks, failures
    checks += 1
    if actual != expected:
        failures += 1
        print(f"FAIL {label}\n     expected: {expected!r}\n     actual:   {actual!r}")


class FakeCursor:
    """Answers the section and reference queries from in-memory rows, keyed by language."""

    def __init__(self, sections, refs):
        self.sections, self.refs, self.rows, self.queries = sections, refs, [], []

    def execute(self, sql, params):
        self.queries.append(sql)
        qid, lang = params
        if "T_WC_WIKIPEDIA_PAGE_LANG_REFERENCE" in sql:
            self.rows = [r for r in self.refs if r["lang"] == lang]
        elif "CONTENT_MD" in sql:
            self.rows = [dict(r) for r in self.sections if r["lang"] == lang]
        else:
            self.rows = [{"title": r["TITLE"], "content": r["CONTENT"]} for r in self.sections if r["lang"] == lang]

    def fetchall(self):
        return self.rows


# -- format and links
fmt = ns["normalize_wikipedia_format"]
check("md", fmt("md"), "md")
check("markdown", fmt("Markdown"), "md")
check("default", fmt(None), "text")
check("unknown", fmt("html"), "text")

links = ns["_wikipedia_md_absolute_links"]
check("title link", links("by [Sergio Leone](Sergio_Leone).", "fr"), "by [Sergio Leone](https://fr.wikipedia.org/wiki/Sergio_Leone).")
check("parentheses and accents", links("*[Parasite](Parasite_(film,_2019))* [É](Émile_Zola)", "fr"),
      "*[Parasite](https://fr.wikipedia.org/wiki/Parasite_(film,_2019))* [É](https://fr.wikipedia.org/wiki/%C3%89mile_Zola)")
check("fragment", links("[Fox](20th_Century_Fox#Fox_Film_Corporation)", "en"),
      "[Fox](https://en.wikipedia.org/wiki/20th_Century_Fox#Fox_Film_Corporation)")
check("external kept", links("[site](https://www.oscars.org)", "en"), "[site](https://www.oscars.org)")
check("lone fragment", links("[see](#Plot)", "en"), "see")
check("table untouched", links("| a \\| b | [x](X) |", "en"), "| a \\| b | [x](https://en.wikipedia.org/wiki/X) |")

# -- content
SECTIONS = [
    {"lang": "en", "DISPLAY_ORDER": 1, "TITLE": "Intro", "CONTENT": "Plain intro", "CONTENT_MD": "**Bold** [Leone](Sergio_Leone)"},
    {"lang": "en", "DISPLAY_ORDER": 2, "TITLE": "Plot", "CONTENT": "Plain plot", "CONTENT_MD": None},
]
REFS = [{"lang": "en", "SECTION_DISPLAY_ORDER": 1, "LABEL": "[1]", "URL": "https://x.org", "TITLE": "T", "REFERENCE_TEXT": "Text T."}]
fetch = ns["_fetch_wikipedia_content"]
check("text unchanged", fetch(FakeCursor(SECTIONS, REFS), "Q1", "en"),
      [{"title": "Intro", "content": "Plain intro"}, {"title": "Plot", "content": "Plain plot"}])
check("md per section, references, fr falls back to en", fetch(FakeCursor(SECTIONS, REFS), "Q1", "fr", "md"), [
    {"title": "Intro", "content": "**Bold** [Leone](https://en.wikipedia.org/wiki/Sergio_Leone)", "format": "md",
     "references": [{"label": "[1]", "url": "https://x.org", "title": "T", "text": "Text T."}]},
    {"title": "Plot", "content": "Plain plot", "format": "text", "references": []},
])
check("no qid", fetch(FakeCursor(SECTIONS, REFS), None, "en", "md"), [])

# -- mention collections
coll = ns["_wikipedia_mention_collections"]
check("no qid, no collections", coll(None, "en"), {})
entries = coll("Q41483", "fr")
check("six lists", list(entries), list(ns["WIKIPEDIA_MENTION_COLLECTIONS"]))
KIND_ID = {"person": "ID_PERSON", "movie": "ID_MOVIE", "serie": "ID_SERIE"}
for name, (sql, params, kind) in entries.items():
    check(f"{name} params", params, ("Q41483", "fr", "Q41483"))
    check(f"{name} placeholders", sql.count("%s"), 3)
    check(f"{name} total", "COUNT(*) OVER() AS _TOTAL_COUNT" in sql, True)
    order = sql.rsplit("ORDER BY", 1)[1]
    check(f"{name} unique tiebreaker", KIND_ID[kind] in order, True)
    check(f"{name} no outer LIMIT", "LIMIT" in order, False)
    check(f"{name} no semicolon", ";" in sql, False)
    check(f"{name} _FR column", ("_FR" in sql) == (kind != "person"), True)
    check(f"{name} adult and deleted", "ADULT, 0) = 0" in sql and "DELETED, 0) = 0" in sql, True)
    check(f"{name} date links", ("IS_DATE = 0" in sql) == name.startswith("mentions_"), True)

result = {}
ns["_attach_wikipedia_mentions"](result, {"mentions_persons": [{"ID_PERSON": 1}]})
check("attach fills the six keys", sorted(result), sorted(ns["WIKIPEDIA_MENTION_COLLECTIONS"]))
check("attach keeps rows", result["mentions_persons"], [{"ID_PERSON": 1}])

# -- wiring of the 16 endpoints and MCP tools
ENDPOINTS = ["get_movie", "get_series", "get_season", "get_episode", "get_person", "get_collection", "get_topic",
             "get_list", "get_movement", "get_technical", "get_group", "get_death", "get_award", "get_nomination",
             "get_location", "get_source_work"]
funcs = {n.name: n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
for name in ENDPOINTS:
    body = ast.get_source_segment(SRC, funcs[name])
    check(f"{name} takes wikipedia_format", "wikipedia_format" in [a.arg for a in funcs[name].args.args], True)
    check(f"{name} passes it", "ui_language, wikipedia_format)" in body, True)
    check(f"{name} registers mentions", "_wikipedia_mention_collections(" in body, True)
    check(f"{name} attaches mentions", "_attach_wikipedia_mentions(result, data)" in body, True)
    tool = funcs["_mcp_" + name]
    tbody = ast.get_source_segment(SRC, tool)
    check(f"_mcp_{name} takes wikipedia_format", "wikipedia_format" in [a.arg for a in tool.args.args], True)
    check(f"_mcp_{name} forwards it", "wikipedia_format=wikipedia_format)" in tbody, True)
check("_mcp_get forwards md only", 'params["wikipedia_format"] = "md"' in ast.get_source_segment(SRC, funcs["_mcp_get"]), True)

print(f"{checks} checks, {failures} failures")
sys.exit(1 if failures else 0)
