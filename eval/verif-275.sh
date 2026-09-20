#!/bin/sh
# Verify the vision upload path (FASTAPI-TEXT2SQL-275) against a running deployment.
#
# WHAT IT PROVES, in the order of the ticket's acceptance list
#   1. a valid JPEG and a valid PNG are accepted, stored under a name of our own, and the
#      image_ref comes back
#   2. bytes decide the format, not the header: a GIF announced as image/jpeg is refused
#   3. a hostile or simply foreign image_ref determines nothing, it is refused before a path
#      is built from it
#   4. a payload past the ceiling is refused with 413
#   5. the deposit is readable again, byte for byte
#   6. a reference whose image is past the retention window answers 410 with a date, never a
#      stack trace: that is the normal end of an old replay
#   7. with OTHER_BASE_URL set, the image deposited on one colour is read back from the OTHER
#      one. This is the only check here that cannot be done on a laptop, and it is the one
#      that proves the shared uploads mount. Without it a flip makes a replay fail in silence.
#
# NEITHER CURL NOR BASH, ON PURPOSE
# The container image is python:3.12-slim-bookworm, which carries no curl. Everything goes
# through python3 and its standard library, and the shebang is /bin/sh with no bashism, so the
# script runs in the container as well as on the workstation.
#
# KEY AND HOST
# The key is read from the repo's .env (API_KEYS, else API_KEY), next to this eval/ folder. A
# KEY already in the environment wins. The default host is the blue instance.
#
# Usage:
#   sh eval/verif-275.sh
#   BASE_URL=http://172.17.0.1:8186 OTHER_BASE_URL=http://172.17.0.1:8187 sh eval/verif-275.sh
#   docker exec -w /app <container> sh eval/verif-275.sh

set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(dirname -- "$SCRIPT_DIR")

BASE_URL="${BASE_URL:-http://www.vaugouin.com:8186}"
export BASE_URL REPO_DIR
export KEY="${KEY:-}"
export OTHER_BASE_URL="${OTHER_BASE_URL:-}"

PY_BIN=""
for candidate in "${PYTHON:-}" python3 python; do
    [ -n "$candidate" ] || continue
    if "$candidate" -c "import sys" >/dev/null 2>&1; then
        PY_BIN="$candidate"
        break
    fi
done
if [ -z "$PY_BIN" ]; then
    echo "No usable Python interpreter. Set PYTHON=<path> if needed." >&2
    exit 1
fi

"$PY_BIN" - <<'PYTHON'
import json
import os
import sys
import urllib.error
import urllib.request
import zlib

BASE_URL = os.environ["BASE_URL"].rstrip("/")
OTHER_BASE_URL = (os.environ.get("OTHER_BASE_URL") or "").rstrip("/")
REPO_DIR = os.environ["REPO_DIR"]


