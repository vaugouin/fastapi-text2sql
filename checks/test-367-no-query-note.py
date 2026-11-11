"""Offline check of the FASTAPI-TEXT2SQL-367 second call (no API, no database).

When the complex model answers `authoritative_empty` and the first pass wrote no SQL, main.py asks
it once more with ``text2sql.COMPLEX_NO_QUERY_RAN_NOTE``. This checks the text2sql side: the note
reaches the user prompt, after the cache boundary, and a call without a note sends the template
unchanged (so the -221 path and the provider prompt cache are untouched).

    uv run --no-project --with-requirements requirements.txt checks/test-367-no-query-note.py
"""

import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import text2sql as t2s  # noqa: E402

captured = []


def fake_call(**kwargs):
    captured.append(kwargs["user_prompt"])
    return json.dumps({"question": "Serie The Diplomat (2023)", "items": [], "error": "",
                       "justification": "", "authoritative_empty": False})


t2s._call_chat_llm = fake_call
QUESTION = "In which 2023 series does Keri Russell play a career diplomat?"
failures = 0


def check(label, ok):
    global failures
    print(("PASS " if ok else "FAIL ") + label)
    failures += 0 if ok else 1


t2s.f_resolve_complex_question_retry_payload(QUESTION, "default")
plain = captured[-1]
check("no note: the note is absent", t2s.COMPLEX_NO_QUERY_RAN_NOTE not in plain)

payload = t2s.f_resolve_complex_question_retry_payload(QUESTION, "default", t2s.COMPLEX_NO_QUERY_RAN_NOTE)
noted = captured[-1]
check("note: present in the user prompt", t2s.COMPLEX_NO_QUERY_RAN_NOTE in noted)
check("note: placed after the cache boundary",
      "<!--CACHE_BOUNDARY-->" not in noted
      or noted.index("<!--CACHE_BOUNDARY-->") < noted.index(t2s.COMPLEX_NO_QUERY_RAN_NOTE))
check("note: the prompt before it is the plain prompt", noted.startswith(plain.rstrip()))
check("payload: rewrite kept, not authoritative_empty",
      payload["retry_question"] != "" and not payload["authoritative_empty"])

print("OK" if failures == 0 else f"{failures} FAILURE(S)")
sys.exit(1 if failures else 0)
