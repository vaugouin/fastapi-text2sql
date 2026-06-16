#!/bin/bash

# Launch the voice-agent conversational harness benchmark in Docker.
# Modeled on text2sql-eval.sh.
#
# The harness ships INSIDE the same image as the evaluator (the eval Dockerfile
# does `COPY . /app/`), so we build that image and only override the entrypoint to
# run harness/run_harness.py instead of text2sql-eval.py.
#
# Like the evaluator, the harness reads the question bank straight from MariaDB
# (T_WC_T2S_EVALUATION), so it needs DB creds via the same --env-file. It does NOT
# need an OpenAI key (the voice-agent holds that). Results persist to /shared/harness.
#
# NETWORKING — the tricky part on this VPS:
#   * MariaDB is reached as DB_HOST=localhost, i.e. only over --network=host.
#   * the voice-agent runs on the `reverseproxy` bridge network (see its
#     restart.sh) and is NOT published on the host, so host:3000 does NOT reach it.
# These two live on different networks. Two ways to run, pick via env vars:
#
#   (A) host network + public voice-agent URL  [default, mirrors how the
#       voice-agent itself reaches the API via a public URL]:
#         VOICE_AGENT_URL=https://YOUR_HOST/voice-agent ./harness-eval.sh
#       (the harness calls $VOICE_AGENT_URL/text-chat → nginx → voice-agent:3000)
#
#   (B) join the reverseproxy network + reach the voice-agent by container name
#       (only if MariaDB is also reachable from that network):
#         NETWORK=reverseproxy VOICE_AGENT_URL=http://voice-agent:3000 ./harness-eval.sh

NETWORK=${NETWORK:-host}
# Default = the voice-agent's public nginx URL (confirmed reachable from the host),
# mirroring how the voice-agent itself reaches the API via a public URL. Override
# VOICE_AGENT_URL for mode (B) or a different host.
VOICE_AGENT_URL=${VOICE_AGENT_URL:-https://www.vaugouin.com/voice-agent}

# Check if the text2sql-harness Docker container is running
if [ $(docker ps -q -f name=text2sql-harness) ]; then
    echo "text2sql-harness Docker container is already running."
else
    # Build the (shared) image and start the harness container if not running
    cd $HOME/docker/text2sql-eval
    docker build -t text2sql-eval-python-app .
    # Full run over the failure-prone categories, French:
    # docker run -d --rm --network="$NETWORK" --env-file /home/debian/docker/text2sql-eval/.env -e VOICE_AGENT_URL="$VOICE_AGENT_URL" --name text2sql-harness -v /home/debian/docker/shared_data/text2sql-eval:/shared --entrypoint python text2sql-eval-python-app harness/run_harness.py --lang fr --categories 9,10,11,33,44
    docker run -d --rm --network="$NETWORK" --env-file /home/debian/docker/text2sql-eval/.env -e VOICE_AGENT_URL="$VOICE_AGENT_URL" --name text2sql-harness -v /home/debian/docker/shared_data/text2sql-eval:/shared --entrypoint python text2sql-eval-python-app harness/run_harness.py --lang en --limit 30
    docker logs -f text2sql-harness
fi
