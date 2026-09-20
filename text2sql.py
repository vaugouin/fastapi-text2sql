import pandas as pd 
import numpy as np 
#pip install psutil
import psutil

import os
import json
import re
import base64
import contextvars
from typing import Optional

import data_watcher
import json_guardrails
from dotenv import load_dotenv
import openai
try:
    import anthropic as anthropic_sdk
except Exception:
    anthropic_sdk = None

try:
    from google import genai
    from google.genai import types as genai_types
except Exception:
    genai = None
    genai_types = None

# Get the virtual memory details
memory_info = psutil.virtual_memory()
# Print the available memory
print("Démarrage de l'API")
print(f"Total Memory: {memory_info.total / (1024 ** 3):.2f} GB")
print(f"Available Memory: {memory_info.available / (1024 ** 3):.2f} GB")
print(f"Used Memory: {memory_info.used / (1024 ** 3):.2f} GB")
print(f"Free Memory: {memory_info.free / (1024 ** 3):.2f} GB")
print(f"Memory Usage: {memory_info.percent}%")

dblavailableram=memory_info.available / (1024 ** 3)

# Text-to-SQL feature
strtext2sqlprompttemplate = "text_to_sql.md"
strtext2sqlmodeldefault = "gpt-4o"

# Complex question feature (stronger model)
strcomplexquestionprompttemplate = "complex_question.md"
strcomplexquestionmodeldefault = "gpt-4o"

# Answer-entity classification (decide result_entity from the ORIGINAL question).
# The strong model is used on purpose: this classification is AUTHORITATIVE over the
# text-to-SQL answer type (it drives the answer-entity guard), so a weak model that
# mistakes a filter phrase ("in the Criterion collection") for the answer would wrongly
# override a correct query. Isolated here so the cost/latency knob is easy to change.
# See f_classify_result_entity().
strresultentitymodeldefault = "gpt-4o"

# Vision identification: read a deposited image and say which work or person it points at
# (FASTAPI-TEXT2SQL-114). Sixth LLM task of the pipeline, and the only one whose input is not
# text. The default is `gpt-6-astra` and not `gpt-4o` like the five others, on purpose: this is
# the model Philippe tried the feature on (2026-09-16, poster and frame both recognised, the
# reasoning model enumerating the clues it read), it is the one whose price the ~4 cents a photo
# figure was computed from, and its family is declared in the reasoning block below since
# FASTAPI-TEXT2SQL-274. Any other model is accepted, like everywhere else here, as long as it
# reads images: see _call_vision_llm, which supports the OpenAI families only and says so.
strvisionprompttemplate = "vision_identification.md"
strvisionmodeldefault = "gpt-6-astra"

# Direct scalar answer when the SQL path returned a single cell worth 0 (FASTAPI-TEXT2SQL-232).
# Until then this task borrowed the complex-question model, which made the two impossible to
# price or to move apart: they are different jobs (one rewrites a question, the other answers
# it from parametric memory) and they deserve their own knob.
stranswersinglevaluemodeldefault = "gpt-4o"

# Sentinel that marks the boundary between the byte-stable static prefix and the
# dynamic suffix (the user question / ui_language) in the prompt templates. Used
# to place an explicit Anthropic `cache_control` breakpoint; stripped out for
# OpenAI/Gemini (whose caching is automatic/prefix-based and needs no marker).
CACHE_BOUNDARY_MARKER = "<!--CACHE_BOUNDARY-->"

#print("Text to SQL prompt template", strtext2sqlprompttemplate)
#print("Entity extraction prompt template", strentityextractionprompttemplate)

# Prompt templates are loaded and kept up-to-date via the data_watcher module.
# They are initialized to empty strings here and populated synchronously by
# the register() calls below.
text2sql_prompt_template = ""
complex_question_prompt_template = ""
vision_identification_prompt_template = ""


def _on_text2sql_prompt_change(content: str) -> None:
    global text2sql_prompt_template
    text2sql_prompt_template = content


def _on_complex_question_prompt_change(content: str) -> None:
    global complex_question_prompt_template
    complex_question_prompt_template = content


def _on_vision_prompt_change(content: str) -> None:
    global vision_identification_prompt_template
    vision_identification_prompt_template = content


data_watcher.register(strtext2sqlprompttemplate, _on_text2sql_prompt_change)
data_watcher.register(strcomplexquestionprompttemplate, _on_complex_question_prompt_change)
data_watcher.register(strvisionprompttemplate, _on_vision_prompt_change)

# Load environment variables (OPENAI_API_KEY)
load_dotenv()

# Check if API key is available
api_key = os.getenv("OPENAI_API_KEY")
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
google_api_key = os.getenv("GOOGLE_API_KEY")
openrouter_api_key = os.getenv("OPENROUTER_API_KEY")

print("LLM API keys loaded:")
print("- OPENAI_API_KEY:", "found" if api_key else "missing")
print("- ANTHROPIC_API_KEY:", "found" if anthropic_api_key else "missing")
print("- GOOGLE_API_KEY:", "found" if google_api_key else "missing")
print("- OPENROUTER_API_KEY:", "found" if openrouter_api_key else "missing")


def _normalize_llm_model(model_name: str, default_value: str) -> str:
    """Normalize an optional model selector by resolving blank and default values."""
    if model_name is None:
        return default_value
    m = str(model_name).strip()
    if m == "" or m.lower() == "default":
        return default_value
    return m


# Per-request buffer of OpenAI prompt-cache observations, surfaced into the
# /search/text2sql response `messages` array by main.py. Isolated per request via
# contextvars: FastAPI runs each request in its own task, which copies the context,
# so concurrent requests never mix events. The complex-question retry re-enters the
# endpoint in the SAME task/context, so it shares this buffer on purpose (main.py
# only resets it for the outer call, keyed on complex_question_already_resolved).
_prompt_cache_events: "contextvars.ContextVar" = contextvars.ContextVar(
    "prompt_cache_events", default=None
)


def reset_prompt_cache_events() -> None:
    """Install a fresh, empty prompt-cache event buffer for the current request."""
    _prompt_cache_events.set([])


def drain_prompt_cache_events() -> list:
    """Return the collected prompt-cache events and clear the buffer.

    Returns an empty list when no buffer was installed (no LLM call happened, or
    the caller never opted in via reset_prompt_cache_events()).
    """
    events = _prompt_cache_events.get()
    if not events:
        return []
    _prompt_cache_events.set([])
    return events


def _record_prompt_cache_event(message_text: str) -> None:
    """Print a prompt-cache observation and record it for the API response messages.

    Each provider logger builds a ready-to-display summary string; main.py drains
    these and appends them to the /search/text2sql response `messages` array.
    """
    print("[prompt-cache] " + message_text)
    buffer = _prompt_cache_events.get()
    if buffer is not None:
        buffer.append({"text": message_text})


def _log_openai_cache_usage(response, *, model_norm: str, label: str = "text2sql") -> None:
    """Log OpenAI automatic prompt-cache stats for a chat/responses call.

    OpenAI caches the longest common prompt prefix automatically (no flag) for
    prompts over ~1024 tokens, in 128-token blocks, billing cached input tokens
    at a reduced rate. The proof a hit occurred is
    ``usage.prompt_tokens_details.cached_tokens > 0`` on a request whose prefix
    matches an earlier one. This logs that field so prompt caching is observable.
    """
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_tokens", None)
        if prompt_tokens is None:
            # Responses API names it differently.
            prompt_tokens = getattr(usage, "input_tokens", None)
        details = getattr(usage, "prompt_tokens_details", None)
        if details is None:
            details = getattr(usage, "input_tokens_details", None)
        cached_tokens = 0
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", 0) or 0
        ratio = (cached_tokens / prompt_tokens) if prompt_tokens else 0.0
        _record_prompt_cache_event(
            f"Prompt cache ({label}): provider=openai, model={model_norm}, "
            f"prompt_tokens={prompt_tokens}, cached_tokens={cached_tokens}, "
            f"hit_ratio={ratio:.1%}."
        )
    except Exception as cache_log_error:
        # Never let cache observability break a request.
        print(f"[prompt-cache][openai][{label}] usage logging failed: {cache_log_error}")


def _log_anthropic_cache_usage(message, *, model_norm: str, label: str = "text2sql") -> None:
    """Log Anthropic explicit prompt-cache stats for a Messages API call.

    Anthropic caching is NOT automatic: it requires a ``cache_control`` breakpoint
    on the static block (placed by ``_build_anthropic_user_content``). On a write
    ``usage.cache_creation_input_tokens > 0``; on a read
    ``usage.cache_read_input_tokens > 0`` (billed ~0.1x). ``input_tokens`` is the
    uncached remainder, so total prompt = input + cache_write + cache_read.
    """
    try:
        usage = getattr(message, "usage", None)
        if usage is None:
            return
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        cache_write = getattr(usage, "cache_creation_input_tokens", 0) or 0
        cache_read = getattr(usage, "cache_read_input_tokens", 0) or 0
        total = input_tokens + cache_write + cache_read
        ratio = (cache_read / total) if total else 0.0
        _record_prompt_cache_event(
            f"Prompt cache ({label}): provider=anthropic, model={model_norm}, "
            f"input_tokens={input_tokens}, cache_write={cache_write}, "
            f"cache_read={cache_read}, hit_ratio={ratio:.1%}."
        )
    except Exception as cache_log_error:
        print(f"[prompt-cache][anthropic][{label}] usage logging failed: {cache_log_error}")


