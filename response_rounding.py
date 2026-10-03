"""Round the numbers of an API response at serialization time (FASTAPI-TEXT2SQL-308).

The rows of a generated query pass through untouched from PyMySQL, so a computed DOUBLE (the
weighted IMDb rating, an average, an aggregated popularity) reaches the client with 15 to 17
significant digits, and the timings and distances do the same. Those digits carry nothing, and
every client that reads the response with a model (MCP, voice-agent) pays for them in tokens.

Two rules shape this module:

- **Round on the way out, never upstream.** MariaDB has already sorted on the exact value, and
  the entity-resolution thresholds compare raw distances; rounding only the serialized copy
  changes no ORDER BY and no threshold decision. Nothing here mutates the objects it is given.
- **A DECIMAL is a number.** MariaDB returns AVG() and SUM() over an integer column as DECIMAL,
  PyMySQL hands it over as decimal.Decimal, and Pydantic v2 serializes a Decimal found inside
  `result: List[dict]` as a JSON *string* ("148.4000"), while the entity endpoints, which go
  through jsonable_encoder, emit a number. Converting here makes both routes agree.

Precision is chosen by key name, case-insensitively; a value inside a list inherits the key of
the list. Anything not listed gets two decimals, except a non-zero value below 0.1, which keeps
three significant digits so that a small quantity never collapses to 0.0.
"""
import math
from decimal import Decimal

from fastapi.responses import JSONResponse

DEFAULT_DECIMALS = 2

# Exact key -> decimals. None means "convert to a number, do not round".
_EXACT = {
    # Wikidata quantities: their magnitude is unknown, a box office and a ratio share the column.
    "AMOUNT": None,
    "AMOUNT_NORMALIZED": None,
    "LOWER_BOUND": None,
    "UPPER_BOUND": None,
    "LATITUDE": None,
    "LONGITUDE": None,
    # 23.976 is a frame rate, 23.98 is not.
    "FRAME_RATE": 3,
    # ChromaDB distances: thresholds sit two decimals apart, four keep the bench meaningful.
    "DISTANCE": 4,
    "MAX_DISTANCE": 4,
    "ENTITY_MATCH_WORST_DISTANCE": 4,
    "FUZZ_RATIO": 1,
    "FUZZ_RATIO_RAW": 1,
    "ENTITY_MATCH_WORST_FUZZ_RATIO": 1,
}

# Whole amounts stored as DOUBLE: 160000000.0 becomes 160000000.
_INTEGRAL_KEYS = {"BUDGET", "REVENUE"}


def _decimals_for(key):
    upper = (key or "").upper()
    if upper in _EXACT:
        return _EXACT[upper]
    if upper.endswith("_TIME") or upper.endswith("_SECONDS"):
        return 3  # the millisecond
    if upper.endswith("_DISTANCE"):
        return 4
    return DEFAULT_DECIMALS


def round_number(key, value):
    """Return `value` rounded for `key`; non-numeric values are returned unchanged."""
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        if not value.is_finite():
            return float(value)
        if value == value.to_integral_value():
            return int(value)
        value = float(value)
    if not isinstance(value, float):
        return value
    if not math.isfinite(value):
        return value
    upper = (key or "").upper()
    if upper in _INTEGRAL_KEYS and value.is_integer():
        return int(value)
    decimals = _decimals_for(key)
    if decimals is None:
        return value
    if decimals == DEFAULT_DECIMALS and value != 0 and abs(value) < 0.1:
        return float(f"{value:.3g}")
    return round(value, decimals)


def round_tree(value, key=""):
    """Round every number of a JSON-like tree. Returns a new tree, the input is left as is."""
    if isinstance(value, dict):
        return {k: round_tree(v, k if isinstance(k, str) else key) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [round_tree(v, key) for v in value]
    return round_number(key, value)


class RoundedJSONResponse(JSONResponse):
    """JSONResponse that rounds its content first. Used by the entity detail endpoints, which
    return plain dicts (FastAPI has already turned their Decimals into numbers)."""

    def render(self, content) -> bytes:
        return super().render(round_tree(content))
