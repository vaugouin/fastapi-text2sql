#!/usr/bin/env python3
"""Offline regression checks for FASTAPI-TEXT2SQL-250 through -255."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))

import entity  # noqa: E402
import json_guardrails  # noqa: E402
from entity_extraction_eval_functions import ee_eval_two_layer  # noqa: E402


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

    extraction = {
        "question": "popular movies released in 1973",
        "query_mode": "ordinary_filter_query",
    }
    assert entity.extracted_entity_items(extraction) == []
    assert ee_eval_two_layer(
        extraction,
        'eq($.query_mode, "ordinary_filter_query") AND seteq(entity_keys($), [])',
    )

    print("entity inference boundary: all checks passed")


if __name__ == "__main__":
    main()
