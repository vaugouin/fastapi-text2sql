echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
docker ps --filter "name=fastapi-text2sql-green"

docker stop fastapi-text2sql-green

cd /home/debian/docker/fastapi-text2sql-green
clear
# Ensure ChromaDB is healthy before (re)starting the API — main.py connects to
# Chroma at import time and the container crashes on boot if it is unreachable.
bash "$HOME/docker/chromadb/chromadb-ensure.sh" || echo "WARNING: ChromaDB not healthy — the API will crash on boot until Chroma is up."
docker build -t fastapi-text2sql-green-app .
# Secrets are injected at runtime via --env-file from a host-managed env file
# kept outside the app source tree (never baked into the image).
#docker run -it --rm --network="host" --env-file /home/debian/docker/fastapi-text2sql-green/.env -v $(pwd):/app --name fastapi-text2sql-green fastapi-text2sql-green-app
docker run -d --rm --network="host" --env-file /home/debian/docker/fastapi-text2sql-green/.env -v $(pwd):/app --name fastapi-text2sql-green fastapi-text2sql-green-app

docker ps --filter "name=fastapi-text2sql-green"
echo "=== $(date '+%Y-%m-%d %H:%M:%S %Z') ==="
docker logs -f fastapi-text2sql-green