def _log_gemini_cache_usage(response, *, model_norm: str, label: str = "text2sql") -> None:
    """Log Gemini implicit prompt-cache stats for a generate_content call.

    Implicit caching is automatic on Gemini 2.x (prefix-based, like OpenAI); the
    hit shows up as ``usage_metadata.cached_content_token_count > 0``.
    ``prompt_token_count`` is the full (effective) prompt size including any
    cached content. Explicit ``CachedContent`` is not used here.
    """
    try:
        usage = getattr(response, "usage_metadata", None)
        if usage is None:
            return
        prompt_tokens = getattr(usage, "prompt_token_count", 0) or 0
        cached_tokens = getattr(usage, "cached_content_token_count", 0) or 0
        ratio = (cached_tokens / prompt_tokens) if prompt_tokens else 0.0
        _record_prompt_cache_event(
            f"Prompt cache ({label}): provider=google, model={model_norm}, "
            f"prompt_tokens={prompt_tokens}, cached_tokens={cached_tokens}, "
            f"hit_ratio={ratio:.1%}."
        )
    except Exception as cache_log_error:
        print(f"[prompt-cache][google][{label}] usage logging failed: {cache_log_error}")


def _build_anthropic_user_content(user_prompt: str):
    """Split the user prompt at the cache boundary into Anthropic content blocks.

    When the ``CACHE_BOUNDARY_MARKER`` is present, return a two-block list: the
    static prefix carrying a ``cache_control: {"type": "ephemeral"}`` breakpoint,
    followed by the dynamic suffix (no breakpoint). The schema/rules stay in the
    user message (no role change vs. the plain-string path), so SQL behaviour is
    unchanged — only a cache boundary is added. Falls back to the plain string
    when the marker is absent (short prompts that aren't worth caching).
    """
    if CACHE_BOUNDARY_MARKER in user_prompt:
        static_prefix, dynamic_suffix = user_prompt.split(CACHE_BOUNDARY_MARKER, 1)
        return [
            {"type": "text", "text": static_prefix, "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": dynamic_suffix},
        ]
    return user_prompt


# --- OpenAI reasoning-model sampling rules (FASTAPI-TEXT2SQL-231) -------------------
# Reasoning models (o-series, GPT-5.x including the 5.6 Sol / Terra / Luna tiers, and the
# GPT-6 line since FASTAPI-TEXT2SQL-274) reject any `temperature` other than the default and
# answer 400 "Unsupported value: 'temperature' does not support 0 with this model". Every
# task in this pipeline passes temperature=0 on purpose, so before this guard a model swap as
# simple as gpt-4o -> gpt-5.6-terra failed on the first request of all five tasks.
# They take `reasoning_effort` instead, and that parameter is the real cost and latency
# knob: the same model spans ~1.8 s to first token at "low" and ~115 s at "max", and
# reasoning tokens are billed at the output rate.
#
# Adding a family here is NOT cosmetic and NOT optional (FASTAPI-TEXT2SQL-274). The dispatcher
# in _call_chat_llm is permissive: anything starting with "gpt-" already routes to OpenAI, and
# the five `llm_model_*` request fields are unvalidated `Optional[str]`. So an unknown
# reasoning family does not bounce, it leaves, with `temperature` attached and no effort at
# all, which is the worst of both: a 400 on every call, or silent default-tier spending.
_REASONING_MODEL_PREFIXES = ("gpt-5", "gpt-6", "o1", "o3", "o4")

# Per-task effort TIER, resolved to a provider value by _resolve_reasoning_effort below.
# Deliberately conservative: the tasks on the 100 % path get the cheapest setting, because
# the API's p50 is 5.45 s end to end and there is no room for a thinking budget there. Only
# the complex-question pair, which fires on ~1 % of requests, is allowed to spend.
#
# `vision_identification` is the sixth task (FASTAPI-TEXT2SQL-114). Its tier is declared here
# ahead of that ticket so the family table below is complete on the day the task lands, and it
# starts at the cheapest setting on purpose: -114 says to begin at effort "low" and to raise it
# only if recognition weakens on the twenty-image bench. Its row costing ~4 cents a photo is a
# reason to measure before spending, not a reason to pre-spend.
_DEFAULT_EFFORT_TIER = {
    "entity_extraction": "cheapest",
    "text2sql": "cheapest",
    "result_entity": "cheapest",
    "complex_question": "medium",
    "answer_single_value": "medium",
    "vision_identification": "cheapest",
}

# The families do not share a vocabulary, and getting this wrong is a 400 on every call,
# not a degradation. Measured against the live API on 2026-08-30: GPT-5.6 answers
# "Unsupported value: 'reasoning_effort' does not support 'minimal' with this model.
# Supported values are: 'none', 'low', 'medium', 'high', and 'xhigh'." `minimal` was a
# GPT-5.0-era value and it is gone; the cheapest 5.6 setting is `none`, which spends no
# reasoning tokens at all. The o-series has no `none`, so its floor is `low`.
#
# GPT-6 (FASTAPI-TEXT2SQL-274) declares five rungs, `low`, `medium`, `high`, `xhigh`, `max`,
# and, the difference that matters for the bill, it has NO `none`: its floor is `low`, like
# the o-series and unlike GPT-5.6. Mapping "cheapest" to `none` here would be a 400, and
# mapping it to `medium` would quietly buy a thinking budget on the three tasks that fire on
# 100 % of requests. Only the two rungs this pipeline actually asks for are listed; the three
# upper ones are documented rather than declared, because a rung nobody selects is a rung
# nobody has measured.
_EFFORT_BY_FAMILY = {
    "gpt-5": {"cheapest": "none", "medium": "medium"},
    "gpt-6": {"cheapest": "low", "medium": "medium"},
    "o":     {"cheapest": "low", "medium": "medium"},
}

# Longest prefix wins, so a future "gpt-6x" line gets its own row without disturbing this one.
# Anything not listed falls back to the o-series vocabulary, which is the conservative guess:
# its floor is `low`, a value every reasoning family here accepts.
_REASONING_FAMILY_BY_PREFIX = (
    ("gpt-5", "gpt-5"),
    ("gpt-6", "gpt-6"),
)

# Which OpenAI endpoint serves a reasoning model, decided rather than inherited
# (FASTAPI-TEXT2SQL-274). `gpt-6-astra` accepts both `responses.create` and
# `chat.completions`, so the choice was free and is made here: chat.completions, the same
# route as GPT-5.x. Two reasons, and neither is taste. The prompt-cache accounting this
# pipeline reports is the one measured on chat.completions (the two routes name their usage
# fields differently, see _log_openai_cache_usage), and the static prefix of
# data/text_to_sql.md makes that measurement the single most expensive thing to get wrong:
# 24.2 K tokens measured 2026-09-19, so caching turns $0.242 a call into $0.0242. Comparing a
# gpt-6 campaign against the gpt-4o baseline also requires that both travel the same route.
# The o-series keeps the Responses API, which is the only place it was ever exercised.
_CHAT_COMPLETIONS_REASONING_PREFIXES = ("gpt-5", "gpt-6")


def _reasoning_family(model_norm: str) -> str:
    """Return the effort-vocabulary family of an OpenAI reasoning model."""
    m = str(model_norm).strip().lower()
    for prefix, family in _REASONING_FAMILY_BY_PREFIX:
        if m.startswith(prefix):
            return family
    return "o"


def _resolve_reasoning_effort(model_norm: str, cache_label: str) -> str:
    """Return the provider-accepted effort value for this model family and task."""
    family = _reasoning_family(model_norm)
    tier = _DEFAULT_EFFORT_TIER.get(cache_label, "cheapest")
    efforts = _EFFORT_BY_FAMILY[family]
    # A tier a family does not declare degrades to its cheapest rung rather than raising:
    # this function runs inside a live request, and a KeyError here would turn a missing
    # table entry into a 500 on a task that would otherwise have answered.
    return efforts.get(tier) or efforts["cheapest"]


def _is_openai_reasoning_model(model_norm: str) -> bool:
    """True when the model rejects `temperature` and expects `reasoning_effort` instead."""
    return str(model_norm).strip().lower().startswith(_REASONING_MODEL_PREFIXES)


def _uses_openai_responses_api(model_norm: str) -> bool:
    """True when this reasoning model is served through `responses.create`.

    Case-folded on purpose: `_is_openai_reasoning_model` lowercases, and before -274 the
    family test that followed it did not, so an oddly-cased `GPT-5.6-terra` took the
    Responses branch while its lowercase twin took chat.completions.
    """
    m = str(model_norm).strip().lower()
    return _is_openai_reasoning_model(m) and not m.startswith(_CHAT_COMPLETIONS_REASONING_PREFIXES)


def _openai_sampling_kwargs(model_norm: str, temperature: float, cache_label: str,
                            reasoning_effort: Optional[str] = None) -> dict:
    """Build the sampling half of an OpenAI call, per model family.

    Non-reasoning models (gpt-4o and the rest of the 4.x line) keep `temperature`, so
    nothing about existing behaviour moves. Reasoning models get `reasoning_effort` and
    no `temperature` at all: passing the default value explicitly is still a 400 on some
    routes, so the parameter is omitted rather than pinned to 1.

    Args:
        reasoning_effort: Explicit override; when None the per-task default above applies.
            Pass "none" to disable reasoning where the model allows it.
    """
    if not _is_openai_reasoning_model(model_norm):
        return {"temperature": temperature}
    effort = reasoning_effort or _resolve_reasoning_effort(model_norm, cache_label)
    if not effort or str(effort).strip().lower() == "default":
        return {}
    return {"reasoning_effort": str(effort).strip().lower()}


