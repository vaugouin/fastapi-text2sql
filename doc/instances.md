# Instances of the API on the VPS: runbook (FASTAPI-TEXT2SQL-412)

An instance is a clone folder `~/docker/fastapi-text2sql-<name>` plus its own `.env`. The port is `API_PORT` in that `.env`, the name is `INSTANCE_NAME` or else the folder suffix, the container is `fastapi-text2sql-<name>`. The version decides nothing. Principle and client table: `README.md` § *Instances*.

| instance | port | tandem | status on 2026-11-19 |
|---|---|---|---|
| blue | 8186 | even versions, with violet | exists, serves 1.1.20 |
| green | 8187 | odd versions, with brown | exists |
| violet | 8188 | even versions, with blue | to create (section 3) |
| brown | 8189 | odd versions, with green | to create (section 3) |
| ops | none | the crons' clone, never started, no `.env` | to create (section 4) |

The tandem is an operator convention: a new version of a parity goes to whichever instance of its pair is not serving, the clients are switched to it once it reports `bktrees_ready: true`, and the old one keeps running until its in-flight requests are over (up to about 90 s), then can be stopped.

## 1. Migrating the two existing instances (once, before their next restart)

The code of -412 refuses to start without `API_PORT`, and `restart.sh` checks it **before** stopping anything, so a forgotten `.env` costs a message, not an outage. Pulling does not restart anything.

```bash
# blue: one port, its own (keep a copy of the old .env)
cd ~/docker/fastapi-text2sql-blue
cp .env .env.bak-20261119
sed -i -E '/^[[:space:]]*API_PORT_(BLUE|GREEN)[[:space:]]*=/d' .env
printf '\n# FASTAPI-TEXT2SQL-412: this instance only\nAPI_PORT=8186\nINSTANCE_NAME=blue\n' >> .env
grep -nE '^(API_PORT|INSTANCE_NAME|MCP_INTERNAL_BASE_URL)' .env    # API_PORT=8186, INSTANCE_NAME=blue; no MCP_INTERNAL_BASE_URL pinned to another port
git pull --ff-only

# green: the same with 8187
cd ~/docker/fastapi-text2sql-green
cp .env .env.bak-20261119
sed -i -E '/^[[:space:]]*API_PORT_(BLUE|GREEN)[[:space:]]*=/d' .env
printf '\n# FASTAPI-TEXT2SQL-412: this instance only\nAPI_PORT=8187\nINSTANCE_NAME=green\n' >> .env
grep -nE '^(API_PORT|INSTANCE_NAME|MCP_INTERNAL_BASE_URL)' .env
git pull --ff-only
```

When to restart: the running containers keep their old code until restarted, and nothing forces it. Restart green when convenient (`bash restart.sh` in its folder). Leave blue, which serves, untouched: it will move to the new code the day violet takes over (section 5), or at its next planned restart.

## 2. Firewall: the two new ports (before the first test)

Each instance runs `--network host`, so ufw really filters its port. The rules are those of 8186 / 8187, copied to 8188 / 8189. They are recorded in the server reference (`t2s-backlog/topics/debian-migration/debian-10-to-12-migration.md`, §4.2b, rule 5f).

```bash
for p in 8188 8189; do
  sudo ufw allow from 127.0.0.1        to any port $p proto tcp comment 'text2sql API violet/brown, loopback'
  sudo ufw allow from 172.16.0.0/12    to any port $p proto tcp comment 'text2sql API violet/brown, docker bridges'
  sudo ufw allow from 192.168.128.0/20 to any port $p proto tcp comment 'text2sql API violet/brown, docker bridges'
  sudo ufw allow from 151.80.152.102   to any port $p proto tcp comment 'text2sql API violet/brown, masqueraded case'
done
sudo ufw allow from 90.25.192.222 to any port 8188,8189 proto tcp comment 'home Philippe (dynamic, recheck)'
sudo ufw allow from 153.53.87.77  to any port 8188,8189 proto tcp comment 'VPN dedicated IP'
sudo ufw allow from 100.85.106.31 to any port 8188,8189 proto tcp comment 'agent-runner Discord bot, Hostinger via Tailscale'
sudo ufw status | grep -E '818[6-9]'    # every source of 8186 also on 8188, every source of 8187 also on 8189
```

If `ufw status` shows a rule on 8186 that the list above lacks (a source added since), copy it to 8188 and 8189 as well, then add it to rule 5f of the server reference.

## 3. Creating violet and brown

