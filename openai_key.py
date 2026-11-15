"""The OpenAI key of the current request (bring your own key).

The API holds no OpenAI key of its own: every client sends one in the ``X-OpenAI-Key``
header, and every OpenAI call made for that request (chat, Responses, vision, the
``decisions`` classifier and the ChromaDB query embeddings) is paid with it. A visitor of
the public voice-agent demo therefore pays for their own questions.

The key lives in a ContextVar, never in a module global: a global swapped per request
would let two concurrent requests pay for each other. ``asyncio.to_thread`` and
``asyncio.create_task`` copy the context, so the worker threads of one request see that
request's key and no other. Same lifecycle as the per-request buffers of ``text2sql.py``
and ``feedback.py``: set by the outer pass of ``/search/text2sql``, inherited by the
complex retry's inner pass.

The key is never logged, never stored, never echoed: use ``fingerprint()`` when a trace
needs to tell two keys apart.
"""

import contextvars
import hashlib
import re

HEADER_NAME = "X-OpenAI-Key"

_request_key: "contextvars.ContextVar[str]" = contextvars.ContextVar("openai_request_key", default="")

# OpenAI keys are printable ASCII without spaces (sk-..., sk-proj-..., sk-svcacct-...).
# Anything else is refused before it reaches an HTTP header of ours or theirs.
_KEY_PATTERN = re.compile(r"^[A-Za-z0-9_\-]{20,512}$")


class OpenAIKeyMissing(RuntimeError):
    """Raised by require() when the request carries no OpenAI key."""


def is_well_formed(key: str) -> bool:
    """True when the string can be an OpenAI key (shape only, not validity)."""
    return bool(key) and bool(_KEY_PATTERN.match(key))


def set_request_key(key) -> None:
    """Store the key of the current request; an empty or malformed value stores nothing."""
    strkey = key.strip() if isinstance(key, str) else ""
    _request_key.set(strkey if is_well_formed(strkey) else "")


def current() -> str:
    """The key of the current request, or "" when it carries none."""
    return _request_key.get()


def require() -> str:
    """The key of the current request; raises OpenAIKeyMissing when there is none."""
    strkey = _request_key.get()
    if not strkey:
        raise OpenAIKeyMissing(f"No OpenAI key on this request (header {HEADER_NAME}).")
    return strkey


# The other providers (2026-11-15). The API keeps its own Anthropic, Google and OpenRouter keys,
# but a client may send its own in these headers, and that request is then paid with it: the
# evaluator does, so a campaign on a Claude model bills the evaluator's account. Same ContextVar
# rule as the OpenAI key; a malformed value counts as none.
PROVIDER_HEADERS = {
    "anthropic": "X-Anthropic-Key",
    "google": "X-Google-Key",
    "openrouter": "X-OpenRouter-Key",
}
_provider_keys: "contextvars.ContextVar[dict]" = contextvars.ContextVar("provider_request_keys", default={})


def set_provider_keys(keys) -> None:
    """Store the other providers' keys of the current request: {provider: key}, malformed dropped."""
    clean = {}
    for provider, value in (keys or {}).items():
        strkey = value.strip() if isinstance(value, str) else ""
        if provider in PROVIDER_HEADERS and is_well_formed(strkey):
            clean[provider] = strkey
    _provider_keys.set(clean)


def provider_key(provider: str, env_value) -> str:
    """The request's key for this provider, else the server's own (env_value), else ""."""
    return _provider_keys.get().get(provider) or (env_value or "")


def fingerprint(key: str = None) -> str:
    """A short, non-reversible tag of a key, for traces ("" when there is no key)."""
    strkey = current() if key is None else key
    if not strkey:
        return ""
    return hashlib.sha256(strkey.encode("utf-8")).hexdigest()[:8]