def _as_responses_api_kwargs(sampling_kwargs: dict) -> dict:
    """Translate chat.completions sampling kwargs into their Responses API spelling.

    The two routes name the effort knob differently: `reasoning_effort="low"` on
    `chat.completions.create`, `reasoning={"effort": "low"}` on `responses.create`. Passing
    the flat form to the Responses API is rejected, and since that call sits inside a
    `try/except` that falls back to chat.completions, the failure was invisible: the o-series
    reached the fallback on every call and ran at its default effort. Found while deciding the
    GPT-6 branch in FASTAPI-TEXT2SQL-274; the GPT-6 and GPT-5.x families do not use this path.
    """
    out = dict(sampling_kwargs)
    effort = out.pop("reasoning_effort", None)
    if effort:
        out["reasoning"] = {"effort": effort}
    return out


def _call_chat_llm(*, model: str, system_prompt: str, user_prompt: str, temperature: float,
                   cache_label: str = "text2sql", reasoning_effort: Optional[str] = None) -> str:
    """Call the selected LLM and return raw text content.

    Args:
        cache_label: Pipeline step name used to tag prompt-cache observations
            (e.g. "entity_extraction", "text2sql", "complex_question"). Also selects the
            default reasoning effort when the model is an OpenAI reasoning model.
        reasoning_effort: Optional per-call override of that default. Ignored by models
            that do not take the parameter.
    """
    model_norm = str(model).strip()
    if model_norm == "gemma-4":
        model_norm = "google/gemma-4-26b-a4b-it:free"
    if model_norm == "gemma-4-google":
        model_norm = "gemma-4-26b-a4b-it"

    # Anthropic splits the user prompt on CACHE_BOUNDARY_MARKER to place an explicit
    # cache breakpoint; every other provider gets the marker stripped (their caching
    # is automatic/prefix-based, so the sentinel would only pollute the prompt text).
    user_prompt_plain = user_prompt.replace(CACHE_BOUNDARY_MARKER, "")

    if model_norm in {"gpt-4o"} or model_norm.startswith("gpt-") or model_norm.startswith("o1") or model_norm.startswith("o3") or model_norm.startswith("o4"):
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not found in environment variables")
        client = openai.OpenAI(api_key=api_key)
        sampling_kwargs = _openai_sampling_kwargs(model_norm, temperature, cache_label, reasoning_effort)

        if _uses_openai_responses_api(model_norm):
            # o-series only. GPT-5.x and GPT-6 are served through chat.completions below, where
            # the prompt-cache accounting this pipeline depends on is the one already measured
            # (FASTAPI-TEXT2SQL-274 made that an explicit decision rather than a leftover).
            try:
                response = client.responses.create(
                    model=model_norm,
                    input=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt_plain},
                    ],
                    **_as_responses_api_kwargs(sampling_kwargs),
                )
                _log_openai_cache_usage(response, model_norm=model_norm, label=cache_label)
                out_text = getattr(response, "output_text", None)
                if out_text:
                    return out_text
                raise RuntimeError("No output_text in OpenAI Responses API response")
            except Exception:
                # Fallback to chat.completions for environments where Responses API isn't available
                pass

        response = client.chat.completions.create(
            model=model_norm,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_plain},
            ],
            **sampling_kwargs,
        )
        _log_openai_cache_usage(response, model_norm=model_norm, label=cache_label)
        if not response.choices or not response.choices[0].message or not response.choices[0].message.content:
            raise RuntimeError("No content in OpenAI API response")
        return response.choices[0].message.content

    if model_norm == "google/gemma-4-26b-a4b-it:free" or model_norm.startswith("google/"):
        if not openrouter_api_key:
            raise RuntimeError("OPENROUTER_API_KEY not found in environment variables")
        client = openai.OpenAI(
            api_key=openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
        )
        response = client.chat.completions.create(
            model=model_norm,
            temperature=temperature,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt_plain},
            ],
        )
        if not response.choices or not response.choices[0].message or not response.choices[0].message.content:
            raise RuntimeError("No content in OpenRouter API response")
        return response.choices[0].message.content

    if model_norm.startswith("claude-"):
        if anthropic_sdk is None:
            raise RuntimeError("anthropic package is not installed")
        if not anthropic_api_key:
            raise RuntimeError("ANTHROPIC_API_KEY not found in environment variables")
        client = anthropic_sdk.Anthropic(api_key=anthropic_api_key)
        message = client.messages.create(
            model=model_norm,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": _build_anthropic_user_content(user_prompt)}],
            temperature=temperature,
        )
        _log_anthropic_cache_usage(message, model_norm=model_norm, label=cache_label)
        return message.content[0].text

    if model_norm.startswith("gemini-") or model_norm.startswith("gemma-4-"):
        if genai is None:
            raise RuntimeError("google-genai is not installed")
        if genai_types is None:
            raise RuntimeError("google-genai is not installed")
        if not google_api_key:
            raise RuntimeError("GOOGLE_API_KEY not found in environment variables")

        client = genai.Client(api_key=google_api_key)

        tried_models = []
        models_to_try = [model_norm]

        if model_norm.startswith("gemini-"):
            if not model_norm.endswith("-latest"):
                models_to_try.append(f"{model_norm}-latest")

            for m in [
                "gemini-2.5-flash",
                "gemini-1.5-pro",
                "gemini-1.5-pro-latest",
                "gemini-1.5-flash",
                "gemini-1.5-flash-latest",
                "gemini-1.5-pro-002",
                "gemini-1.5-flash-002",
                "gemini-1.0-pro",
            ]:
                if m not in models_to_try:
                    models_to_try.append(m)

        last_exc = None
        for candidate in models_to_try:
            tried_models.append(candidate)
            try:
                config = genai_types.GenerateContentConfig(
                    temperature=temperature,
                    system_instruction=system_prompt,
                )
                res = client.models.generate_content(
                    model=candidate,
                    contents=user_prompt_plain,
                    config=config,
                )
                _log_gemini_cache_usage(res, model_norm=candidate, label=cache_label)
                if getattr(res, "text", None):
                    return res.text
                raise RuntimeError("No text in Google GenAI API response")
            except Exception as e:
                last_exc = e
                msg = str(e)
                # Only fall back on "model not found" errors; otherwise surface immediately.
                if "NOT_FOUND" in msg or "is not found" in msg or "404" in msg:
                    continue
                raise

        raise RuntimeError(
            f"Error calling model '{model_norm}' (NOT_FOUND). Tried: {', '.join(tried_models)}. Last error: {last_exc}"
        )

    raise RuntimeError(f"Unsupported LLM model: {model_norm}")


def _complex_question_temperature(model: str) -> float:
    """Return a model-compatible temperature for complex-question resolution.

    Since FASTAPI-TEXT2SQL-231 the value returned here is simply ignored for reasoning
    models: `_openai_sampling_kwargs` omits `temperature` for the whole o-series and
    GPT-5.x family rather than pinning it to the default, because passing it explicitly
    is still rejected on some routes. The function is kept because it is the single
    place that answers "what temperature does this task want", which stays a real
    question for gpt-4o and for the Anthropic/Gemini/OpenRouter branches.
    """
    model_norm = str(model).strip()
    if _is_openai_reasoning_model(model_norm):
        return 1
    return 0

def f_text2sql(user_question: str, strtext2sqlmodel: str, ui_language: str = "en", correction_hint: str = ""):
    """Convert natural language question to JSON using the LLM provider SDK.

    Args:
        user_question (str): The user's natural language question
        strtext2sqlmodel (str): The model to use for SQL generation
        ui_language (str): Language code for the user-oriented answer (default: "en")
        correction_hint (str): Optional corrective instruction appended to the prompt,
            used by the answer-entity guard to request a single targeted regeneration
            when the first query returned the wrong result entity.

    Returns:
        str: The generated JSON
    """
    print("Text to SQL")
    print("User question:", user_question)
    model_to_use = _normalize_llm_model(strtext2sqlmodel, strtext2sqlmodeldefault)
    print("Text2SQL LLM model:", model_to_use)

    try:
        # Use the text2sql_prompt_template from the data/prompt.txt file
        #print("Text to SQL prompt template")
        formatted_prompt = text2sql_prompt_template.replace("{user_question}", user_question)
        formatted_prompt = formatted_prompt.replace("{ui_language}", ui_language)
        if correction_hint:
            formatted_prompt = formatted_prompt + "\n\n" + correction_hint

        json_content = _call_chat_llm(
            model=model_to_use,
            system_prompt="You are a MariaDB SQL query generator. Respond only with the JSON content, no explanations.",
            user_prompt=formatted_prompt,
            temperature=0,
            cache_label="text2sql",
        ).strip()
        
        # Check if json_content starts with ```json and remove it
        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        
        # Check if json_content ends with ``` and remove it
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()

        if json_content.endswith(";"):
            json_content = json_content[:-1].strip()
            
        # Replace escaped newlines (\n) with spaces
        json_content = json_content.replace("\\n", " ")
            
        # Strip any remaining whitespace
        json_content = json_content.strip()
        
        print(f"Generated JSON: {json_content}")

        cleaned_content = json_content.strip().strip('\n').strip('\r').strip('\n')
        if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
            return {"error": "Incomplete JSON response from API", "raw_content": json_content}

        try:
            parsed = json.loads(cleaned_content)
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in text2sql conversion: {str(json_error)}")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}
        # JSON guardrail (FASTAPI-TEXT2SQL-038): validate the output shape.
        ok, guard_error = json_guardrails.validate_llm_json(parsed, "text2sql")
        if not ok:
            print(f"JSON guardrail failed in text2sql conversion: {guard_error}")
            return {"error": f"JSON guardrail: {guard_error}", "raw_content": json_content}
        return parsed
    except Exception as e:
        print(f"Error in text2sql conversion: {str(e)}")
        return {"error": f"Error: {str(e)}"}