```bash
# violet, tandem of blue
git clone https://github.com/vaugouin/fastapi-text2sql.git ~/docker/fastapi-text2sql-violet
cd ~/docker/fastapi-text2sql-violet
cp ~/docker/fastapi-text2sql-blue/.env .env
sed -i -E '/^[[:space:]]*(API_PORT|INSTANCE_NAME)[[:space:]]*=/d' .env
printf 'API_PORT=8188\nINSTANCE_NAME=violet\n' >> .env
chmod 600 .env
grep -nE '^(API_PORT|INSTANCE_NAME)' .env

# brown, tandem of green
git clone https://github.com/vaugouin/fastapi-text2sql.git ~/docker/fastapi-text2sql-brown
cd ~/docker/fastapi-text2sql-brown
cp ~/docker/fastapi-text2sql-green/.env .env
sed -i -E '/^[[:space:]]*(API_PORT|INSTANCE_NAME)[[:space:]]*=/d' .env
printf 'API_PORT=8189\nINSTANCE_NAME=brown\n' >> .env
chmod 600 .env
grep -nE '^(API_PORT|INSTANCE_NAME)' .env
```

Both clones carry `main`, i.e. version 1.1.20 today. Brown has nothing of its own to serve until 1.1.21 exists: create it now, start it when an odd version needs it.

**Memory before starting a third or fourth instance.** Each instance builds its own BK-trees and title lexicons in RAM. Check before starting one, and stop an idle tandem instance rather than keeping four warm:

```bash
free -h
docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}' | grep fastapi-text2sql
```

Starting violet (it serves nobody until a client is pointed at it):

```bash
cd ~/docker/fastapi-text2sql-violet && bash restart.sh
KEY=$(grep -E '^API_KEYS=' .env | cut -d= -f2- | cut -d, -f1 | tr -d '"'\''\r')
curl -s -H "X-API-Key: $KEY" http://127.0.0.1:8188/ | python3 -c "import sys,json;d=json.load(sys.stdin);print({k:d.get(k) for k in ('instance','api_version','bktrees_ready')})"
# expected: {'instance': 'violet', 'api_version': '1.1.20', 'bktrees_ready': ...}; wait for True
```

`restart.sh` refuses if another `.env` declares the same port, or if the port is still in use once its own container is stopped.

## 4. The crons leave the blue clone

`archive-logs.sh` and `purge-uploads.sh` work on `shared_data`, not on an instance. They now run from a clone that is no instance: no `.env`, so `restart.sh` refuses to start it.

```bash
git clone https://github.com/vaugouin/fastapi-text2sql.git ~/docker/fastapi-text2sql-ops
ls -l ~/docker/fastapi-text2sql-ops/archive-logs.sh ~/docker/fastapi-text2sql-ops/purge-uploads.sh   # both -rwxr-xr-x

# Repoint the two lines, in whichever crontab holds them (the user's, and check root's)
crontab -l | grep -nE 'archive-logs|purge-uploads'
sudo crontab -l 2>/dev/null | grep -nE 'archive-logs|purge-uploads'
crontab -l > ~/crontab.bak-20261119
sed -E 's#fastapi-text2sql-(blue|green)/(archive-logs|purge-uploads)\.sh#fastapi-text2sql-ops/\2.sh#' ~/crontab.bak-20261119 | crontab -
crontab -l | grep -nE 'archive-logs|purge-uploads'    # both lines now in fastapi-text2sql-ops
# If they were in root's crontab, the same with sudo crontab -l / sudo crontab -.
```

Dry run, harmless: `~/docker/fastapi-text2sql-ops/purge-uploads.sh --dry-run`. Updating the ops clone later: `git pull --ff-only` in it, like any clone.

## 5. Switching the clients to another instance

Example: 1.1.20 with new code, from blue to violet, no version bump.

1. `git pull --ff-only` in violet, `bash restart.sh`, wait for `bktrees_ready: true` (section 3 command).
2. Switch each client (`README.md` § *Instances*, client table): t2s-front (`TEXT2SQL_API_BLUE_URL` to `:8188`, or its colour line), voice-agent (`TEXT2SQL_BASE_URL`, then its `restart.sh`), agent-runner (`T2S_BASE_URL` on Hostinger). The evaluator reaches only blue and green until TEXT2SQL-EVAL-011.
3. Check each client reports `instance: violet` where it exposes it (`/voice-agent/tool/health` exposes `api_version` only until its next version; `GET /` of the instance always does).
4. Leave blue running a couple of minutes (in-flight requests, up to about 90 s), then `docker stop fastapi-text2sql-blue` if the memory is needed.

**Same version on two instances shares the SQL cache** (`T_WC_T2S_CACHE` is keyed on the version): a fix that changes generated SQL without a bump will be shadowed by cache rows written by the old code. Retire those rows as usual (`maintenance/AGENTS.md`), or bump.

## 6. Known gaps after this runbook (tickets)

- data-monitoring knows the container names `fastapi-text2sql-blue`, `-green`, `fastapi-text2sql` only: violet and brown are not watched (DATA-MONITORING-007).
- The evaluator still derives its port from the version parity (TEXT2SQL-EVAL-011).
- t2s-front holds two URLs and one colour line (T2S-FRONT-022).
- voice-agent needs a recreate to change `TEXT2SQL_BASE_URL` (VOICE-AGENT-278).
- t2s-web accepts `blue` and `green` only (T2S-WEB-016).
