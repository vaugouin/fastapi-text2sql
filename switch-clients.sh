#!/usr/bin/env bash
# Point the API clients of the VPS at an instance, or check where each one points.
# Runbook: doc/instances.md, section 5 (switching the clients); client table: README.md, "Instances".
#
# Run on the VPS as debian, from a clone that is no instance (fastapi-text2sql-ops):
#   cd ~/docker/fastapi-text2sql-ops && git pull --ff-only
#   bash switch-clients.sh check                # where every client points, and who called whom lately
#   bash switch-clients.sh switch 8186 8188     # blue -> violet (every :8186 becomes :8188)
#   bash switch-clients.sh switch 8188 8186     # and back
#
# switch refuses to start unless the target answers bktrees_ready: true. Each edited file is backed up
# as <file>.bak-<YYYYMMDD-HHMMSS>. Clients a switch cannot reach from here are listed at the end:
# agent-runner (Hostinger), the evaluator (port derived from the version, TEXT2SQL-EVAL-011), the PC tools.
# Edits keep the scheme and host of each URL and change the port only.
# The MCP host is one of the clients: its upstream port lives in reverseproxy/includes/t2s-api-live.conf,
# a file git does not track (each switch rewrites it on the VPS), and a switch that edits it reloads
# NGINX through reverseproxy/reload.sh; on a refused reload the file is restored, MCP stays on the old port.
set -u
D=${DOCKER_ROOT:-$HOME/docker}
LOGS_DIR=${LOGS_DIR:-$D/shared_data/fastapi-text2sql/logs}
RECENT_MIN=${RECENT_MIN:-15}
STAMP=bak-$(date +%Y%m%d-%H%M%S)