def f_classify_result_entity(user_question: str, allowed_entities, strmodel: str = "default") -> str:
    """Classify which entity type the user wants *listed*, from the ORIGINAL question.

    ``result_entity`` is normally decided by the text-to-SQL LLM on the ANONYMIZED
    question. Anonymization can flip the apparent answer type when the head noun is
    itself an entity word: e.g. "Which movie directors died in 2025?" anonymizes to
    "Which movie {{Department_name1}} died in {{Death_year1}}?", in which the leftover
    "movie" reads as the head, so the model returns movies instead of the directors.
    Re-deriving the expected answer type from the original question (which still says
    "directors") gives the answer-entity guard a trustworthy expectation to enforce.
    Extends the answer-entity guard (FASTAPI-TEXT2SQL-117/-136).

    Args:
        user_question: The original, de-anonymized user question.
        allowed_entities: Iterable of valid lowercase result-entity strings
            (passed in by the caller — the single source of truth is
            ``main._RESULT_ENTITY_SOURCES`` — so this never drifts).
        strmodel: Optional model override; "default" -> ``strresultentitymodeldefault``.

    Returns:
        A lowercase entity string contained in ``allowed_entities``, or "" when the
        model is uncertain or the answer is multi-entity / unmapped. On "" the caller
        falls back to the LLM's own ``result_entity`` (legacy behavior).
    """
    allowed = [str(e).strip().lower() for e in allowed_entities if str(e).strip()]
    if not user_question or not user_question.strip() or not allowed:
        return ""
    model_to_use = _normalize_llm_model(strmodel, strresultentitymodeldefault)
    system_prompt = (
        "You classify what kind of thing a user wants LISTED in the results of a "
        "movie / TV database query. Reply with EXACTLY ONE lowercase word from this set:\n"
        + ", ".join(allowed) + "\n"
        "Decide the type of the ROWS the user wants back — never the filters/constraints "
        "used to narrow the search.\n"
        "Filter traps (do NOT return one of these just because the word appears in the "
        "question):\n"
        "- A named collection / franchise, award, genre, list, company, network, movement "
        "or location used as a CONSTRAINT is a filter, not the answer. Phrases like 'in the "
        "Criterion collection', 'won the Palme d'Or', 'Sci-Fi movies', 'on Netflix', 'set in "
        "Paris' only scope the query.\n"
        "- 'movie' / 'film' / 'TV' / 'serie' in front of a role ('movie directors') only "
        "scopes the medium; the role is what the user wants listed.\n"
        "Image requests: 'pictures / photos / portraits / images / posters / backdrops OF a "
        "person, movie or serie' means the user wants the IMAGE ROWS, not the entity card -> "
        "return the image type: person_image ('<person> pictures/photos/portraits/images'), "
        "movie_image / serie_image ('<movie/serie> posters/backdrops/images').\n"
        "Examples:\n"
        "- 'List the movie directors with the most movies in the Criterion collection' -> person "
        "(the directors are the answer; 'Criterion collection' is only a filter).\n"
        "- 'Which movie directors died in 2025?' -> person.\n"
        "- 'movies with Brad Pitt' -> movie.\n"
        "- 'who directed Inception?' -> person.\n"
        "- 'List Criterion collection movies' -> movie (you want movies; the collection filters).\n"
        "- 'What collections is Inception part of?' -> collection (here the collections ARE the answer).\n"
        "- 'Sci-Fi series on HBO' -> serie (the genre filters).\n"
        "- 'List Sci-Fi movies' -> movie (the genre filters).\n"
        "- 'What are all the movie genres?' / 'list the genres' -> genre (here the genres ARE the answer).\n"
        "- 'Show Zendaya pictures' / 'photos of Timothee Chalamet' -> person_image (the photos are the answer, not the person card).\n"
        "- 'Dune posters' -> movie_image.  'backdrops of Breaking Bad' -> serie_image.\n"
        "If the answer mixes movies and series, or you are genuinely unsure, reply exactly: "
        "unknown (the caller then trusts the SQL-generation step instead).\n"
        "Reply with only the single word: no punctuation, no quotes, no explanation."
    )
    try:
        raw = _call_chat_llm(
            model=model_to_use,
            system_prompt=system_prompt,
            user_prompt=user_question,
            temperature=0,
            cache_label="result_entity",
        ).strip().lower()
    except Exception as e:
        # Classification is best-effort; never let it break a request.
        print(f"Error in result_entity classification: {str(e)}")
        return ""
    # Defend against stray punctuation / extra words: keep the first [a-z_] token only.
    token = re.split(r"[^a-z_]+", raw, maxsplit=1)[0] if raw else ""
    return token if token in allowed else ""


def f_resolve_complex_question(user_question: str, strcomplexquestionmodel: str = "default"):
    """Rewrite a complex, non-anonymized question into a simpler question for Text-to-SQL."""
    print("Complex question resolution")
    print("User question:", user_question)

    model_to_use = _normalize_llm_model(strcomplexquestionmodel, strcomplexquestionmodeldefault)
    temperature_to_use = _complex_question_temperature(model_to_use)
    print("Complex question LLM model:", model_to_use)

    try:
        try:
            formatted_prompt = complex_question_prompt_template.replace("{user_question}", user_question)
        except Exception as format_error:
            print(f"Error formatting complex question prompt template: {str(format_error)}")
            print(f"User question: '{user_question}'")
            return {"error": f"Prompt formatting failed: {str(format_error)}"}

        try:
            json_content = _call_chat_llm(
                model=model_to_use,
                system_prompt="You are a powerful question resolver. Respond only with the JSON content, no explanations.",
                user_prompt=formatted_prompt,
                temperature=temperature_to_use,
                cache_label="complex_question",
            ).strip()
        except Exception as api_error:
            msg = str(api_error)
            # If the chosen stronger model isn't available (common with o1/o3 gated access),
            # retry once with the default chat model so the pipeline can still proceed.
            if (
                model_to_use != "gpt-4o"
                and (
                    "model_not_found" in msg
                    or "does not exist" in msg
                    or "you do not have access" in msg
                    or "404" in msg
                )
            ):
                try:
                    json_content = _call_chat_llm(
                        model="gpt-4o",
                        system_prompt="You are a powerful question resolver. Respond only with the JSON content, no explanations.",
                        user_prompt=formatted_prompt,
                        temperature=_complex_question_temperature("gpt-4o"),
                        cache_label="complex_question",
                    ).strip()
                except Exception as fallback_error:
                    print(f"LLM API call failed: {str(fallback_error)}")
                    print(f"API error type: {type(fallback_error)}")
                    return {"error": f"LLM API call failed: {str(fallback_error)}"}
            else:
                print(f"LLM API call failed: {str(api_error)}")
                print(f"API error type: {type(api_error)}")
                return {"error": f"LLM API call failed: {str(api_error)}"}

        if json_content.startswith("```json"):
            json_content = json_content[7:].strip()
        if json_content.endswith("```"):
            json_content = json_content[:-3].strip()

        cleaned_content = json_content.strip().strip('\n').strip('\r').strip('\n')
        if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
            return {"error": "Incomplete JSON response from API", "raw_content": json_content}

        try:
            parsed = json.loads(cleaned_content)
        except json.JSONDecodeError as json_error:
            print(f"JSON parsing error in complex question resolution: {str(json_error)}")
            return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}
        # JSON guardrail (FASTAPI-TEXT2SQL-038): validate the output shape.
        ok, guard_error = json_guardrails.validate_llm_json(parsed, "complex_question")
        if not ok:
            print(f"JSON guardrail failed in complex question resolution: {guard_error}")
            return {"error": f"JSON guardrail: {guard_error}", "raw_content": json_content}
        return parsed

    except Exception as e:
        print(f"Error in complex question resolution: {str(e)}")
        return {"error": str(e)}


