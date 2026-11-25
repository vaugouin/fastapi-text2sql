"""OAuth in front of the MCP server: GitHub login through FastMCP's OAuth proxy, and an
allowlist of the GitHub logins that may see and call the tools.

Why OAuth rather than the static bearer used until 2026-11-15: ChatGPT's custom MCP
plugins and claude.ai connectors offer OAuth or no authentication, never an arbitrary
header, and no authentication is excluded because sql_search spends an OpenAI key.

How it works. The OAuth proxy presents a complete authorization server to MCP clients
(metadata, dynamic client registration, /authorize, /token) and delegates the login to
one GitHub OAuth app. GitHub authenticates ANY GitHub user, so the allowlist below is
what keeps the server private: without it, anyone with a GitHub account could call
sql_search.

Every instance must share two things, or a restart or an instance switch logs every
client out: the JWT signing key (MCP_OAUTH_JWT_SIGNING_KEY, the same in each instance
.env) and the client storage (a disk store on the shared_data mount, encrypted with
MCP_OAUTH_STORAGE_KEY, also the same everywhere).

Fail closed: when the OAuth settings are missing, the server keeps its tools but every
listing is empty and every call refused, and startup says so. The routes stay mounted,
so a misconfigured instance is visible rather than open.
"""

import json
import os
import threading
import time
from typing import Optional

from fastmcp.server.auth import AuthContext
from fastmcp.server.middleware import AuthMiddleware, Middleware, MiddlewareContext

MCP_PUBLIC_BASE_URL = os.getenv("MCP_PUBLIC_BASE_URL", "").strip().rstrip("/")
MCP_GITHUB_CLIENT_ID = os.getenv("MCP_GITHUB_CLIENT_ID", "").strip()
MCP_GITHUB_CLIENT_SECRET = os.getenv("MCP_GITHUB_CLIENT_SECRET", "").strip()
MCP_OAUTH_JWT_SIGNING_KEY = os.getenv("MCP_OAUTH_JWT_SIGNING_KEY", "").strip()
MCP_OAUTH_STORAGE_KEY = os.getenv("MCP_OAUTH_STORAGE_KEY", "").strip()
# Mounted by restart.sh from shared_data, so every instance reads the same registrations.
MCP_OAUTH_STORAGE_DIR = os.getenv("MCP_OAUTH_STORAGE_DIR", "mcp-oauth").strip()
MCP_ALLOWED_GITHUB_LOGINS = frozenset(
    login.strip().lower()
    for login in os.getenv("MCP_ALLOWED_GITHUB_LOGINS", "").split(",")
    if login.strip()
)
# The API holds no OpenAI key of its own: sql_search must send one in X-OpenAI-Key or it
# only serves cache hits. A stopgap for the owner's account, removed once each user stores
# their own key on the account page (decided 2026-11-23).
MCP_OWNER_OPENAI_KEY = os.getenv("MCP_OWNER_OPENAI_KEY", "").strip()

_REQUIRED = {
    "MCP_PUBLIC_BASE_URL": MCP_PUBLIC_BASE_URL,
    "MCP_GITHUB_CLIENT_ID": MCP_GITHUB_CLIENT_ID,
    "MCP_GITHUB_CLIENT_SECRET": MCP_GITHUB_CLIENT_SECRET,
    "MCP_OAUTH_JWT_SIGNING_KEY": MCP_OAUTH_JWT_SIGNING_KEY,
    "MCP_OAUTH_STORAGE_KEY": MCP_OAUTH_STORAGE_KEY,
    "MCP_ALLOWED_GITHUB_LOGINS": ",".join(sorted(MCP_ALLOWED_GITHUB_LOGINS)),
}


def missing_settings() -> list:
    return [name for name, value in _REQUIRED.items() if not value]


def build_auth_provider():
    """The GitHub OAuth proxy, or None when a setting is missing (then every call is refused)."""
    if missing_settings():
        return None
    from cryptography.fernet import Fernet
    from fastmcp.server.auth.providers.github import GitHubProvider
    from key_value.aio.stores.disk import DiskStore
    from key_value.aio.wrappers.encryption import FernetEncryptionWrapper

    os.makedirs(MCP_OAUTH_STORAGE_DIR, exist_ok=True)
    return GitHubProvider(
        client_id=MCP_GITHUB_CLIENT_ID,
        client_secret=MCP_GITHUB_CLIENT_SECRET,
        base_url=MCP_PUBLIC_BASE_URL,
        jwt_signing_key=MCP_OAUTH_JWT_SIGNING_KEY,
        client_storage=FernetEncryptionWrapper(
            key_value=DiskStore(directory=MCP_OAUTH_STORAGE_DIR),
            fernet=Fernet(MCP_OAUTH_STORAGE_KEY),
        ),
    )


