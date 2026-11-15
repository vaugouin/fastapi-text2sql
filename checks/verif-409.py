"""Offline check of FASTAPI-TEXT2SQL-409: the OpenAI key comes with each request.

No API, no database, no OpenAI call. Run from the repository root:

    uv run --no-project checks/verif-409.py

Checks:
1. openai_key: a malformed or empty key stores nothing; require() raises without a key.
2. Two concurrent requests keep their own key, in the event loop and in the worker threads
   of asyncio.to_thread and create_task (the way main.py runs every LLM call).
3. The sources no longer read OPENAI_API_KEY nor set a global openai.api_key, every OpenAI
   client of text2sql.py and of the embedding function takes the request's key, and the
   endpoint answers 401 `openai_key_required` before the first model call.
"""

import asyncio
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import openai_key  # noqa: E402

failures = []


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


# 1. Shape and absence
KEY_A = "sk-proj-" + "a" * 40
KEY_B = "sk-proj-" + "b" * 40
openai_key.set_request_key("")
check(openai_key.current() == "", "empty key stores nothing")
openai_key.set_request_key("sk-short")
check(openai_key.current() == "", "too short a key stores nothing")
openai_key.set_request_key("sk-proj-" + "a" * 30 + "\r\nX-Evil: 1")
check(openai_key.current() == "", "a key with a line break stores nothing")
openai_key.set_request_key(object())
check(openai_key.current() == "", "a non-string (the Header() default) stores nothing")
try:
    openai_key.require()
    check(False, "require() raises without a key")
except openai_key.OpenAIKeyMissing:
    check(True, "require() raises without a key")
openai_key.set_request_key("  " + KEY_A + "  ")
check(openai_key.current() == KEY_A, "a well-formed key is stored, stripped")
check(len(openai_key.fingerprint()) == 8 and KEY_A not in openai_key.fingerprint(), "fingerprint is short and does not reveal the key")
openai_key.set_request_key("")


# 2. Isolation between concurrent requests
async def one_request(key, seen):
    openai_key.set_request_key(key)
    await asyncio.sleep(0.01)  # let the other request run and set its own key
    seen.append(("loop", key, openai_key.current()))
    seen.append(("to_thread", key, await asyncio.to_thread(openai_key.current)))
    task = asyncio.create_task(asyncio.to_thread(openai_key.require))
    await asyncio.sleep(0.01)
    seen.append(("create_task", key, await task))


async def two_requests():
    seen = []
    # gather wraps each coroutine in its own task, as the ASGI server does per request
    await asyncio.gather(one_request(KEY_A, seen), one_request(KEY_B, seen))
    return seen


for where, sent, got in asyncio.run(two_requests()):
    check(sent == got, f"concurrent requests keep their own key ({where}, {sent[-2:]})")
check(openai_key.current() == "", "the requests' keys did not leak into the outer context")


# 3. Sources
def read(name):
    with open(os.path.join(ROOT, name), encoding="utf-8") as f:
        return f.read()


main_src = read("main.py")
t2s_src = read("text2sql.py")
for name, src in (("main.py", main_src), ("text2sql.py", t2s_src)):
    check('getenv("OPENAI_API_KEY")' not in src, f"{name} does not read OPENAI_API_KEY")
check("openai.api_key" not in main_src, "main.py sets no global openai.api_key")
check("openai.embeddings.create" not in main_src, "the embedding function uses no global client")
check(main_src.count("openai.OpenAI(api_key=openai_key.require()).embeddings.create") == 2,
      "both embedding paths take the request's key")
openai_clients = re.findall(r"openai\.OpenAI\(\s*api_key=([a-z_.]+(?:\(\))?)", t2s_src)
check(sorted(openai_clients) == sorted(["openai_key.require()", "api_key", "openrouter_api_key"]),
      f"text2sql.py OpenAI clients: request key, vision's local key, OpenRouter ({openai_clients})")
check("api_key = openai_key.require()" in t2s_src and "api_key = openai_key.current()" in t2s_src,
      "vision and decisions read the request's key")
check("Header(default=None, alias=openai_key.HEADER_NAME)" in main_src, "the endpoint reads the X-OpenAI-Key header")
check(main_src.count("_refuse_without_openai_key(connection, \"") == 2, "two refusal points (vision, exact cache miss)")
check('"error_code": "openai_key_required"' in main_src, "the refusal carries error_code openai_key_required")
pos_refuse = main_src.find('_refuse_without_openai_key(connection, "answer this question")')
pos_extract = main_src.find("entity_extraction = await asyncio.to_thread(")
check(0 < pos_refuse < pos_extract, "the refusal comes before entity extraction")

print()
if failures:
    print(f"{len(failures)} check(s) failed")
    sys.exit(1)
print("All checks passed")
