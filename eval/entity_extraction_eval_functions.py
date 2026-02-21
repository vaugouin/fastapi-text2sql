import re
from typing import Any, Dict, List, Tuple


def ee_eval_two_layer(
    ee: Dict[str, Any],
    layer2_expr: str,
) -> bool:
    """
    Two-layer EE evaluation (0/1 as boolean):

    Inputs:
      - ee: dict with at least {"question": "..."} and optionally extracted entity keys.
      - layer2_expr: Layer-2 "gold-value exact" expression in the DSL style, e.g.:
            '(eq($.question, "What is {{Person_name1}}?") AND eq($.Person_name1, "Stanley Kubrick"))'
        Supported in Layer 2:
          - AND / OR / NOT, parentheses
          - eq(a, b)
          - nonempty(x)
          - seteq(listA, listB)
          - placeholders($.question)
          - entity_keys($)
          - keys($)
          - matches(x, /regex/flags)   flags: i (ignorecase), m, s
          - $.<Key> (root key access)

    Returns:
      - True iff Layer 1 (schema/contract hard gate) AND Layer 2 (gold expression) are True.
    """

    # ----------------------------
    # Layer 1 — Schema/Contract
    # ----------------------------
    q = ee.get("question", None)
    if not isinstance(q, str) or not q.strip():
        return False

    ph = _placeholders(q)  # list of placeholder names in question
    ek = _entity_keys(ee)  # list of entity keys (excluding "question")

    # Hard gate: placeholders <-> entity keys must match exactly (order-insensitive)
    if sorted(ph) != sorted(ek):
        return False

    # Hard gate: each entity value must be a non-empty string
    for k in ek:
        v = ee.get(k, None)
        if not isinstance(v, str) or not v.strip():
            return False

    # ----------------------------
    # Layer 2 — Gold-value exact
    # ----------------------------
    try:
        return bool(_eval_layer2(layer2_expr, ee))
    except Exception:
        # Any parsing/eval error => fail closed
        return False


# ============================================================
# DSL helpers (Layer 2)
# ============================================================

_PLACEHOLDER_RE = re.compile(r"\{\{([A-Za-z_][A-Za-z0-9_]*)\}\}")

def _placeholders(question: str) -> List[str]:
    return _PLACEHOLDER_RE.findall(question or "")

def _entity_keys(ee: Dict[str, Any]) -> List[str]:
    return [k for k in ee.keys() if k != "question"]

def _keys_root(ee: Dict[str, Any]) -> List[str]:
    return list(ee.keys())

def _nonempty(x: Any) -> bool:
    return isinstance(x, str) and bool(x.strip())

def _seteq(a: Any, b: Any) -> bool:
    # Treat None as empty for convenience
    a_list = list(a or [])
    b_list = list(b or [])
    return sorted(a_list) == sorted(b_list)

def _eq(a: Any, b: Any) -> bool:
    return a == b

def _matches(x: Any, pattern: Any) -> bool:
    """
    pattern can be:
      - a compiled regex (re.Pattern)
      - a string regex
    """
    if not isinstance(x, str):
        return False
    if isinstance(pattern, re.Pattern):
        return pattern.search(x) is not None
    if isinstance(pattern, str):
        return re.search(pattern, x) is not None
    return False

def _V(ee: Dict[str, Any], key: str) -> Any:
    return ee.get(key, None)

_REGEX_LITERAL_RE = re.compile(r"/((?:\\.|[^/])*)/([ims]*)")

def _compile_regex_literal(m: re.Match) -> re.Pattern:
    body = m.group(1)
    flags_s = m.group(2) or ""
    flags = 0
    if "i" in flags_s:
        flags |= re.IGNORECASE
    if "m" in flags_s:
        flags |= re.MULTILINE
    if "s" in flags_s:
        flags |= re.DOTALL
    return re.compile(body, flags)

def _eval_layer2(expr: str, ee: Dict[str, Any]) -> Any:
    """
    Translate a constrained DSL expression to a Python expression and eval it
    in a locked-down environment.
    """

    if not isinstance(expr, str) or not expr.strip():
        raise ValueError("Layer2 expression must be a non-empty string")

    s = expr.strip()

    # 1) Convert boolean operators (case-insensitive)
    s = re.sub(r"\bAND\b", "and", s, flags=re.IGNORECASE)
    s = re.sub(r"\bOR\b", "or", s, flags=re.IGNORECASE)
    s = re.sub(r"\bNOT\b", "not", s, flags=re.IGNORECASE)

    # 2) Replace $.Key with V("Key")
    #    (Only allow simple root keys; no nested paths here.)
    s = re.sub(
        r"\$\.\s*([A-Za-z_][A-Za-z0-9_]*)",
        lambda m: f'V("{m.group(1)}")',
        s,
    )

    # 3) Replace entity_keys($), keys($) with functions
    s = re.sub(r"entity_keys\s*\(\s*\$\s*\)", "entity_keys()", s)
    s = re.sub(r"keys\s*\(\s*\$\s*\)", "keys_()", s)

    # 4) Keep placeholders($.question) valid because $.question already became V("question")
    #    i.e. placeholders(V("question"))

    # 5) Convert /regex/flags literals into compiled patterns: REGEX("..", "i")
    #    We implement by substituting them with a placeholder token and passing compiled objects in locals.
    regex_objects: List[re.Pattern] = []

    def repl_regex(m: re.Match) -> str:
        pat = _compile_regex_literal(m)
        idx = len(regex_objects)
        regex_objects.append(pat)
        return f"__re_{idx}__"

    s = _REGEX_LITERAL_RE.sub(repl_regex, s)

    # 6) Build safe eval environment
    safe_globals = {"__builtins__": {}}
    safe_locals = {
        # data access
        "V": lambda k: _V(ee, k),
        "entity_keys": lambda: _entity_keys(ee),
        "keys_": lambda: _keys_root(ee),
        "placeholders": _placeholders,
        # predicates
        "nonempty": _nonempty,
        "seteq": _seteq,
        "eq": _eq,
        "matches": _matches,
    }

    # inject compiled regexes
    for i, rx in enumerate(regex_objects):
        safe_locals[f"__re_{i}__"] = rx

    # 7) Eval
    return eval(s, safe_globals, safe_locals)


# ============================================================
# Example usage
# ============================================================
if __name__ == "__main__":
    ee = {"question": "What are the highest-grossing movies of all time?"}
    layer2 = 'eq($.question, "What are the highest-grossing movies of all time?") AND seteq(entity_keys($), [])'
    print(ee_eval_two_layer(ee, layer2))  # True

    ee2 = {
        "question": "{{Movie_title1}} ({{Release_year1}})",
        "Movie_title1": "Tommy",
        "Release_year1": "1975",
    }
    layer2_2 = (
        'eq($.question, "{{Movie_title1}} ({{Release_year1}})") AND '
        'eq($.Movie_title1, "Tommy") AND eq($.Release_year1, "1975") AND '
        'matches($.Release_year1, /^(19|20)\\d{2}$/)'
    )
    print(ee_eval_two_layer(ee2, layer2_2))  # True
    