def f_build_retry_question_from_reasoning(resolved: dict) -> str:
    """Convert structured complex-question reasoning output into a retry question string."""
    try:
        if not isinstance(resolved, dict):
            return ""
        items = resolved.get("items")
        base_q = str(resolved.get("question") or "").strip()
        if not isinstance(items, list) or len(items) == 0:
            return base_q

        cleaned_items = []
        for it in items:
            if not isinstance(it, dict):
                continue
            v = str(it.get("value") or "").strip()
            if v == "":
                continue
            y = str(it.get("year") or "").strip()
            bare = v
            if re.fullmatch(r"\d{4}", y or ""):
                v = f"{v} ({y})"
            t = str(it.get("type") or "").strip().lower()
            cleaned_items.append({"type": t, "value": v, "year": y, "bare_value": bare})

        if len(cleaned_items) == 0:
            return base_q

        if len(cleaned_items) == 1 and base_q == "":
            it0 = cleaned_items[0]
            t0 = it0.get("type")
            # The title WITHOUT its parenthesised year, because the single-item patterns below
            # state the year themselves: `Movie Blade Runner (1982) released in 1982` was what
            # this branch produced, and the redundancy only stayed invisible because the branch
            # is nearly dead on the complex-retry path (the stronger model almost always fills
            # `question`, so `base_q` is not empty and this code is skipped). The vision
            # pre-stage of FASTAPI-TEXT2SQL-114 never fills `question`, so it exercises this
            # branch on every lone photo. The list branch below keeps the parenthesised form,
            # which is right there: `Movies A (1931), B (1992)` has nowhere else to put a year.
            v0 = it0.get("bare_value") or it0.get("value")
            y0 = it0.get("year")
            if t0 == "movie":
                if re.fullmatch(r"\d{4}", y0 or ""):
                    return f"Movie {v0} released in {y0}"
                return f"Movie {v0}"
            if t0 == "person":
                if re.fullmatch(r"\d{4}", y0 or ""):
                    return f"Person {v0} born in {y0}"
                return f"Person {v0}"
            if t0 == "serie":
                return f"Serie {v0}"
            if t0 == "topic":
                return f"Topic {v0}"
            return v0

        if len(cleaned_items) >= 2:
            types = [c.get("type") for c in cleaned_items]
            t0 = types[0] if types else ""
            same_type = all(t == t0 for t in types)
            prefix = "Items"
            if same_type:
                if t0 == "movie":
                    prefix = "Movies"
                elif t0 == "person":
                    prefix = "Persons"
                elif t0 == "topic":
                    prefix = "Topics"
                elif t0 == "company":
                    prefix = "Companies"
                elif t0 == "network":
                    prefix = "Networks"
                elif t0 == "location":
                    prefix = "Locations"
                elif t0 == "serie":
                    prefix = "Series"
                elif t0:
                    prefix = f"{t0.capitalize()}s"
            values = [c.get("value") for c in cleaned_items if c.get("value")]
            if values:
                return f"{prefix} " + ", ".join(values)
        return base_q
    except Exception:
        try:
            return str(resolved.get("question") or "").strip()
        except Exception:
            return ""


# FASTAPI-TEXT2SQL-263. The entity-card patterns the stronger model is allowed to emit
# (`data/complex_question.md`). A rewrite that collapses to one of these has stopped asking
# anything: it identifies a thing. Kept in sync with the prompt's pattern list.
_RETRY_ENTITY_CARD_PREFIXES = (
    "movie", "movies", "serie", "series", "person", "persons", "people",
    "topic", "topics", "collection", "collections", "location", "locations",
    "company", "companies", "network", "networks", "award", "awards",
    "nomination", "nominations", "movement", "movements",
    "group", "groups", "death", "deaths", "items",
)
# "List"/"Lists" are deliberately absent. `List Criterion Collection` (the entity card) and
# `list movies happening in Paris` (a request) are the same first word, and no test of form
# separates them. Missing a genuine `List X` rewrite is the cheaper error: this signal can
# drive a warning or a refusal, so a false alarm costs more than a silence.

# Interrogative markers, English and French. A question carrying one of these asks about a
# RELATION of the entity, not about the entity's identity.
_RETRY_INTERROGATIVE_WORDS = (
    "who", "what", "which", "where", "when", "why", "how", "whose", "whom",
    "qui", "que", "quoi", "quel", "quelle", "quels", "quelles", "ou", "où",
    "quand", "pourquoi", "comment", "combien", "list", "give", "show", "name",
    "find", "liste", "donne", "montre", "cite", "trouve",
)


def f_retry_question_drops_intent(
    original_question: str,
    retry_question: str,
    expected_result_entity: str = "",
    retry_result_entity: str = "",
) -> bool:
    """True when the stronger model's rewrite replaced the question instead of repairing it.

    FASTAPI-TEXT2SQL-263. Not every rewrite is a loss. `Marion Morrison` -> `Person John
    Wayne` keeps the intention and serves it better, and `guess the movie with a rosebud` ->
    `Movie Citizen Kane (1941)` IS the answer, in entity-card form, which is exactly what the
    complex-question prompt exists to produce. But `In which city the action of movie Pulp
    Fiction takes place?` -> `Movie Pulp Fiction (1994)` REPLACES the question, and the API
    then answers something nobody asked, with no error and no signal. That is the one failure
    mode `data/complex_question.md` tells the model never to produce, applied to questions
    rather than to names.

    TWO conditions, both required, because neither carries it alone:

    1. **Form.** The original asks about a relation (an interrogative marker, or a question
       mark) and the rewrite has collapsed into a bare entity card. Alone, this flags the
       legitimate `which movie has a rosebud?` -> `Movie Citizen Kane`.
    2. **Type.** The answer entity the ORIGINAL question calls for is not the one the retry
       returned: asked for a city, given a movie. This is the discriminator, and it is free:
       `expected_result_entity` is already classified from the original question by the
       answer-entity guard (-117/-136), and `retry_result_entity` is on the retry response.

    Both classifications are required. When either is missing the function returns False:
    a silence is cheaper than a wrong alarm on a signal that may drive a refusal.
    """
    try:
        _orig = str(original_question or "").strip().lower()
        _retry = str(retry_question or "").strip().lower()
        _expected = str(expected_result_entity or "").strip().lower()
        _returned = str(retry_result_entity or "").strip().lower()
        if _orig == "" or _retry == "":
            return False
        # Condition 2 first: it is the cheap, decisive one.
        if _expected == "" or _returned == "" or _expected == _returned:
            return False

        def _words(text: str) -> list:
            return re.findall(r"[a-zà-ÿ]+", text)

        _orig_words = _words(_orig)
        _retry_words = _words(_retry)
        if not _orig_words or not _retry_words:
            return False

        original_asks = ("?" in _orig) or any(w in _RETRY_INTERROGATIVE_WORDS for w in _orig_words)
        if not original_asks:
            return False

        retry_asks = ("?" in _retry) or any(w in _RETRY_INTERROGATIVE_WORDS for w in _retry_words)
        if retry_asks:
            return False

        return _retry_words[0] in _RETRY_ENTITY_CARD_PREFIXES
    except Exception:
        # A guard that raises must not break the retry it is only meant to describe.
        return False


def f_answer_single_value(user_question: str, strcomplexquestionmodel: str = "default"):
    """Ask the stronger model to directly answer a question with a single scalar value.

    Used when a SQL query returned a single-cell result with value 0, suggesting
    the SQL approach failed. The stronger model provides the factual answer directly.

    Args:
        user_question: The original user question.
        strcomplexquestionmodel: The model to use for answering. Since
            FASTAPI-TEXT2SQL-232 this resolves against
            ``stranswersinglevaluemodeldefault``, its own default, not the
            complex-question one: the two tasks share a caller but not a job, and the
            parameter name is kept only so existing positional callers keep working.

    Returns:
        dict with keys:
            - "value": the scalar answer (int, float, or str), or None on failure
            - "error": error message if the call failed, else ""
    """
    model_to_use = _normalize_llm_model(strcomplexquestionmodel, stranswersinglevaluemodeldefault)
    temperature_to_use = _complex_question_temperature(model_to_use)

    system_prompt = (
        "You are a factual knowledge assistant. "
        "Answer the following question with ONLY a single numeric or short scalar value. "
        "Do not explain, do not add units unless essential, do not add any surrounding text. "
        "If the answer is a number, return only the number. "
        "If you cannot determine the answer, return exactly: UNKNOWN"
    )

    try:
        raw_answer = _call_chat_llm(
            model=model_to_use,
            system_prompt=system_prompt,
            user_prompt=user_question,
            temperature=temperature_to_use,
            cache_label="answer_single_value",
        ).strip()
    except Exception as e:
        return {"value": None, "error": f"LLM call failed: {str(e)}"}

    if raw_answer.upper() == "UNKNOWN":
        return {"value": None, "error": "Model could not determine the answer."}

    # Try to parse as int, then float, otherwise keep as string
    try:
        parsed = int(raw_answer)
        return {"value": parsed, "error": ""}
    except ValueError:
        pass
    try:
        parsed = float(raw_answer)
        return {"value": parsed, "error": ""}
    except ValueError:
        pass

    return {"value": raw_answer, "error": ""}


def f_resolve_complex_question_retry_payload(user_question: str, strcomplexquestionmodel: str = "default"):
    """Resolve a complex question and package the retry payload used by the API flow."""
    resolved_complex = f_resolve_complex_question(user_question, strcomplexquestionmodel)
    retry_question = f_build_retry_question_from_reasoning(resolved_complex)
    try:
        reasoning_justification = str(resolved_complex.get("justification") or "").strip()
    except Exception:
        reasoning_justification = ""
    return {
        "resolved": resolved_complex,
        "retry_question": retry_question,
        "justification": reasoning_justification,
        "has_error": not (isinstance(resolved_complex, dict) and not resolved_complex.get("error")),
        # FASTAPI-TEXT2SQL-221. Distinct from has_error on purpose: this is not a failure,
        # it is the model affirming that the empty database result stands. The caller has
        # to be able to tell the two apart, which is what -156 and -207 have been asking
        # for, and what an empty "question" alone could never express.
        "authoritative_empty": bool(
            isinstance(resolved_complex, dict) and resolved_complex.get("authoritative_empty")),
    }


