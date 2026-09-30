#!/bin/bash
# Restart the API of the colour this checkout belongs to. The colour is read from the
# folder the script lives in: /home/debian/docker/fastapi-text2sql-blue restarts Blue,
# /home/debian/docker/fastapi-text2sql-green restarts Green. Anywhere else it stops,
# rather than guess a colour and restart the live one by mistake.
STACK_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
case "$STACK_DIR" in
    /home/debian/docker/fastapi-text2sql-blue) COLOR=blue ;;
    /home/debian/docker/fastapi-text2sql-green) COLOR=green ;;
    *)
        echo "ERROR: $STACK_DIR is neither /home/debian/docker/fastapi-text2sql-blue nor /home/debian/docker/fastapi-text2sql-green, nothing restarted."
        exit 1
        ;;
esac
NAME="fastapi-text2sql-$COLOR"

echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === $NAME"
docker ps --filter "name=$NAME"

docker stop "$NAME"

cd "$STACK_DIR" || exit 1
clear
# Ensure ChromaDB is healthy before (re)starting the API — main.py connects to
# Chroma at import time and the container crashes on boot if it is unreachable.
bash "$HOME/docker/chromadb/chromadb-ensure.sh" || echo "WARNING: ChromaDB not healthy — the API will crash on boot until Chroma is up."
# The log corpus is shared by every deployment (FASTAPI-TEXT2SQL-276). Without the
# logs mount below each colour writes into its own stack dir and the dataset is
# split in three. The application knows nothing about it: LOGS_FOLDER is the relative
# "logs" (logs.py), so it writes to the same place whatever is mounted there, which is
# also why it still runs unchanged on a laptop.
# Create the host dir HERE rather than letting Docker create it: Docker would make it
# root-owned, and archive-logs.sh then cannot remove the loose originals.
LOGS_DIR=/home/debian/docker/shared_data/fastapi-text2sql/logs
mkdir -p "$LOGS_DIR/archive" || echo "WARNING: could not create $LOGS_DIR, the container will start with a root-owned log dir."
# Same move, same reason, for the vision uploads (FASTAPI-TEXT2SQL-275). An image deposited
# on one colour has to be readable from the other, otherwise a flip makes a replay fail in
# silence, which is worse than a failure that shows. UPLOADS_FOLDER is the relative "uploads"
# (uploads.py), like LOGS_FOLDER, so nothing in the code knows about this mount.
# The regime here is the OPPOSITE of logs/: purged after 30 days by purge-uploads.sh, not
# backed up, not mirrored. Write that rule on the folder, never on the shared parent.
UPLOADS_DIR=/home/debian/docker/shared_data/fastapi-text2sql/uploads
mkdir -p "$UPLOADS_DIR/vision" || echo "WARNING: could not create $UPLOADS_DIR, the container will start with a root-owned uploads dir."
docker build -t "$NAME-app" .
# Secrets are injected at runtime via --env-file from a host-managed env file
# kept outside the app source tree (never baked into the image).
#docker run -it --rm --network="host" --env-file "$STACK_DIR/.env" -v "$STACK_DIR":/app -v "$LOGS_DIR":/app/logs -v "$UPLOADS_DIR":/app/uploads --name "$NAME" "$NAME-app"
docker run -d --rm --network="host" --env-file "$STACK_DIR/.env" -v "$STACK_DIR":/app -v "$LOGS_DIR":/app/logs -v "$UPLOADS_DIR":/app/uploads --name "$NAME" "$NAME-app"

docker ps --filter "name=$NAME"
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') === $NAME"
docker logs -f "$NAME"
