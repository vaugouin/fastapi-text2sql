"""JSON guardrails for LLM step outputs (FASTAPI-TEXT2SQL-038).

Provider-agnostic, dependency-free schema validation of the JSON each LLM step of
the workflow returns. A malformed structure (e.g. from a weaker model like Haiku)
is caught at the step boundary and surfaced as a normal `{"error": ...}` payload —
which the pipeline already handles (ambiguous flag / stronger-model retry) — instead
of propagating a bad shape that crashes a downstream step.

Why not the OpenAI Agent SDK Guardrails (as the backlog suggested)? The stack is
multi-provider (OpenAI, Anthropic, Gemini, OpenRouter via `_call_chat_llm`), so an
OpenAI-only guardrail layer doesn't fit. This tiny validator is provider-agnostic
and adds no dependency.

Each step's *output* schema is also the *input* contract of the next step, so
validating every step's output once gives input+output coverage across the workflow
without redundant re-validation.

Usage:
    ok, err = validate_llm_json(payload, "text2sql")
    if not ok:
        return {"error": f"JSON guardrail: {err}", "raw_content": ...}
"""
from typing import Any, Tuple

# Declarative mini-schemas, one per workflow step that returns LLM JSON.
# - required:        keys that must be present, mapped to their required type
# - any_of_required: at least one of these keys must be present and non-empty
# - types:           type checks applied only to these keys when present
# Unlisted keys are allowed (e.g. dynamic entity-extraction placeholder keys).
_SCHEMAS = {
    # f_entity_extraction -> {"question": "...anonymized...", "<Placeholder>": "...", ...}
    "entity_extraction": {
        "required": {"question": str},
        "types": {"question": str, "error": str, "raw_content": str},
    },
    # f_text2sql -> {"result_entity"?, "sql_query"|"error", "justification"?, "answer"?,
    #                "dropped_clause"?}
    # dropped_clause (FASTAPI-TEXT2SQL-220) names the part of the question the SQL does not
    # implement, and is empty when it implements all of it. Typed like justification and answer
    # because it is advisory prose; unlisted keys are allowed, so an older model that omits it
    # stays valid.
    "text2sql": {
        "any_of_required": ["sql_query", "error"],
        "types": {
            "result_entity": str, "sql_query": str, "justification": str,
            "answer": str, "dropped_clause": str, "error": str, "raw_content": str,
        },
    },
    # f_resolve_complex_question ->
    #   {"question"|"error"|"authoritative_empty", "justification"?, "answer"?}
    #
    # FASTAPI-TEXT2SQL-221. `authoritative_empty` exists because the prompt asked the
    # model to say something by staying silent, and this guardrail refused the silence.
    # The rule at data/complex_question.md:75 prescribed an empty "question", empty
    # "items" and empty "error" to mean "the database result is authoritative", a shape
    # `any_of_required` rejects by construction. Every correct application of that
    # branch was therefore recorded as a malformed output and the retry was abandoned.
    # Measured on 18 097 calls, 2026-08-28: 13 of the 17 complex retries on 1.1.18, the
    # live version, died here, and that version produced zero usable conclusions.
    #
    # Loosening `any_of_required` to accept three empty fields was the tempting fix and
    # the wrong one: it would admit a genuinely empty output, indistinguishable from a
    # model failure, which is precisely what -038 built this guardrail to catch. An
    # authoritative empty is not an absence of answer, it is an affirmative one, so it
    # gets a field and says so.
    "complex_question": {
        "any_of_required": ["question", "error", "authoritative_empty"],
        "types": {
            "question": str, "justification": str, "answer": str,
            "error": str, "raw_content": str, "authoritative_empty": bool,
        },
    },
}


def validate_llm_json(payload: Any, step: str) -> Tuple[bool, str]:
    """Validate an LLM step's parsed JSON against its schema.

    Returns (ok, error_message). Fails open (ok=True) for unknown steps so callers
    can guard new steps incrementally. An explicit non-empty {"error": ...} payload
    is always accepted — it is a handled failure, not a malformed shape.
    """
    schema = _SCHEMAS.get(step)
    if schema is None:
        return True, ""

    if not isinstance(payload, dict):
        return False, f"{step}: expected a JSON object, got {type(payload).__name__}"

    # A surfaced error is a valid, already-handled outcome.
    if isinstance(payload.get("error"), str) and payload.get("error").strip():
        return True, ""

    for key, typ in schema.get("required", {}).items():
        if key not in payload:
            return False, f"{step}: missing required key '{key}'"
        if not isinstance(payload[key], typ):
            return False, f"{step}: key '{key}' must be {typ.__name__}, got {type(payload[key]).__name__}"

    any_of = schema.get("any_of_required")
    # Truthiness rather than a membership test against (None, ""), because a boolean
    # key joined this list with -221 and `False not in (None, "")` is True: a model
    # returning `authoritative_empty: false` alongside an empty question and an empty
    # error would have satisfied the gate, which is the exact hole this guardrail
    # exists to close. Equivalent for every string field already listed, where "" is
    # falsy and any other value truthy, so no existing schema changes behaviour.
    if any_of and not any(k in payload and bool(payload[k]) for k in any_of):
        return False, f"{step}: at least one of {any_of} must be present and non-empty"

    types = schema.get("types", {})
    for key, expected in types.items():
        if key in payload and payload[key] is not None and not isinstance(payload[key], expected):
            return False, f"{step}: key '{key}' must be {expected.__name__}, got {type(payload[key]).__name__}"

    return True, ""