# ---------------------------------------------------------------------------
# Vision identification, the sixth LLM task (FASTAPI-TEXT2SQL-114)
# ---------------------------------------------------------------------------
# An image enters the pipeline as an `image_ref` on /search/text2sql, is read here, and
# leaves as a question in words. Everything downstream (entity extraction, text-to-SQL,
# resolution, cache, pagination) is untouched: only the MODALITY of the fuzzy input
# changes, which is what makes this feature much cheaper than it looks.
#
# Two boundaries worth knowing before editing this block.
#
# **This task identifies, it never composes the question that reaches the database.** The
# composition is deterministic, below, and that is a decision rather than an omission: the
# identification of an image does not depend on the question asked about it, so it is cached
# on the MD5 of the bytes (see vision_cache.py). A model-composed question would make the
# cached path and the fresh path produce different questions for the same photo, and the
# divergence would only show up in production, on the second turn of a conversation.
#
# **This task never answers a catalogue question.** "Who directed this?" is answered by the
# catalogue, from the work identified here. The prompt says so twice; the code enforces it by
# reading nothing but `hints`, `items`, `about_image`, `image_answer`, `authoritative_empty`.

# OpenAI bills an image by patches: a 1024x1024 photo at detail "high" is
# ceil(1024/32)^2 = 1024 patches, billed ceil(1024 * 1.2) = 1229 tokens, about $0.0123 at
# $10 per million. "low" divides that by twenty and loses the credits block of a poster,
# which the ticket calls the most discriminating clue a poster carries. So: "high", and let the client
# bound the bill by resizing before the deposit (the front resizes to ~1024 px, q~0.8).
VISION_IMAGE_DETAIL = "high"

# Telling two candidates apart (FASTAPI-TEXT2SQL-114 point 8, arbitrage 5 of VOICE-AGENT-179).
# A candidate that clearly dominates opens its entry, with the alternative reported beside it;
# candidates that sit close are all presented, which is rule VOICE-AGENT-093.
#
# **These two values are PROVISIONAL and have not been measured.** The ticket is explicit that
# the threshold is settled on the twenty-image bench and not guessed, and that bench does not
# exist yet (FASTAPI-TEXT2SQL-277). They are named constants precisely so the measurement has
# somewhere to land: do not inline them, and do not tune them on a single bad photo.
VISION_CONFIDENCE_DOMINANT = 0.70
VISION_CONFIDENCE_MARGIN = 0.20

# At most this many candidates reach the composed question. Beyond it the model is listing
# rather than identifying, and a list question returns a page of unrelated rows.
VISION_MAX_CANDIDATES = 5

# The item types the composer knows how to phrase. Same vocabulary as complex_question.md,
# deliberately: f_build_retry_question_from_reasoning is shared with the complex-retry path.
_VISION_ITEM_TYPES = (
    "movie", "serie", "person", "collection", "topic",
    "company", "network", "location", "other",
)

# How each type reads inside a user's own question. "who directed {phrase}?" must come out as
# a sentence, so these carry their article and stay lowercase. Per language, because the
# substitution happens INSIDE the user's own words: dropping "the movie Blade Runner" into
# "qui a realise ce film ?" would hand the pipeline a sentence no one wrote.
_VISION_TYPE_PHRASE = {
    "en": {
        "movie": "the movie",
        "serie": "the TV series",
        "person": "the person",
        "collection": "the collection",
        "topic": "the topic",
        "company": "the company",
        "network": "the network",
        "location": "the location",
    },
    "fr": {
        "movie": "le film",
        "serie": "la série",
        "person": "la personne",
        "collection": "la collection",
        "topic": "le sujet",
        "company": "la société",
        "network": "la chaîne",
        "location": "le lieu",
    },
}

# What is appended when the question carries no demonstrative to replace ("cast", "trivia").
#
# **Not a word of "image" or "picture" in here, and that is measured rather than tasteful.**
# The first wording was "the image shows {phrase}", and on 2026-09-20 the question "Movie?"
# came out as "Movie? (the image shows the movie The Big Sleep (1946))", which the
# answer-entity classifier read as a request for pictures OF a movie: it returned
# `movie_image` and the client got 50 posters instead of the film. The suffix had invented the
# very word the classifier keys on. "about" says the same thing and says nothing else.
#
# The French form avoids "a propos de" and "au sujet de" on purpose: both would have to
# contract in front of "le film", and the phrase is built elsewhere.
_VISION_SUBJECT_SUFFIX = {
    "en": "about {phrase}",
    "fr": "concernant {phrase}",
}

# A question that asks about the PIXELS, which no catalogue can answer: the tagline printed on
# a poster, the edition of a Blu-ray, whether the image is a poster or a frame. This list is a
# *may-call* gate and nothing more: when it fires the vision model is called even if the image
# is already in the recognition cache, because the answer depends on the question and the cache
# holds only the identification. When it does not fire and the model is called anyway (a cache
# miss), the model still has the final word through `about_image`. So a marker missing from
# this list costs one cached turn, never a wrong answer.
_VISION_IMAGE_QUESTION_MARKERS = (
    # English
    "poster", "cover", "sleeve", "jacket", "artwork", "blu-ray", "bluray", "dvd",
    "edition", "written", "writing", "tagline", "caption", "font", "typography",
    "logo", "colour of", "color of", "background", "screenshot",
    "in this image", "in this picture", "in this photo", "on this image",
    "what does it say", "what is written",
    # French
    "affiche", "jaquette", "pochette", "boitier", "couverture", "edition", "accroche",
    "police de caractere", "typographie", "couleur de", "arriere-plan", "capture",
    "photogramme", "sur cette image", "sur cette photo", "ecrit sur",
    "qu'est-ce qui est ecrit", "qu'y a-t-il d'ecrit",
)

# The demonstrative phrases a user actually types in front of a photo. The first match is
# replaced by the identified entity, which is the whole of "substituting the resolved entity
# into the user's question": "who directed this film?" becomes "who directed the movie Blade
# Runner (1982)?", keeping the interrogative form the catalogue needs (FASTAPI-TEXT2SQL-263).
_VISION_DEMONSTRATIVE_RE = re.compile(
    r"\b("
    r"(?:this|that|the)\s+(?:movie|film|picture|serie|series|show|tv\s+show|poster|image|photo|"
    r"person|actor|actress|director|character)"
    r"|(?:ce|cet|cette)\s+(?:film|long[-\s]m[eé]trage|s[eé]rie|affiche|image|photo|"
    r"personne|acteur|actrice|r[eé]alisateur|r[eé]alisatrice|personnage)"
    r"|celui[-\s]ci|celle[-\s]ci|ceux[-\s]ci|celles[-\s]ci"
    r")\b",
    re.IGNORECASE,
)

# The bare pronoun, handled apart because it must only fire when it stands alone at the end of
# a clause: "who directed this?" is a reference to the photo, "this movie" is already covered
# above, and "it is a comedy" is not a reference at all.
_VISION_PRONOUN_RE = re.compile(r"\b(this|it|ca|ça)\b(?=\s*[?!.,]|\s*$)", re.IGNORECASE)


# Which language the user actually wrote in, read off the demonstrative that matched rather
# than off `ui_language` (FASTAPI-TEXT2SQL-114). Measured on 2026-09-20: tmdb-front sends
# `ui_language=en` whatever the typed language, so "De quel film vient cette image ?" came back
# as "De quel film vient the movie The Shining (1980) ?", a sentence nobody wrote. The
# demonstrative that was replaced is the one piece of evidence available about the language of
# the QUESTION, and it costs nothing to read: a French alternative can only have matched French
# words. `ui_language` stays the fallback, for a question with no demonstrative at all.
_VISION_FRENCH_MATCH_RE = re.compile(
    r"^(?:ce|cet|cette|ces|celui|celle|ceux|celles|ça|ca)\b", re.IGNORECASE)


def _phrase_language(matched_text: str, ui_language: str) -> str:
    """Language to phrase the injected entity in: the question's own, else the UI's."""
    if matched_text and _VISION_FRENCH_MATCH_RE.match(matched_text.strip()):
        return "fr"
    if matched_text:
        return "en"
    return str(ui_language or "en").strip().lower()


# A question asking WHO IS IN THE PICTURE, which the faces answer better than a cast list
# (FASTAPI-TEXT2SQL-281). Measured on 2026-09-20: "who are the actors on this picture?" returned
# the 32 names of The Big Sleep, with Dorothy Malone at rank 11, while the vision model had read
# and named both visible faces. The names were in the response all along, in `hints.faces`, and
# thrown away.
_VISION_PERSON_QUESTION_MARKERS = (
    # English
    "who is this", "who is that", "who is he", "who is she", "who is the actor",
    "who is the actress", "who is the person", "who's this", "who's that", "who is it",
    "who are these", "who are those", "who are they", "who are the actors",
    "who are the actresses", "who are the people", "name the actors", "name these actors",
    "which actor", "which actress", "identify the actor", "identify the person",
    # French
    "qui est cet", "qui est cette", "qui est ce ", "qui est l'acteur", "qui est l'actrice",
    "qui est la personne", "c'est qui", "qui sont ces", "qui sont ils", "qui sont-ils",
    "qui sont les acteurs", "qui sont les actrices", "quel acteur", "quelle actrice",
)

