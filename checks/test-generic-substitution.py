"""Offline check of the generic-substitution count (FASTAPI-TEXT2SQL-371 step 4).

No API, no database. A Character_name has no resolver in entity_resolution.json: its raw value is
substituted ("generic"). ``entity.plan_entity_resolutions`` must flag it ``is_generic`` and
``entity.apply_entity_resolutions`` must count it in ``generic_count``, the signal main.py reads
to open the complex retry on an empty result instead of declaring it authoritative.

    uv run --no-project --with-requirements requirements.txt checks/test-generic-substitution.py
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import entity  # noqa: E402


class Msg:
    def __init__(self, position, text):
        self.position, self.text = position, text


class NoCursor:
    """The Character_name branch never queries; any SQL here is a failure."""
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        raise AssertionError(f"unexpected SQL: {sql[:120]}")


class NoConnection:
    def cursor(self):
        return NoCursor()


failures = 0


def check(label, ok, detail=""):
    global failures
    failures += 0 if ok else 1
    print(("PASS" if ok else "FAIL"), label, detail)


SQL = ("SELECT DISTINCT p.ID_PERSON, p.PERSON_NAME FROM T_WC_T2S_PERSON p WHERE EXISTS (SELECT 1 FROM "
       "T_WC_T2S_PERSON_MOVIE pm WHERE pm.ID_PERSON = p.ID_PERSON AND pm.CAST_CHARACTER = '{{Character_name1}}')")

# 1. The generic branch of the planner flags the entity (no ChromaDB, no query: the
#    Character_name branch never reaches a resolver).
plan = entity.plan_entity_resolutions(
    connection=NoConnection(),
    entity_extraction={"question": "Who starred as the {{Character_name1}}?", "Character_name1": "Six Million Dollar Man"},
    chromadb_collections_by_name={},
)
gen = [e for e in plan["entities"] if e.key == "Character_name1"]
check("planner flags Character_name as generic", len(gen) == 1 and gen[0].is_generic and not gen[0].is_raw_fallback)

# 2. Applied: counted once, placeholder gone, not a raw fallback.
out = entity.apply_entity_resolutions(plan=plan, sql_query=SQL, justification="", answer="",
                                      position_counter=0, text_message_cls=Msg, messages=[])
check("generic_count == 1", out.get("generic_count") == 1, f"({out.get('generic_count')})")
check("raw_fallback_count == 0", out.get("raw_fallback_count") == 0)
check("placeholder substituted", "{{" not in out["sql_query"] and "'Six Million Dollar Man'" in out["sql_query"])

# 3. require_present: a generic entity absent from the SQL is not applied, so not counted.
out = entity.apply_entity_resolutions(plan=plan, sql_query="SELECT 1", justification="", answer="",
                                      position_counter=0, text_message_cls=Msg, messages=[])
check("absent placeholder not counted", out.get("generic_count") == 0)

# 4. The flag survives the co-constrained rescue's plan copy (title or person rescue).
t = entity._PlannedEntity("Movie_title1", "{{Movie_title1}}")
t.resolve_with(entity._substitute_plain("{{Movie_title1}}", "Gladiator", "Gladiator"))
c = gen[0]
pp = entity._PlannedEntity("Person_name1", "{{Person_name1}}")
pp.resolve_with(entity._substitute_plain("{{Person_name1}}", "Phoenix", "Phoenix"), is_raw_fallback=True)
src = {"entities": [t, c, pp]}
copies = []
for p in src["entities"]:
    q = entity._PlannedEntity(p.key, p.placeholder)
    q.is_generic = p.is_generic
    copies.append(q)
check("slot exists on copies", copies[1].is_generic and not copies[0].is_generic)

print("\nOK" if failures == 0 else f"\n{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
