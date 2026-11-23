#!/bin/bash
# Restart the API instance this checkout belongs to (FASTAPI-TEXT2SQL-412).
#
# One instance = one clone folder + its own .env. Nothing here knows a list of colours:
#   - the instance name is INSTANCE_NAME from the .env, or else the folder suffix
#     (/home/debian/docker/fastapi-text2sql-violet -> violet);
#   - the port is API_PORT from the .env, and only there (main.py listens on it);
#   - container fastapi-text2sql-<instance>, image fastapi-text2sql-<instance>-app.
# The version in main.py decides nothing about the name or the port any more: violet and brown
# may run the same version, or blue may run an odd one.
#
# A new instance: git clone into ~/docker/fastapi-text2sql-<name>, copy a .env, set API_PORT
# (a free port, opened in ufw) and optionally INSTANCE_NAME, then bash restart.sh.
# Runbook: doc/instances.md.
STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$STACK_DIR/.env"

# Read one KEY=value from the .env, without sourcing it (values may hold shell characters).
env_value() {
    grep -E "^[[:space:]]*$1[[:space:]]*=" "$2" 2>/dev/null | tail -1 \
        | sed -E "s/^[^=]*=[[:space:]]*//; s/[[:space:]]+#.*$//; s/^[\"']//; s/[\"'][[:space:]]*$//; s/[[:space:]]*$//"
}

if [ ! -s "$ENV_FILE" ]; then
    echo "ERROR: no $ENV_FILE, nothing restarted (a clone without .env is not an instance, e.g. the -ops clone of the crons)."
    exit 1
fi

INSTANCE="$(env_value INSTANCE_NAME "$ENV_FILE")"
if [ -z "$INSTANCE" ]; then
    FOLDER="$(basename "$STACK_DIR")"
    case "$FOLDER" in
        fastapi-text2sql-?*) INSTANCE="${FOLDER#fastapi-text2sql-}" ;;
        *)
            echo "ERROR: $FOLDER has no -<instance> suffix and $ENV_FILE sets no INSTANCE_NAME, nothing restarted."
            exit 1
            ;;
    esac
fi
if ! [[ "$INSTANCE" =~ ^[a-z0-9][a-z0-9-]*$ ]]; then
    echo "ERROR: instance name '$INSTANCE' must be lowercase letters, digits and dashes, nothing restarted."
    exit 1
fi

API_PORT="$(env_value API_PORT "$ENV_FILE")"
if ! [[ "$API_PORT" =~ ^[0-9]+$ ]]; then
    echo "ERROR: API_PORT is missing or not a number in $ENV_FILE, nothing restarted."
    if grep -qE '^[[:space:]]*API_PORT_(BLUE|GREEN)[[:space:]]*=' "$ENV_FILE"; then
        echo "       This .env still has API_PORT_BLUE / API_PORT_GREEN: replace them by API_PORT=<this instance's port>."
    fi
    exit 1
fi

# Two instances on one port: the second would fail to bind (host network), after the first
# one had been stopped. Refuse before stopping anything.
for other_env in "$(dirname "$STACK_DIR")"/fastapi-text2sql*/.env; do
    [ -f "$other_env" ] || continue
    [ "$other_env" = "$ENV_FILE" ] && continue
    if [ "$(env_value API_PORT "$other_env")" = "$API_PORT" ]; then
        echo "ERROR: $other_env also declares API_PORT=$API_PORT, nothing restarted."
        exit 1
    fi
done

NAME="fastapi-text2sql-$INSTANCE"

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === $NAME (port $API_PORT)"
docker ps --filter "name=^${NAME}\$"

docker stop "$NAME" 2>/dev/null

# The port must be free once our own container is stopped: anything still listening there is
# another process, and the new container would die on bind.
if ss -ltn 2>/dev/null | awk '{print $4}' | grep -qE "[:.]${API_PORT}\$"; then
    echo "ERROR: port $API_PORT is still in use after stopping $NAME, not started:"
    ss -ltnp 2>/dev/null | grep -E "[:.]${API_PORT}[[:space:]]" || true
    exit 1