# ... unless the question names a ROLE, in which case it asks about someone who is very
# probably not in the frame. "who directed this?" carries "who" and must never be answered by
# the faces: that person is found in the catalogue, from the work.
#
# Each entry is deliberately a WHOLE role word and not a stem. "film" was in the first draft
# and it would have disabled the feature in French on its own: "qui sont les acteurs de ce
# film ?" contains it, so every French person question would have fallen back to the cast, the
# exact behaviour this ticket exists to stop. Same reasoning removed "edit" (edition), "shot"
# and "score".
_VISION_ROLE_VERBS = (
    "directed", "director", "wrote", "writer", "written", "screenplay", "screenwriter",
    "produced", "producer", "composed", "composer", "music by", "score by", "filmed by",
    "edited by", "editor", "cinematograph",
    "realis", "r\u00e9alis", "sc\u00e9nariste", "scenariste", "sc\u00e9nario", "scenario",
    "\u00e9crit par", "ecrit par", "produit par", "producteur", "compositeur", "musique de",
    "monteur", "chef op\u00e9rateur", "chef operateur",
)


def question_targets_the_people_shown(user_question) -> bool:
    """True when the question asks who the people IN the image are.

    FASTAPI-TEXT2SQL-281, arbitrage of 2026-09-20 (option 1): when the model has read faces,
    such a question is answered by those faces rather than by the work's whole cast. Two
    conditions, and the second is what keeps it safe: a person-identity marker, and no role
    verb. "Who directed this?" carries "who" and is not about the visible people, so composing
    from the faces there would answer confidently and wrongly.

    Flattening an identity question into entity cards is NOT the -263 defect: -263 is about a
    question asking for a RELATION being replaced by a card. "Who is this?" asks for the card.
    """
    q = str(user_question or "").strip().lower()
    if not q:
        return False
    if any(verb in q for verb in _VISION_ROLE_VERBS):
        return False
    return any(marker in q for marker in _VISION_PERSON_QUESTION_MARKERS)


def question_targets_the_image(user_question) -> bool:
    """True when the question asks about the image itself rather than about the work.

    See ``_VISION_IMAGE_QUESTION_MARKERS``: this is a gate that decides whether the vision
    model MAY be called again on an image already recognised, never a verdict. The model
    itself answers that question, through ``about_image``, whenever it is called.
    """
    q = str(user_question or "").strip().lower()
    if not q:
        return False
    return any(marker in q for marker in _VISION_IMAGE_QUESTION_MARKERS)


def _normalize_vision_items(payload) -> list:
    """Return the payload's candidates as clean dicts, best first.

    Ranked on ``confidence`` with a stable sort, so the model's own order survives ties and
    a payload that omits confidence entirely keeps the order it was written in.
    """
    try:
        items = payload.get("items") if isinstance(payload, dict) else None
    except Exception:
        items = None
    if not isinstance(items, list):
        return []
    cleaned = []
    for it in items:
        if not isinstance(it, dict):
            continue
        value = str(it.get("value") or "").strip()
        if value == "":
            continue
        item_type = str(it.get("type") or "").strip().lower()
        if item_type not in _VISION_ITEM_TYPES:
            item_type = "other"
        year = str(it.get("year") or "").strip()
        if not re.fullmatch(r"\d{4}", year or ""):
            year = ""
        try:
            confidence = float(it.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        raw_evidence = it.get("evidence")
        evidence = ([str(e).strip() for e in raw_evidence if str(e).strip()]
                    if isinstance(raw_evidence, list) else [])
        cleaned.append({
            "type": item_type,
            "value": value,
            "year": year,
            "note": str(it.get("note") or "").strip(),
            "confidence": confidence,
            "evidence": evidence,
        })
    # No cap here: the cap is applied per KIND by select_vision_candidates, because a single
    # cap over a confidence-sorted list lets recognised faces evict the work
    # (FASTAPI-TEXT2SQL-281).
    cleaned.sort(key=lambda c: -c["confidence"])
    return cleaned


def select_vision_candidates(payload) -> dict:
    """Decide whether one candidate dominates, or whether they all have to be presented.

    Returns ``{"ranked": [...], "selected": item|None, "alternatives": [...],
    "dominant": bool}``. ``dominant`` is what tells the caller to compose the question from
    ONE candidate; otherwise the question lists them all and the ordinary same-name-cluster
    machinery (``name_ambiguity``) lets the client ask which one is meant.

    A single candidate is dominant by construction: there is nothing to be ambiguous with,
    and its own confidence is reported rather than used as a floor. Refusing it below a
    threshold would turn "one uncertain reading" into "no reading at all", which loses the
    evidence the user is entitled to see.
    """
    ranked = _normalize_vision_items(payload)
    # Works and people are capped SEPARATELY (FASTAPI-TEXT2SQL-281). A single cap over a list
    # sorted by confidence would let five recognised faces push the film out of a five-slot
    # list, and the photo would then be answered as if it showed nobody's film.
    works = [c for c in ranked if c["type"] != "person"][:VISION_MAX_CANDIDATES]
    people = [c for c in ranked if c["type"] == "person"][:VISION_MAX_CANDIDATES]
    # What the response reports is the union of the two capped lists, so `candidates` never
    # holds an item the composer could not have used.
    ranked = sorted(works + people, key=lambda c: -c["confidence"])
    # What a question about the SUBJECT is answered from: the work when there is one, the
    # people when the image shows no work at all (a portrait), which is the case that had no
    # answer before this ticket.
    pool = works or people
    if not pool:
        return {"ranked": ranked, "works": works, "people": people,
                "selected": None, "alternatives": [], "dominant": False}
    top = pool[0]
    if len(pool) == 1:
        return {"ranked": ranked, "works": works, "people": people,
                "selected": top, "alternatives": [], "dominant": True}
    runner_up = pool[1]
    dominant = (
        top["confidence"] >= VISION_CONFIDENCE_DOMINANT
        and (top["confidence"] - runner_up["confidence"]) >= VISION_CONFIDENCE_MARGIN
    )
    return {
        "ranked": ranked,
        "works": works,
        "people": people,
        "selected": top,
        "alternatives": pool[1:],
        "dominant": dominant,
    }


def vision_entity_phrase(item, ui_language: str = "en") -> str:
    """Phrase one identified candidate as it reads inside a sentence.

    ``{"type": "movie", "value": "Blade Runner", "year": "1982"}`` becomes
    ``the movie Blade Runner (1982)``, or ``le film Blade Runner (1982)`` in French.
    """
    if not isinstance(item, dict):
        return ""
    value = str(item.get("value") or "").strip()
    if value == "":
        return ""
    year = str(item.get("year") or "").strip()
    table = _VISION_TYPE_PHRASE.get(str(ui_language or "en").strip().lower(),
                                    _VISION_TYPE_PHRASE["en"])
    phrase = table.get(str(item.get("type") or "").strip().lower(), "")
    if re.fullmatch(r"\d{4}", year or ""):
        value = f"{value} ({year})"
    return f"{phrase} {value}".strip()


def compose_vision_question(payload, user_question: str = "", ui_language: str = "en") -> str:
    """Turn an identification into the question the rest of the pipeline will answer.

    Two shapes, one per case of the ticket:

    - **Photo alone.** ``f_build_retry_question_from_reasoning`` composes the canonical
      identity question, exactly as it does for the complex-question retry: ``Movie Blade
      Runner released in 1982``, or a list when several candidates are close.
    - **Photo plus a question.** The user's own question is kept and the identified entity is
      substituted into it, so ``who directed this film?`` becomes ``who directed the movie
      Blade Runner (1982)?``. Flattening it into a bare entity card would return the film and
      answer nothing, which is the defect recorded as FASTAPI-TEXT2SQL-263.

    With several close candidates AND a user question, the best candidate is substituted: a
    relation question needs one subject. The alternatives are not lost, they travel in
    ``vision_evidence`` and the client can re-ask on another one.

    Returns "" when nothing was identified; the caller then treats the turn as an
    authoritative empty rather than searching for the user's raw words.
    """
    selection = select_vision_candidates(payload)
    ranked = selection["ranked"]
    if not ranked:
        return ""

    question = str(user_question or "").strip()

    # FASTAPI-TEXT2SQL-281, option 1. "Who are the actors on this picture?" is answered by the
    # faces the model read, not by the work's cast: the user pointed at two people and the cast
    # buried them among thirty-two. When no face was read, this does not fire and the question
    # falls through to the work, which is the pre-existing behaviour.
    if question and selection["people"] and question_targets_the_people_shown(question):
        return f_build_retry_question_from_reasoning(
            {"question": "", "items": selection["people"]})

    if question == "":
        items = [selection["selected"]] if selection["dominant"] else (selection["works"] or ranked)
        return f_build_retry_question_from_reasoning({"question": "", "items": items})

    # The demonstrative is located BEFORE the phrase is built, because the language it is
    # written in decides the language the phrase is written in.
    match = _VISION_DEMONSTRATIVE_RE.search(question) or _VISION_PRONOUN_RE.search(question)
    langue = _phrase_language(match.group(0) if match else "", ui_language)
    phrase = vision_entity_phrase(selection["selected"], langue)
    if phrase == "":
        return question

    if match:
        substituted = question[:match.start()] + phrase + question[match.end():]
    else:
        # No demonstrative to replace ("cast", "trivia", "awards"). Naming the subject beside
        # the question is the honest composition: it adds what the photo carried and removes
        # nothing of what was typed.
        suffix = _VISION_SUBJECT_SUFFIX.get(langue, _VISION_SUBJECT_SUFFIX["en"])
        substituted = f"{question} ({suffix.format(phrase=phrase)})"
    return substituted.strip()


# The strict schema is the primary path: the OpenAI documentation shows `response_format`
# json_schema and `reasoning_effort` together on chat.completions, which is exactly this call.
# The fallback below exists anyway, for two reasons and not out of superstition. AGENTS.md
# records a neighbouring refusal (function tools combined with `reasoning_effort` on
# gpt-5.6-sol), and this repository has never exercised structured outputs against the live
# API, so the first request of the first deployment is where a surprise would land. On a
# refusal this flag flips and every later call of the process goes straight to the plain-JSON
# contract the other five tasks use, cleaned and validated the same way. Same degrade-once
# idiom as sql_cache._RESULT_ENTITY_COLUMN_AVAILABLE.
_VISION_STRUCTURED_OUTPUTS_AVAILABLE = True

# The contract, as a strict JSON schema. Strict mode demands that every property be listed in
# `required` and that every object refuse additional properties, so an optional field is
# expressed as a field the model must emit empty, never as an absent one.
_VISION_RESPONSE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["hints", "items", "about_image", "image_answer",
                 "authoritative_empty", "justification", "error"],
    "properties": {
        "hints": {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "title_text", "credits_block", "faces",
                         "era_cues", "genre_cues", "text_language"],
            "properties": {
                "kind": {"type": "string",
                         "enum": ["poster", "frame", "still", "physical_media", "other"]},
                "title_text": {"type": "string"},
                "credits_block": {"type": "string"},
                "faces": {"type": "array", "items": {"type": "string"}},
                "era_cues": {"type": "array", "items": {"type": "string"}},
                "genre_cues": {"type": "array", "items": {"type": "string"}},
                "text_language": {"type": "string"},
            },
        },
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["type", "value", "year", "note", "confidence", "evidence"],
                "properties": {
                    "type": {"type": "string", "enum": list(_VISION_ITEM_TYPES)},
                    "value": {"type": "string"},
                    "year": {"type": "string"},
                    "note": {"type": "string"},
                    "confidence": {"type": "number"},
                    "evidence": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "about_image": {"type": "boolean"},
        "image_answer": {"type": "string"},
        "authoritative_empty": {"type": "boolean"},
        "justification": {"type": "string"},
        "error": {"type": "string"},
    },
}


