"""Offline check of FASTAPI-TEXT2SQL-410: OpenAI Ultrafast mode per task.

No API, no database, no OpenAI call: openai.OpenAI is replaced by a fake that records what
would have been sent. Run from the repository root:

    uv run --no-project --with-requirements requirements.txt checks/verif-410.py

Checks:
1. An Ultrafast task on gpt-6.1-sol or gpt-6-astra goes through responses.create with
   service_tier="ultrafast" and returns its output_text.
2. An Ultrafast task on a model without it (gpt-6-sol) gets Fast on chat.completions.
3. A refused Ultrafast call (400) falls back to Fast on chat.completions.
4. A task that did not ask for it is untouched (standard tier, chat.completions).
5. llm_costs prices an Ultrafast task at six times the standard rates.
"""

import os
import sys
from types import SimpleNamespace

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.chdir(ROOT)

import httpx  # noqa: E402
import openai  # noqa: E402

import openai_key  # noqa: E402
import text2sql as t2s  # noqa: E402
import llm_costs  # noqa: E402

failures = []
calls = []
refuse_ultrafast = {"on": False}


def check(cond, label):
    print(("ok   " if cond else "FAIL ") + label)
    if not cond:
        failures.append(label)


class _Responses:
    def create(self, **kwargs):
        calls.append(("responses", kwargs))
        if refuse_ultrafast["on"]:
            request = httpx.Request("POST", "https://api.openai.com/v1/responses")
            raise openai.BadRequestError("service_tier not supported", response=httpx.Response(400, request=request), body=None)
        return SimpleNamespace(output_text="ULTRA", service_tier=kwargs.get("service_tier"), usage=None)


class _Completions:
    def create(self, **kwargs):
        calls.append(("chat", kwargs))
        message = SimpleNamespace(content="CHAT")
        return SimpleNamespace(choices=[SimpleNamespace(message=message)], service_tier=kwargs.get("service_tier") or "default", usage=None)


class _FakeClient:
    def __init__(self, api_key=None, **_):
        self.responses = _Responses()
        self.chat = SimpleNamespace(completions=_Completions())

    def with_options(self, **_):
        return self


openai.OpenAI = _FakeClient
openai_key.set_request_key("sk-proj-" + "k" * 40)


def run(model, label):
    calls.clear()
    out = t2s._call_chat_llm(model=model, system_prompt="sys", user_prompt="user", temperature=0, cache_label=label)
    return out, list(calls)


t2s.set_fast_tasks([])
t2s.set_ultrafast_tasks(["complex_question", "text2sql"])

for model in ("gpt-6.1-sol", "gpt-6-astra"):
    out, seen = run(model, "complex_question")
    check(out == "ULTRA" and seen[0][0] == "responses" and seen[0][1].get("service_tier") == "ultrafast",
          f"Ultrafast task on {model}: responses.create with service_tier=ultrafast")
    check(len(seen) == 1, f"Ultrafast task on {model}: one call only")

out, seen = run("gpt-6-sol", "text2sql")
check(out == "CHAT" and seen[0][0] == "chat" and seen[0][1].get("service_tier") == "fast",
      "Ultrafast asked on gpt-6-sol: Fast on chat.completions")

refuse_ultrafast["on"] = True
out, seen = run("gpt-6.1-sol", "complex_question")
check([c[0] for c in seen] == ["responses", "chat"] and seen[1][1].get("service_tier") == "fast" and out == "CHAT",
      "refused Ultrafast: falls back to Fast on chat.completions")
refuse_ultrafast["on"] = False

out, seen = run("gpt-6.1-sol", "entity_extraction")
check(seen[0][0] == "chat" and "service_tier" not in seen[0][1], "task without Ultrafast: standard tier, chat.completions")

check(t2s.ultrafast_tasks_enabled() == ["complex_question", "text2sql"], "echo of the Ultrafast tasks, sorted")

# The picture task (vision_identification)
t2s.set_ultrafast_tasks(["vision_identification"])
calls.clear()
out = t2s._call_vision_llm(model="gpt-6-astra", system_prompt="sys", user_prompt="user", imagebytes=b"x", media_type="image/jpeg")
check(out == "ULTRA" and calls[0][0] == "responses" and calls[0][1].get("service_tier") == "ultrafast"
      and calls[0][1]["input"][1]["content"][1]["type"] == "input_image",
      "picture task in Ultrafast: responses.create with the image as input_image")
t2s.set_ultrafast_tasks([])
t2s.set_fast_tasks(["vision_identification"])
calls.clear()
out = t2s._call_vision_llm(model="gpt-6-astra", system_prompt="sys", user_prompt="user", imagebytes=b"x", media_type="image/jpeg")
check(out == "CHAT" and calls[0][0] == "chat" and calls[0][1].get("service_tier") == "fast", "picture task in Fast: chat.completions with service_tier=fast")
t2s.set_fast_tasks([])
calls.clear()
out = t2s._call_vision_llm(model="gpt-6-astra", system_prompt="sys", user_prompt="user", imagebytes=b"x", media_type="image/jpeg")
check(calls[0][0] == "chat" and "service_tier" not in calls[0][1], "picture task in Normal: no service_tier")

entry = {"model": "gpt-6.1-sol", "prompt_tokens": 1_000_000, "cached_tokens": 0, "cache_write_tokens": 0, "completion_tokens": 0}
standard = llm_costs.task_cost_usd(dict(entry))
ultra = llm_costs.task_cost_usd(dict(entry, service_tier="ultrafast"))
fast = llm_costs.task_cost_usd(dict(entry, service_tier="fast"))
check(standard is not None and abs(ultra - 6 * standard) < 1e-9, "Ultrafast priced at six times standard")
check(standard is not None and abs(fast - 2 * standard) < 1e-9, "Fast still priced at twice standard")

print()
if failures:
    print(f"{len(failures)} check(s) failed")
    sys.exit(1)
print("All checks passed")