fi

cd "$STACK_DIR" || exit 1
# Ensure ChromaDB is healthy before (re)starting the API — main.py connects to
# Chroma at import time and the container crashes on boot if it is unreachable.
bash "$HOME/docker/chromadb/chromadb-ensure.sh" || echo "WARNING: ChromaDB not healthy — the API will crash on boot until Chroma is up."
# The log corpus is shared by every instance (FASTAPI-TEXT2SQL-276). Without the
# logs mount below each instance writes into its own stack dir and the dataset is
# split. The application knows nothing about it: LOGS_FOLDER is the relative
# "logs" (logs.py), so it writes to the same place whatever is mounted there, which is
# also why it still runs unchanged on a laptop. Each record names its instance (-412).
# Create the host dir HERE rather than letting Docker create it: Docker would make it
# root-owned, and archive-logs.sh then cannot remove the loose originals.
LOGS_DIR=/home/debian/docker/shared_data/fastapi-text2sql/logs
mkdir -p "$LOGS_DIR/archive" || echo "WARNING: could not create $LOGS_DIR, the container will start with a root-owned log dir."
# Same move, same reason, for the vision uploads (FASTAPI-TEXT2SQL-275). An image deposited
# on one instance has to be readable from another, otherwise a switch makes a replay fail in
# silence, which is worse than a failure that shows. UPLOADS_FOLDER is the relative "uploads"
# (uploads.py), like LOGS_FOLDER, so nothing in the code knows about this mount.
# The regime here is the OPPOSITE of logs/: purged after 30 days by purge-uploads.sh, not
# backed up, not mirrored. Write that rule on the folder, never on the shared parent.
UPLOADS_DIR=/home/debian/docker/shared_data/fastapi-text2sql/uploads
mkdir -p "$UPLOADS_DIR/vision" || echo "WARNING: could not create $UPLOADS_DIR, the container will start with a root-owned uploads dir."
# The OAuth client registrations and tokens of /mcp (mcp_auth.py), encrypted with
# MCP_OAUTH_STORAGE_KEY. Shared by every instance for the same reason as uploads/: kept per
# instance, each switch or restart would log every MCP client out. Back it up with the
# secrets; losing it only forces a new login.
MCP_OAUTH_DIR=/home/debian/docker/shared_data/fastapi-text2sql/mcp-oauth
mkdir -p "$MCP_OAUTH_DIR" || echo "WARNING: could not create $MCP_OAUTH_DIR, the container will start with a root-owned OAuth store."
docker build -t "$NAME-app" .
# Secrets are injected at runtime via --env-file from a host-managed env file
# kept outside the app source tree (never baked into the image). INSTANCE_NAME is passed
# explicitly so a folder-derived name reaches the logs and GET / too.
#docker run -it --rm --network="host" --env-file "$ENV_FILE" -e INSTANCE_NAME="$INSTANCE" -v "$STACK_DIR":/app -v "$LOGS_DIR":/app/logs -v "$UPLOADS_DIR":/app/uploads -v "$MCP_OAUTH_DIR":/app/mcp-oauth --name "$NAME" "$NAME-app"
docker run -d --rm --network="host" --env-file "$ENV_FILE" -e INSTANCE_NAME="$INSTANCE" -v "$STACK_DIR":/app -v "$LOGS_DIR":/app/logs -v "$UPLOADS_DIR":/app/uploads -v "$MCP_OAUTH_DIR":/app/mcp-oauth --name "$NAME" "$NAME-app"

docker ps --filter "name=^${NAME}\$"
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === $NAME (port $API_PORT)"
# Returns once the container is started, with its last log lines (2026-11-15): follow them with
# docker logs -f "$NAME" when needed. Wait for bktrees_ready: true in GET / before judging it.
sleep 3
docker logs --tail 20 "$NAME"