def _is_structured_outputs_refusal(exc: Exception) -> bool:
    """True when this failure is the provider refusing the strict schema, and only then.

    The distinction is load-bearing. Flipping `_VISION_STRUCTURED_OUTPUTS_AVAILABLE` on any
    exception would let a rate limit, a timeout or a network blip disable structured outputs
    for the whole life of the process, and nothing would ever turn them back on. A refusal is
    a 400 that names the parameter; everything else is re-raised and surfaces to the caller
    like any other provider failure, which is what keeps a 429 retryable for the client.
    """
    status = getattr(exc, "status_code", None)
    if status is not None and status != 400:
        return False
    text = str(exc).lower()
    return any(marker in text for marker in (
        "response_format", "json_schema", "structured output",
        "unsupported parameter", "unsupported value",
    ))


def _call_vision_llm(*, model: str, system_prompt: str, user_prompt: str,
                     imagebytes: bytes, media_type: str,
                     cache_label: str = "vision_identification") -> str:
    """Call a vision-capable LLM with one image and return its raw text content.

    Deliberately NOT folded into ``_call_chat_llm``: that dispatcher takes a string prompt and
    every provider encodes an image differently, so merging them would put three content
    builders behind one signature for the benefit of one caller.

    **OpenAI only, and the error says so.** `gpt-4o` and the GPT-5.x / GPT-6 families read
    images through `chat.completions` with an `image_url` content block, which is the route
    this function implements; the o-series would need the Responses API and is not wired.
    Anthropic and Gemini both accept images and neither is wired either: an unexercised branch
    that formats bytes for a provider nobody has tested against is a liability, not a feature.
    Adding one is a small, explicit job, not an accident to have in advance.
    """
    global _VISION_STRUCTURED_OUTPUTS_AVAILABLE
    model_norm = str(model).strip()
    if not (model_norm.startswith("gpt-") or model_norm.startswith("chatgpt-")):
        raise RuntimeError(
            f"Unsupported vision model: {model_norm}. The vision task reads images through the "
            "OpenAI chat.completions route only (gpt-4o, gpt-5.x, gpt-6-astra). "
            "Anthropic and Gemini vision are not wired in this repository."
        )
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not found in environment variables")

    user_prompt_plain = user_prompt.replace(CACHE_BOUNDARY_MARKER, "")
    data_url = f"data:{media_type};base64,{base64.b64encode(imagebytes).decode('ascii')}"
    client = openai.OpenAI(api_key=api_key)
    sampling_kwargs = _openai_sampling_kwargs(model_norm, 0, cache_label)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": [
            {"type": "text", "text": user_prompt_plain},
            {"type": "image_url", "image_url": {"url": data_url, "detail": VISION_IMAGE_DETAIL}},
        ]},
    ]

    if _VISION_STRUCTURED_OUTPUTS_AVAILABLE:
        try:
            response = client.chat.completions.create(
                model=model_norm,
                messages=messages,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": "vision_identification",
                        "strict": True,
                        "schema": _VISION_RESPONSE_SCHEMA,
                    },
                },
                **sampling_kwargs,
            )
            _log_openai_cache_usage(response, model_norm=model_norm, label=cache_label)
            if (response.choices and response.choices[0].message
                    and response.choices[0].message.content):
                return response.choices[0].message.content
            raise RuntimeError("No content in OpenAI API response")
        except RuntimeError:
            raise
        except Exception as structured_error:
            if not _is_structured_outputs_refusal(structured_error):
                raise
            _VISION_STRUCTURED_OUTPUTS_AVAILABLE = False
            print(f"[vision] Structured outputs refused ({structured_error}); falling back to "
                  "the plain-JSON contract for the rest of this process.")

    response = client.chat.completions.create(
        model=model_norm,
        messages=messages,
        **sampling_kwargs,
    )
    _log_openai_cache_usage(response, model_norm=model_norm, label=cache_label)
    if not response.choices or not response.choices[0].message or not response.choices[0].message.content:
        raise RuntimeError("No content in OpenAI API response")
    return response.choices[0].message.content


def f_identify_from_image(imagebytes: bytes, media_type: str, user_question: str = "",
                          strvisionmodel: str = "default", ui_language: str = "en"):
    """Read an image and return what it points at, in the ``items[]`` contract.

    Args:
        imagebytes: The deposited image, read back from ``uploads/vision/``.
        media_type: Its media type, decided by the magic number at deposit time.
        user_question: What the user asked alongside the photo, "" when the photo is alone.
            It is passed to the model for ONE purpose, deciding ``about_image`` and answering
            it; the identification itself does not depend on it, which is what makes the
            recognition cache sound.
        strvisionmodel: Model override; "default" resolves to ``strvisionmodeldefault``.
        ui_language: Language of ``image_answer``, the only user-facing string here.

    Returns:
        dict: the parsed contract (``hints``, ``items``, ``about_image``, ``image_answer``,
        ``authoritative_empty``, ``justification``), or ``{"error": ...}``. Never raises:
        a vision failure degrades to a turn the user can retype, not to a 500.
    """
    model_to_use = _normalize_llm_model(strvisionmodel, strvisionmodeldefault)
    print("Vision identification LLM model:", model_to_use)

    try:
        question_for_prompt = str(user_question or "").strip()
        if question_for_prompt == "":
            question_for_prompt = "(none: the user sent the photo alone, with no question)"
        formatted_prompt = vision_identification_prompt_template.replace(
            "{user_question}", question_for_prompt)
        formatted_prompt = formatted_prompt.replace("{ui_language}", ui_language or "en")

        json_content = _call_vision_llm(
            model=model_to_use,
            system_prompt=("You are a film and television image reader. Respond only with the "
                           "JSON content, no explanations."),
            user_prompt=formatted_prompt,
            imagebytes=imagebytes,
            media_type=media_type,
        ).strip()
    except Exception as e:
        print(f"Error in vision identification: {str(e)}")
        return {"error": f"Vision identification failed: {str(e)}"}

    if json_content.startswith("```json"):
        json_content = json_content[7:].strip()
    if json_content.startswith("```"):
        json_content = json_content[3:].strip()
    if json_content.endswith("```"):
        json_content = json_content[:-3].strip()

    cleaned_content = json_content.strip()
    if not cleaned_content.startswith('{') or not cleaned_content.endswith('}'):
        return {"error": "Incomplete JSON response from the vision model",
                "raw_content": json_content}

    try:
        parsed = json.loads(cleaned_content)
    except json.JSONDecodeError as json_error:
        print(f"JSON parsing error in vision identification: {str(json_error)}")
        return {"error": f"JSON parsing failed: {str(json_error)}", "raw_content": json_content}

    ok, guard_error = json_guardrails.validate_llm_json(parsed, "vision_identification")
    if not ok:
        print(f"JSON guardrail failed in vision identification: {guard_error}")
        return {"error": f"JSON guardrail: {guard_error}", "raw_content": json_content}
    return parsed
