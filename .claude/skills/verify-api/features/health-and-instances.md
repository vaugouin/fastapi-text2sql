# Instances, readiness, identity

## Sub-features
- `GET /` returns `instance` (blue, green, violet, brown), `api_version`, `bktrees_ready`, and `lexicons` (title lexicons built, rows and date).
- Four production instances answer over Tailscale on `100.113.161.122`: 8186 blue, 8187 green, 8188 violet, 8189 brown. Two run at a time (even versions on blue and violet, odd on green and brown, by convention only).
- The live public instance is the one `reverseproxy/includes/t2s-api-live.conf` points to; `verify_api.py` reads that file when the `reverseproxy` checkout sits next to this repo, and uses it as the default port.

## How to get to it
`GET /` with `X-API-Key`. No token spent, nothing written except a usage log line.

## Driving it
- `verify_api.py instances`: one line per port, `<= live` on the public one, `connection refused` for a stopped instance.
- `verify_api.py doctor [--port N]`: `GET /`, the fast path, `GET /movies/15`, `GET /samples`; verdict HEALTHY or NOT HEALTHY, evidence JSON.

## Gotchas
- **Ready means `bktrees_ready: true`**, not "answers 200": the BK-tree warm-up runs for minutes after a restart and competes for CPU. Never judge latency or resolution on a warming instance.
- The version does not tell which instance answered (two may run the same version): read `instance`.
- After a redeploy without a version bump, prove the new code with a field only the new code emits, on the fast path (`tt0033467`).
