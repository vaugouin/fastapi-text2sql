#!/usr/bin/env python3
"""Offline regression checks for FASTAPI-TEXT2SQL-250 through -256."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import importlib.util  # noqa: E402

import entity  # noqa: E402
import json_guardrails  # noqa: E402
from entity_extraction_eval_functions import ee_eval_two_layer  # noqa: E402


def _load_retry_analyzer():
    """Import analyze-complex-retry-logs.py, whose hyphenated name blocks a plain import."""
    spec = importlib.util.spec_from_file_location(
        "analyze_complex_retry_logs", ROOT / "analyze-complex-retry-logs.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOVIE_SQL = "SELECT ID_MOVIE FROM T_WC_T2S_MOVIE WHERE MOVIE_TITLE = '{}'"


def main() -> None:
    ok, error = json_guardrails.validate_llm_json(
        {"question": "popular movies released in 1973", "query_mode": "ordinary_filter_query"},
        "entity_extraction",
    )
    assert ok, error

    ok, error = json_guardrails.validate_llm_json(
        {"question": "clues", "query_mode": "invented_mode"},
        "entity_extraction",
    )
    assert not ok and "query_mode" in error

    # FASTAPI-TEXT2SQL-255. A missing query_mode costs the descriptive routing, not the
    # extraction: the payload stays usable and must pass. Rejecting it sent the pipeline
    # down the fallback branch with the raw, non-anonymized question.
    ok, error = json_guardrails.validate_llm_json(
        {"question": "tell me about {{Movie_title1}}", "Movie_title1": "Blow-Up"},
        "entity_extraction",
    )
    assert ok, error

    # A present-but-wrong query_mode is still a contract breach, by value and by type.
    ok, error = json_guardrails.validate_llm_json(
        {"question": "clues", "query_mode": 3}, "entity_extraction",
    )
    assert not ok and "query_mode" in error

    ok, error = json_guardrails.validate_llm_json(
        {"requires_complex_resolution": True}, "text2sql",
    )
    assert ok, error

    assert entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("The Conversation"),
        "a surveillance expert records a couple and fears they will be killed",
        {"question": "a surveillance expert records a couple", "query_mode": "descriptive_identification"},
    )
    assert entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("The Apartment"),
        "a man lends his flat to his boss for his affairs and his boss dates the woman he has a crush on",
        {"question": "a man lends his flat to his boss", "query_mode": "descriptive_identification"},
    )
    assert not entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("Pour le plaisir"),
        "Pour le plaisir",
        {"question": "Pour le plaisir", "query_mode": "ordinary_filter_query"},
    )
    assert not entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("The Conversasion"),
        "tell me about The Conversasion",
        {
            "question": "tell me about {{Movie_title1}}",
            "query_mode": "named_entity_query",
            "Movie_title1": "The Conversasion",
        },
    )

    # FASTAPI-TEXT2SQL-259. Surface form must not decide provenance. The canonical title
    # carries a colon the user never typed; on an exact-question cache hit the SQL comes back
    # already resolved to that canonical value, with no extraction to fall back on, and the
    # guard was rejecting the pipeline's own stored SQL.
    assert not entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("2001: A Space Odyssey"),
        "What are the narrative locations of the movie 2001 A space odyssey?",
        None,
    )
    assert not entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("Amelie"),
        "tell me about Amélie",
        None,
    )
    assert not entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("Blow-Up"),
        "who directed Blow Up",
        None,
    )
    # Folding punctuation must not fold words: an inferred title still shares none.
    assert entity.find_unbacked_entity_literals(
        MOVIE_SQL.format("2001: A Space Odyssey"),
        "a computer kills the crew of a mission to Jupiter",
        None,
    )

    # The routing decision itself lives inside the request handler, which needs a database and
    # cannot run offline. Assert the gate at the source level instead: without it the guard
    # runs on cache-hit SQL, where no extraction exists to ground a canonical literal.
    main_source = (ROOT / "main.py").read_text(encoding="utf-8")
    assert "entity.find_unbacked_entity_literals(" in main_source, (
        "the provenance guard call disappeared from main.py"
    )
    guard_condition = next(
        (line for line in main_source.splitlines()
         if line.strip().startswith("if sql_query and not requires_complex_resolution")),
        None,
    )
    assert guard_condition is not None, "the provenance guard condition disappeared from main.py"
    assert "not cached_exact_question" in guard_condition, (
        "the provenance guard must skip exact-question cache hits (FASTAPI-TEXT2SQL-259)"
    )

    extraction = {
        "question": "popular movies released in 1973",
        "query_mode": "ordinary_filter_query",
    }
    assert entity.extracted_entity_items(extraction) == []
    assert ee_eval_two_layer(
        extraction,
        'eq($.query_mode, "ordinary_filter_query") AND seteq(entity_keys($), [])',
    )

    # FASTAPI-TEXT2SQL-256. query_mode is extraction metadata, not an extracted entity.
    # Counting it as one makes the NOTHING_EXTRACTED bucket of the retry report unreachable,
    # which is invisible in the output: the bucket just reads zero forever.
    analyzer = _load_retry_analyzer()
    assert analyzer.classify(
        {"entity_extraction": {"question": "clues", "query_mode": "descriptive_identification"}}
    ) == "NOTHING_EXTRACTED"
    assert analyzer.classify(
        {"entity_extraction": {
            "question": "tell me about {{Movie_title1}}",
            "query_mode": "named_entity_query",
            "Movie_title1": "The Conversasion",
        }}
    ) != "NOTHING_EXTRACTED"

    print("entity inference boundary: all checks passed")


if __name__ == "__main__":
    main()
