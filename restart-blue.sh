echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
docker ps --filter "name=fastapi-text2sql-blue"

docker stop fastapi-text2sql-blue 

cd /home/debian/docker/fastapi-text2sql-blue
clear
# Ensure ChromaDB is healthy before (re)starting the API — main.py connects to
# Chroma at import time and the container crashes on boot if it is unreachable.
bash "$HOME/docker/chromadb/chromadb-ensure.sh" || echo "WARNING: ChromaDB not healthy — the API will crash on boot until Chroma is up."
# The log corpus is shared by every deployment (FASTAPI-TEXT2SQL-276). Without the
# second mount below each colour writes into its own stack dir and the dataset is
# split in three. The application knows nothing about it: LOGS_FOLDER is the relative
# "logs" (logs.py), so it writes to the same place whatever is mounted there, which is
# also why it still runs unchanged on a laptop.
# Create the host dir HERE rather than letting Docker create it: Docker would make it
# root-owned, and archive-logs.sh then cannot remove the loose originals.
LOGS_DIR=/home/debian/docker/shared_data/fastapi-text2sql/logs
mkdir -p "$LOGS_DIR/archive" || echo "WARNING: could not create $LOGS_DIR, the container will start with a root-owned log dir."
docker build -t fastapi-text2sql-blue-app .
# Secrets are injected at runtime via --env-file from a host-managed env file
# kept outside the app source tree (never baked into the image).
#docker run -it --rm --network="host" --env-file /home/debian/docker/fastapi-text2sql-blue/.env -v $(pwd):/app -v "$LOGS_DIR":/app/logs --name fastapi-text2sql-blue fastapi-text2sql-blue-app
docker run -d --rm --network="host" --env-file /home/debian/docker/fastapi-text2sql-blue/.env -v $(pwd):/app -v "$LOGS_DIR":/app/logs --name fastapi-text2sql-blue fastapi-text2sql-blue-app

docker ps --filter "name=fastapi-text2sql-blue"
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
docker logs -f fastapi-text2sql-blue