# One API key, read from any instance's .env (API_KEYS is a comma-separated list), for GET /.
KEY=$(grep -h -m1 '^API_KEYS=' "$D"/fastapi-text2sql-*/.env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' | cut -d, -f1)

instance_on() {  # instance_on <port>: "violet ready" / "blue loading" / "down"
    local j
    j=$(curl -s -m 5 -H "X-API-Key: $KEY" "http://127.0.0.1:$1/" 2>/dev/null)
    local name ready
    name=$(printf '%s' "$j" | grep -o '"instance":"[^"]*"' | cut -d'"' -f4)
    ready=$(printf '%s' "$j" | grep -o '"bktrees_ready":[a-z]*' | cut -d: -f2)
    if [ -z "$name" ]; then echo "down"; elif [ "$ready" = "true" ]; then echo "$name ready"; else echo "$name loading"; fi
}

port_of() { printf '%s' "$1" | sed -n 's#.*:\([0-9][0-9]*\).*#\1#p'; }

# Clients: label | file | variable (empty: the file's first line is the URL; @server: the "server"
# line of an NGINX upstream) | default when unset
MCP_UPSTREAM=$D/reverseproxy/includes/t2s-api-live.conf
CLIENTS=(
    "MCP host (reverseproxy upstream)|$MCP_UPSTREAM|@server|"
    "t2s-front (/en/ /fr/ /private/ demos)|$D/t2s-front/.env|TEXT2SQL_API_BLUE_URL|"
    "t2s-back (/back-new/)|$D/t2s-back/.env|TEXT2SQL_API_BLUE_URL|"
    "damp-vaugouin-com stack .env (to unset)|$D/damp-vaugouin-com/.env|TEXT2SQL_API_BLUE_URL|"
    "voice-agent (owner)|$D/voice-agent/runtime/text2sql-url||"
    "voice-agent .env (fallback)|$D/voice-agent/.env|TEXT2SQL_BASE_URL|"
    "voice-demo|$D/voice-agent/runtime/text2sql-url-demo||"
    "voice-demo .env.demo (fallback)|$D/voice-agent/.env.demo|TEXT2SQL_BASE_URL|"
    "t2s-web|$D/t2s-web/.env|T2S_BLUE_URL|"
    "listening-companion|$D/listening-companion/.env|TEXT2SQL_BASE_URL|http://host.docker.internal:8186"
)

read_url() {  # read_url <file> <var> <default>
    local f=$1 v=$2 def=$3
    [ -f "$f" ] || { echo "(absent)"; return; }
    if [ "$v" = "@server" ]; then grep -m1 -E '^[[:space:]]*server[[:space:]]' "$f" | sed -E 's/^[[:space:]]*server[[:space:]]+//; s/;.*//'
    elif [ -z "$v" ]; then grep -v -e '^[[:space:]]*#' -e '^[[:space:]]*$' "$f" | head -1
    else
        local line; line=$(grep -m1 "^$v=" "$f" | cut -d= -f2- | tr -d '"')
        [ -n "$line" ] && echo "$line" || echo "${def:-(unset)}${def:+ (default)}"
    fi
}

do_check() {
    echo "== Instances"
    for p in 8186 8187 8188 8189; do printf '  :%s  %s\n' "$p" "$(instance_on $p)"; done
    echo "== Clients: configured URL -> instance answering on that port"
    local entry label f v def url p
    for entry in "${CLIENTS[@]}"; do
        IFS='|' read -r label f v def <<< "$entry"
        url=$(read_url "$f" "$v" "$def"); p=$(port_of "$url")
        printf '  %-38s %-40s -> %s\n' "$label" "$url" "${p:+$(instance_on "$p")}"
    done
    echo "== What the running containers really use"
    local fpm; fpm=$(docker ps --format '{{.Names}}' | grep -m1 php-fpm)
    [ -n "$fpm" ] && printf '  %-38s %s\n' "php-fpm process env" "$(docker exec "$fpm" printenv TEXT2SQL_API_BLUE_URL 2>/dev/null || echo '(unset: t2s-front/.env and t2s-back/.env decide, the seamless state)')"
    printf '  %-38s %s\n' "t2s-front colour line" "$(grep -m1 '^\$strtext2sqlapicolor' "$D/t2s-front/lib/global-light.inc.php" 2>/dev/null)"
    local c
    for c in voice-agent voice-agent-demo; do
        docker ps --format '{{.Names}}' | grep -qx "$c" || { printf '  %-38s %s\n' "$c" "not running"; continue; }
        printf '  %-38s %s\n' "$c /tool/health" "$(docker exec "$c" python -c "import urllib.request,json;h=json.load(urllib.request.urlopen('http://127.0.0.1:3000/tool/health'));print('source', h.get('api_url_source'), 'version', h.get('api_version'), 'reachable', h.get('api_reachable'))" 2>/dev/null || echo 'health unreadable')"
    done
    # hello (GET /, version probes, this script's own) and start (an instance booting) are not client
    # calls: counting them made a drained instance look busy. Every other route is (search, entities, uploads).
    echo "== Client requests logged in the last $RECENT_MIN min, by instance (the proof: who still calls the old one)"
    find "$LOGS_DIR" -maxdepth 1 -name '*.json' -mmin "-$RECENT_MIN" ! -name '*_hello_*' ! -name '*_start_*' -print0 2>/dev/null \
        | xargs -0 -r grep -h -m1 -o '"instance": *"[a-z]*"' | cut -d'"' -f4 | sort | uniq -c | sed 's/^/  /'
    echo "  (the evaluator still calls blue or green by design; agent-runner and PC tools are not checked here)"
}

swap_port() {  # swap_port <file> <var> <from> <to> <default>
    local f=$1 v=$2 from=$3 to=$4 def=$5
    [ -f "$f" ] || { echo "  SKIP  $f (absent)"; return; }
    if [ "$v" = "@server" ]; then
        grep -qE "^[[:space:]]*server[[:space:]]+[^;]*:$from([^0-9]|\$)" "$f" || { echo "  SKIP  $f: upstream not on :$from"; return; }
        cp -p "$f" "$f.$STAMP"; sed -i -E "s#^([[:space:]]*server[[:space:]]+[^;]*:)$from([^0-9]|\$)#\\1$to\\2#" "$f"
        sed -i -E "/^[[:space:]]*server[[:space:]]/ s|;.*|;  # set by switch-clients.sh on $(date +%Y-%m-%d), from :$from|" "$f"
    elif [ -z "$v" ]; then
        grep -q ":$from" "$f" || { echo "  SKIP  $f (not on :$from)"; return; }
        cp -p "$f" "$f.$STAMP"; sed -i "s#:$from\b#:$to#" "$f"
    elif grep -q "^$v=" "$f"; then
        grep -q "^$v=.*:$from" "$f" || { echo "  SKIP  $f: $v not on :$from"; return; }
        cp -p "$f" "$f.$STAMP"; sed -i "s#^\($v=.*:\)$from#\1$to#" "$f"
    elif [ -n "$def" ] && [ "$(port_of "$def")" = "$from" ]; then
        cp -p "$f" "$f.$STAMP"; echo "$v=${def%:*}:$to" >> "$f"
    else echo "  SKIP  $f: no $v"; return; fi
    echo "  OK    $f: $(read_url "$f" "$v" "$def")"
}

do_switch() {
    local from=$1 to=$2
    case "$(instance_on "$to")" in
        *" ready") echo "== Target :$to is $(instance_on "$to")" ;;
        *) echo "STOP: :$to is $(instance_on "$to"), wait for bktrees_ready: true"; exit 1 ;;
    esac
    echo "== Editing the client files"
    local entry label f v def
    for entry in "${CLIENTS[@]}"; do
        IFS='|' read -r label f v def <<< "$entry"
        swap_port "$f" "$v" "$from" "$to" "$def"
    done
    echo "== Restarting what reads its file only at start"
    # t2s-front and t2s-back reread their own .env on every request (f_envinit, env_load), so editing
    # it is enough. But a variable in the php-fpm PROCESS environment wins over that file, and php-fpm
    # takes its environment from the stack .env (damp-vaugouin-com/.env, env_file) only when the
    # container is created. Recreating php-fpm cuts every PHP page for a few seconds: Apache answers
    # 503 "Service Unavailable" (seen on 2026-11-24, switch 8186 -> 8188). So the API URL must not be
    # in the stack .env; the recreate below is only the safety net while it still is.
    local fpm fpmurl; fpm=$(docker ps --format '{{.Names}}' | grep -m1 php-fpm)
    fpmurl=$([ -n "$fpm" ] && docker exec "$fpm" printenv TEXT2SQL_API_BLUE_URL 2>/dev/null)
    if [ -n "$fpmurl" ]; then
        echo "  WARNING php-fpm carries TEXT2SQL_API_BLUE_URL=$fpmurl in its process env (stack .env):"
        echo "          recreating it, PHP pages answer 503 for a few seconds. Remove TEXT2SQL_API_BLUE_URL"
        echo "          and TEXT2SQL_API_GREEN_URL from $D/damp-vaugouin-com/.env to make switches seamless."
        [ -d "$D/damp-vaugouin-com" ] && (cd "$D/damp-vaugouin-com" && docker compose up -d --no-deps php-fpm)
    else
        echo "  php-fpm: no API URL in its process env; t2s-front and t2s-back reread their .env per request: no restart."
    fi
    # t2s-web reads its .env at start only: /t2s-web/ is down for a few seconds here (FASTAPI-TEXT2SQL-420).
    [ -d "$D/t2s-web" ] && (cd "$D/t2s-web" && docker compose up -d --force-recreate)
    [ -f "$D/listening-companion/.env" ] && (cd "$D/listening-companion" && docker compose up -d --wait --wait-timeout 120)
    if [ -f "$MCP_UPSTREAM.$STAMP" ]; then
        if bash "$D/reverseproxy/reload.sh"; then
            echo "  MCP host: NGINX reloaded, MCP now on :$to (OAuth logins survive: shared signing key and store)."
        else
            cp -p "$MCP_UPSTREAM.$STAMP" "$MCP_UPSTREAM"
            echo "  ERROR MCP host: NGINX reload refused, $MCP_UPSTREAM restored, MCP STAYS ON :$from."
            echo "        Do not restart :$from before MCP is moved (bash $D/reverseproxy/reload.sh after a fix)."
        fi
    fi
    echo "  voice-agent and voice-demo reread their runtime file on the next call (VOICE-AGENT-280): no restart."
    echo
    do_check
    echo
    echo "== Not reachable from here, by hand:"
    echo "  agent-runner (Hostinger): ssh hostinger; sudo sed -i.$STAMP 's#\\(T2S_BASE_URL=.*:\\)$from#\\1$to#' /etc/agent-runner/env && sudo systemctl restart agent-discord-bot"
    echo "  PC tools: image-captioning (.env TEXT2SQL_BASE_URL), source-to-screen (TEXT2SQL_BASE_URL, default :8186 in facts.py)"
    echo "  evaluator: port derived from --api-version (TEXT2SQL-EVAL-011)"
}

case "${1:-check}" in
    check) do_check ;;
    switch) [ $# -eq 3 ] || { echo "usage: $0 switch <from-port> <to-port>"; exit 1; }; do_switch "$2" "$3" ;;
    *) echo "usage: $0 [check | switch <from-port> <to-port>]"; exit 1 ;;
esac