def read_key():
    """KEY from the environment, else API_KEYS then API_KEY from the repo .env.

    The .env is parsed by hand rather than with python-dotenv: this script has to run in any
    container, including one without that dependency.
    """
    key = (os.environ.get("KEY") or "").strip()
    if key:
        return key, "KEY environment variable"
    env_path = os.path.join(REPO_DIR, ".env")
    if not os.path.isfile(env_path):
        return "", f"not found ({env_path} missing)"
    found = {}
    with open(env_path, encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            name, _, value = line.partition("=")
            name = name.strip()
            if name in ("API_KEYS", "API_KEY"):
                found[name] = value.strip().strip('"').strip("'")
    for name in ("API_KEYS", "API_KEY"):
        if found.get(name):
            return found[name].split(",")[0].strip(), f"{name} from .env"
    return "", "neither API_KEYS nor API_KEY in .env"


def call(url, key, method="GET", data=None, content_type=None):
    """Return (status, body_bytes). An HTTP error is a result here, not an exception."""
    headers = {"X-API-Key": key}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()


def png_bytes(payload=b"verif-275"):
    """A minimal but genuinely valid 1x1 PNG, built here so the script stays self-contained."""
    def chunk(kind, body):
        return (len(body).to_bytes(4, "big") + kind + body
                + zlib.crc32(kind + body).to_bytes(4, "big"))
    header = b"\x89PNG\r\n\x1a\n"
    ihdr = chunk(b"IHDR", (1).to_bytes(4, "big") + (1).to_bytes(4, "big") + bytes([8, 2, 0, 0, 0]))
    idat = chunk(b"IDAT", zlib.compress(b"\x00\xff\x00\x00"))
    text = chunk(b"tEXt", b"verif\x00" + payload)
    return header + ihdr + idat + text + chunk(b"IEND", b"")


def jpeg_bytes(payload=b"verif-275"):
    """SOI + APP0 JFIF + a comment carrying the marker + EOI. Enough to be a JPEG by its bytes."""
    app0 = b"\xff\xe0" + (16).to_bytes(2, "big") + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    comment = b"\xff\xfe" + (len(payload) + 2).to_bytes(2, "big") + payload
    return b"\xff\xd8" + app0 + comment + b"\xff\xd9"


key, key_origin = read_key()
if not key:
    print(f"No API key: {key_origin}", file=sys.stderr)
    sys.exit(1)
print(f"host   {BASE_URL}")
print(f"key    {key_origin}")

failures = []


def check(label, condition, detail=""):
    print(f"{'ok  ' if condition else 'FAIL'}  {label}{(': ' + detail) if detail else ''}")
    if not condition:
        failures.append(label)

refs = {}
for label, payload, content_type in (
    ("jpeg deposit", jpeg_bytes(), "image/jpeg"),
    ("png deposit, with a lying Content-Type", png_bytes(), "text/plain"),
):
    status, body = call(BASE_URL + "/uploads/vision", key, "POST", payload, content_type)
    data = json.loads(body) if status == 200 else {}
    check(label, status == 200, f"status {status} {data.get('image_ref', body[:80])}")
    if status == 200:
        refs[data["image_ref"]] = payload
        check(f"{label}: name follows the house convention",
              data["image_ref"].count("_") == 3 and data["image_ref"][8] == "-",
              data["image_ref"])
        check(f"{label}: retention is announced", data.get("retention_days") == 30,
              f"purge_after {data.get('purge_after')}")

for image_ref, payload in refs.items():
    status, body = call(f"{BASE_URL}/uploads/vision/{image_ref}", key)
    check("read back, byte for byte", status == 200 and body == payload,
          f"status {status}, {len(body)} bytes")

status, body = call(BASE_URL + "/uploads/vision", key, "POST", b"GIF89a" + b"\x00" * 64, "image/jpeg")
check("a GIF announced as image/jpeg is refused", status == 415, f"status {status}")

status, body = call(BASE_URL + "/uploads/vision", key, "POST", b"", "image/jpeg")
check("an empty body is refused", status == 400, f"status {status}")

# The trailing filler sits after the EOI marker: still a JPEG by its first bytes, and
# refused on size before anything else is even looked at.
status, body = call(BASE_URL + "/uploads/vision", key, "POST",
                    jpeg_bytes() + b"x" * (26 * 1024 * 1024), "image/jpeg")
check("a payload past the ceiling is refused with 413", status == 413, f"status {status}")

for label, bad_ref in (
    ("a client filename determines nothing", "poster.jpg"),
    ("a traversal attempt is refused", "..%2F..%2Fetc%2Fpasswd"),
    ("a name that is not ours is refused", "x" * 200 + ".jpg"),
):
    status, body = call(f"{BASE_URL}/uploads/vision/{bad_ref}", key)
    check(label, status in (400, 404), f"status {status}")

purged_ref = "20200101-120000_vision_1.1.19_" + "a" * 32 + ".jpg"
status, body = call(f"{BASE_URL}/uploads/vision/{purged_ref}", key)
detail = ""
try:
    detail = json.loads(body).get("detail", "")
except Exception:
    detail = str(body[:120])
check("a replay past the retention window says so, with a date",
      status == 410 and "purged" in detail, f"status {status}, {detail[:90]}")

if OTHER_BASE_URL:
    for image_ref, payload in refs.items():
        status, body = call(f"{OTHER_BASE_URL}/uploads/vision/{image_ref}", key)
        check("deposited on one colour, read back from the other (shared mount)",
              status == 200 and body == payload, f"{OTHER_BASE_URL} status {status}")
else:
    print("skip  cross-colour read: set OTHER_BASE_URL to the other colour to prove the shared mount")

print()
if failures:
    print(f"{len(failures)} check(s) failed: " + "; ".join(failures))
    sys.exit(1)
print("all checks passed")
PYTHON