def github_login(ctx: AuthContext) -> Optional[str]:
    token = getattr(ctx, "token", None)
    if token is None:
        return None
    login = (getattr(token, "claims", None) or {}).get("login")
    return str(login).lower() if login else None


def allowlisted(ctx: AuthContext) -> bool:
    """Auth check for every tool: the caller's GitHub login must be in the allowlist."""
    return bool(MCP_ALLOWED_GITHUB_LOGINS) and github_login(ctx) in MCP_ALLOWED_GITHUB_LOGINS


# Journal of MCP tool calls, one JSON line per call, keyed on the caller's GitHub login.
# The per-request logs (logs/<date>_<endpoint>_...json) cannot answer "who asked what": every
# MCP tool reaches the API through an internal HTTP call made with the server's own API key,
# so those logs see the MCP server as the caller, never the account behind it. This journal is
# the only place that ties a call to an account, which is what a per-account quota and the
# analysis of a rating left from Claude or ChatGPT need. One file per month in the logs folder
# (the shared_data mount, so every instance appends to the same one); the .jsonl extension
# keeps it out of the readers that glob *.json for request logs (switch-clients.sh check).
# Refused calls are journaled too: the journal sits outside the allowlist check.
MCP_JOURNAL_MAX_ARG_CHARS = 2000
_journal_lock = threading.Lock()


def _journal_login() -> tuple:
    """(login, client_id) of the caller, (None, None) when the call carries no token."""
    try:
        from fastmcp.server.dependencies import get_access_token
        token = get_access_token()
    except Exception:
        return None, None
    if token is None:
        return None, None
    login = (getattr(token, "claims", None) or {}).get("login")
    return (str(login).lower() if login else None), getattr(token, "client_id", None)


def _journal_args(arguments) -> dict:
    out = {}
    for key, value in (arguments or {}).items():
        if isinstance(value, str) and len(value) > MCP_JOURNAL_MAX_ARG_CHARS:
            value = value[:MCP_JOURNAL_MAX_ARG_CHARS] + "..."
        out[key] = value
    return out


def journal_write(record: dict) -> None:
    """Append one record; a journal failure never fails the tool call."""
    import logs
    try:
        stamp = logs.now_paris()
        record = {"ts": stamp.isoformat(timespec="seconds"), "instance": logs.INSTANCE_NAME, **record}
        os.makedirs(logs.LOGS_FOLDER, exist_ok=True)
        path = os.path.join(logs.LOGS_FOLDER, f"mcp-calls-{stamp:%Y-%m}.jsonl")
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        with _journal_lock, open(path, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception as exc:
        print(f"[mcp-journal] write failed: {type(exc).__name__}: {exc}")


class CallJournal(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        login, client_id = _journal_login()
        message = context.message
        record = {
            "login": login,
            "client_id": client_id,
            "tool": getattr(message, "name", None),
            "arguments": _journal_args(getattr(message, "arguments", None)),
        }
        started = time.monotonic()
        try:
            result = await call_next(context)
        except Exception as exc:
            record.update(outcome="error", error=f"{type(exc).__name__}: {str(exc)[:300]}",
                          duration_ms=round((time.monotonic() - started) * 1000))
            journal_write(record)
            raise
        record.update(outcome="ok", duration_ms=round((time.monotonic() - started) * 1000))
        journal_write(record)
        return result


def build_middleware() -> list:
    # Journal first: middleware run in list order, so it wraps the allowlist check and also
    # records the calls that check refuses.
    return [CallJournal(), AuthMiddleware(auth=allowlisted)]


def startup_lines(auth_enabled: bool) -> list:
    if auth_enabled:
        lines = [
            f"[startup] MCP OAuth ENABLED (GitHub login), public base {MCP_PUBLIC_BASE_URL}, "
            f"{len(MCP_ALLOWED_GITHUB_LOGINS)} allowed login(s), storage {MCP_OAUTH_STORAGE_DIR}."
        ]
        if not MCP_OWNER_OPENAI_KEY:
            lines.append("[startup] MCP_OWNER_OPENAI_KEY is empty: sql_search serves cache hits only.")
        return lines
    return [
        "[startup] *** MCP OAuth NOT configured, every MCP tool call is refused. Missing: "
        + ", ".join(missing_settings()) + " ***"
    ]
