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
# - allowed_values:  closed values for keys whose vocabulary is part of the contract
# Unlisted keys are allowed (e.g. dynamic entity-extraction placeholder keys).
_SCHEMAS = {
    # f_entity_extraction -> {"question": "...anonymized...", "<Placeholder>": "...", ...}
    # FASTAPI-TEXT2SQL-255: `query_mode` is deliberately NOT required. A missing one only loses
    # the `descriptive_identification` routing; requiring it failed usable extractions and handed
    # Text2SQL the raw, non-anonymized question. A value outside the vocabulary stays rejected.
    "entity_extraction": {
        "required": {"question": str},
        "types": {"question": str, "query_mode": str, "error": str, "raw_content": str},
        "allowed_values": {
            "query_mode": {
                "named_entity_query", "descriptive_identification", "ordinary_filter_query",
            },
        },
    },
    # f_text2sql -> {"result_entity"?, "sql_query"|"error"|"requires_complex_resolution",
    #                "justification"?, "answer"?, "dropped_clause"?}
    # dropped_clause (FASTAPI-TEXT2SQL-220) is advisory prose, typed like justification; an older
    # model that omits it stays valid.
    "text2sql": {
        "any_of_required": ["sql_query", "error", "requires_complex_resolution"],
        "types": {
            "result_entity": str, "sql_query": str, "justification": str,
            "answer": str, "dropped_clause": str, "error": str, "raw_content": str,
            "requires_complex_resolution": bool,
        },
    },
    # f_resolve_complex_question ->
    #   {"question"|"error"|"authoritative_empty", "justification"?, "answer"?}
    # FASTAPI-TEXT2SQL-221: an authoritative empty is an answer, so it gets its own field.
    # The prompt used to signal it with an empty question, items and error, which this gate
    # rejects: measured 2026-08-28, 13 of 17 complex retries died on that shape.
    # Do not loosen any_of_required to accept three empty fields instead: that would admit
    # a genuinely empty output, indistinguishable from a model failure, which is what this
    # guardrail exists to catch.
    "complex_question": {
        "any_of_required": ["question", "error", "authoritative_empty"],
        "types": {
            "question": str, "justification": str, "answer": str,
            "error": str, "raw_content": str, "authoritative_empty": bool,
            # FASTAPI-TEXT2SQL-355: `known_credits` is deliberately NOT typed here. It only
            # helps choose among namesakes; a malformed block must cost that choice, never the
            # whole rewrite. text2sql._normalize_known_credits cleans it defensively.
        },
    },
    # f_identify_from_image -> {"hints": {...}, "items": [...], "about_image", "image_answer",
    #                           "authoritative_empty", "justification", "error"}
    # FASTAPI-TEXT2SQL-114. An empty `items` list does NOT satisfy the gate: an image that
    # identifies nothing must say so through `authoritative_empty`, as on complex_question:
    # a silence meant as an answer reads as a malformed output.
    # The per-item shape is deliberately not validated here: the provider's strict json_schema
    # and `_normalize_vision_items` already cover it, and a third copy would drift.
    "vision_identification": {
        "any_of_required": ["items", "image_answer", "authoritative_empty", "error"],
        "types": {
            "hints": dict, "items": list, "about_image": bool, "image_answer": str,
            "authoritative_empty": bool, "justification": str,
            "error": str, "raw_content": str,
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

    if isinstance(payload.get("error"), str) and payload.get("error").strip():
        return True, ""

    for key, typ in schema.get("required", {}).items():
        if key not in payload:
            return False, f"{step}: missing required key '{key}'"
        if not isinstance(payload[key], typ):
            return False, f"{step}: key '{key}' must be {typ.__name__}, got {type(payload[key]).__name__}"

    any_of = schema.get("any_of_required")
    # Truthiness, not a test against (None, ""): `authoritative_empty`, a boolean, sits in these lists, and
    # `authoritative_empty: false` with everything else empty would otherwise pass the gate.
    if any_of and not any(k in payload and bool(payload[k]) for k in any_of):
        return False, f"{step}: at least one of {any_of} must be present and non-empty"

    types = schema.get("types", {})
    for key, expected in types.items():
        if key in payload and payload[key] is not None and not isinstance(payload[key], expected):
            return False, f"{step}: key '{key}' must be {expected.__name__}, got {type(payload[key]).__name__}"

    for key, allowed in schema.get("allowed_values", {}).items():
        if key in payload and payload[key] not in allowed:
            return False, f"{step}: key '{key}' must be one of {sorted(allowed)}, got {payload[key]!r}"

    return True, ""
