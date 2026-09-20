#!/bin/sh
# Verify the vision upload path (FASTAPI-TEXT2SQL-275) against a running deployment.
#
# WHAT IT PROVES, in the order of the ticket's acceptance list
#   1. a valid JPEG and a valid PNG are accepted, stored under a name of our own, and the
#      image_ref comes back
#   2. bytes decide the format, not the header: a GIF announced as image/jpeg is refused
#   3. a hostile or simply foreign image_ref determines nothing, it is refused before a path
#      is built from it
#   4. a payload past the ceiling is refused, on the declared Content-Length before any body
#      is read, and again on the streamed count when no length is declared
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
# The key is taken from the first .env that carries one, looked for in three places in this
# order: the repository root (the normal <repo>/eval/ layout), then beside the script itself,
# which is where it lands when eval/ is copied out flat, as ~/docker/text2sql-eval on the VPS
# is, then the working directory. Within a file API_KEYS wins over API_KEY, which wins over
# TEXT2SQL_API_KEY, the evaluator's name for the same X-API-Key value. A KEY already in the
# environment beats all of it. The default host is the blue instance, so green needs BASE_URL.
#
# Usage:
#   sh eval/verif-275.sh
#   BASE_URL=http://172.17.0.1:8187 sh verif-275.sh          # green, from a flat copy
#   BASE_URL=http://172.17.0.1:8186 OTHER_BASE_URL=http://172.17.0.1:8187 sh eval/verif-275.sh
#   docker exec -w /app <container> sh eval/verif-275.sh

set -e

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
REPO_DIR=$(dirname -- "$SCRIPT_DIR")

BASE_URL="${BASE_URL:-http://www.vaugouin.com:8186}"
export BASE_URL REPO_DIR SCRIPT_DIR
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
import http.client
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import zlib

BASE_URL = os.environ["BASE_URL"].rstrip("/")
OTHER_BASE_URL = (os.environ.get("OTHER_BASE_URL") or "").rstrip("/")
REPO_DIR = os.environ["REPO_DIR"]
SCRIPT_DIR = os.environ.get("SCRIPT_DIR") or REPO_DIR

KEY_NAMES = ("API_KEYS", "API_KEY", "TEXT2SQL_API_KEY")


def env_candidates():
    """Directories that may hold the .env, most authoritative first.

    REPO_DIR is the repository root when this script sits in its own eval/ folder, the only
    layout where the file is certainly the API's. SCRIPT_DIR is the same directory when eval/
    has been copied out flat, which is what ~/docker/text2sql-eval on the VPS is. The working
    directory comes last. Duplicates are dropped so a normal run still reports one path.
    """
    ordered = []
    for path in (REPO_DIR, SCRIPT_DIR, os.getcwd()):
        if path and path not in ordered:
            ordered.append(path)
    return ordered


def read_key():
    """KEY from the environment, else the first key name found in the first .env that has one.

    The .env is parsed by hand rather than with python-dotenv: this script has to run in any
    container, including one without that dependency. TEXT2SQL_API_KEY is accepted because the
    evaluator's own .env names the same X-API-Key value that way, and its folder is a place
    this script legitimately runs from.
    """
    key = (os.environ.get("KEY") or "").strip()
    if key:
        return key, "KEY environment variable"
    tried = []
    for directory in env_candidates():
        env_path = os.path.join(directory, ".env")
        tried.append(env_path)
        if not os.path.isfile(env_path):
            continue
        found = {}
        with open(env_path, encoding="utf-8", errors="replace") as handle:
            for line in handle:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                name, _, value = line.partition("=")
                name = name.strip()
                if name in KEY_NAMES:
                    found[name] = value.strip().strip('"').strip("'")
        for name in KEY_NAMES:
            if found.get(name):
                return found[name].split(",")[0].strip(), f"{name} from {env_path}"
    return "", "no .env carrying " + ", ".join(KEY_NAMES) + " in: " + ", ".join(tried)


def call(url, key, method="GET", data=None, content_type=None):
    """Return (status, body_bytes). An HTTP error is a result here, not an exception, and so is
    a connection the server closed on us: status 0, with the reason in place of the body.

    Nothing at this level may raise. One unreachable host used to end the whole run with a stack
    trace where a FAIL line was wanted.
    """
    headers = {"X-API-Key": key}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as error:
        return error.code, error.read()
    except OSError as error:
        return 0, f"{type(error).__name__}: {error}".encode()


def call_headers(url, key):
    """Return (status, headers) for a GET, header names lower-cased.

    `call` above returns the body and drops the headers, which was enough until
    FASTAPI-TEXT2SQL-278 made one of them part of the contract. A missing header is a silence,
    and a silence is exactly what this file exists to turn into a FAIL line.
    """
    request = urllib.request.Request(url, headers={"X-API-Key": key}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.status, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as error:
        return error.code, {k.lower(): v for k, v in (error.headers or {}).items()}
    except OSError as error:
        return 0, {}


def raw_connection(url):
    """A bare HTTPConnection plus the path to request.

    urllib serves every other call here, but it insists on sending the whole body before it will
    look at a response, and both ceiling checks below need exactly the opposite.
    """
    parsed = urllib.parse.urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    opener = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
    return opener(parsed.hostname, port, timeout=60), (parsed.path or "/")


def oversize_declared(url, key, declared):
    """Declare a body past the ceiling and send no body at all.

    The endpoint refuses on the declared Content-Length before reading a single chunk, which is
    precisely the guarantee under test, so the bytes never have to exist. Sending them for real
    is what used to end this script with a stack trace: the server had answered 413 and closed
    while the client was still pushing 26 MB into the socket, so the reset arrived before the
    response could be read. The refusal was correct; only the way of observing it was wrong.
    """
    conn, path = raw_connection(url)
    try:
        conn.putrequest("POST", path, skip_accept_encoding=True)
        conn.putheader("X-API-Key", key)
        conn.putheader("Content-Type", "image/jpeg")
        conn.putheader("Content-Length", str(declared))
        conn.endheaders()
        response = conn.getresponse()
        return response.status, response.read()
    except (OSError, http.client.HTTPException) as error:
        return 0, f"{type(error).__name__}: {error}".encode()
    finally:
        conn.close()


def oversize_streamed(url, key, ceiling):
    """Push past the ceiling with no declared length, so only the streamed guard can stop it.

    That guard is the one which actually enforces, the declared length being a courtesy, and a
    chunked body is the only way to reach it. A reset while writing counts as a refusal here,
    and an early one, but only once the server is shown to be still standing: see the caller.
    """
    conn, path = raw_connection(url)
    block = b"\xff\xd8" + b"\x00" * (1024 * 1024 - 2)
    try:
        conn.putrequest("POST", path, skip_accept_encoding=True)
        conn.putheader("X-API-Key", key)
        conn.putheader("Content-Type", "image/jpeg")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        sent = 0
        while sent < ceiling + len(block):
            conn.send(("%x\r\n" % len(block)).encode() + block + b"\r\n")
            sent += len(block)
        conn.send(b"0\r\n\r\n")
        response = conn.getresponse()
        return response.status, response.read()
    except (OSError, http.client.HTTPException) as error:
        return 0, f"{type(error).__name__}: {error}".encode()
    finally:
        conn.close()


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


def webp_bytes(payload=b"verif-275"):
    """A RIFF/WEBP container carrying the marker, valid by its signature.

    WEBP is the third accepted format since FASTAPI-TEXT2SQL-279, and it is the one that does
    not fit the prefix table in uploads.py: "RIFF" sits at offset 0 and "WEBP" at offset 8,
    with the file length in between. A fixture that only got the first window right would pass
    a sniffer that only checks the first window, which is exactly the bug worth catching.
    """
    body = b"VP8 " + (len(payload) + 4).to_bytes(4, "little") + b"\x00" * 4 + payload
    return b"RIFF" + (len(body) + 4).to_bytes(4, "little") + b"WEBP" + body


def heic_bytes():
    """The opening box of an HEIC file, the format an iPhone produces and this API refuses."""
    return (24).to_bytes(4, "big") + b"ftypheic" + b"\x00" * 12


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
    ("webp deposit", webp_bytes(), "image/webp"),
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
    # FASTAPI-TEXT2SQL-278. The deposit guard is a magic number, not a decode, so a polyglot
    # (JPEG signature plus an HTML or PHP payload) is stored. Nothing executes it here; browser
    # sniffing was the last way it could be read as something else.
    status, headers = call_headers(f"{BASE_URL}/uploads/vision/{image_ref}", key)
    check("read back, with nosniff and an image content type",
          headers.get("x-content-type-options", "").lower() == "nosniff"
          and headers.get("content-type", "").startswith("image/"),
          f"status {status}, type {headers.get('content-type')!r}, "
          f"nosniff {headers.get('x-content-type-options')!r}")

status, body = call(BASE_URL + "/uploads/vision", key, "POST", b"GIF89a" + b"\x00" * 64, "image/jpeg")
check("a GIF announced as image/jpeg is refused", status == 415, f"status {status}")

# FASTAPI-TEXT2SQL-279. HEIC is refused BY DECISION, not by oversight: the vision model does not
# read it, so accepting it would mean decoding it here, on a path that deliberately carries no
# image library. The check is on the message as much as on the status, because a 415 that does
# not name the remedy leaves an iPhone user with no way forward.
status, body = call(BASE_URL + "/uploads/vision", key, "POST", heic_bytes(), "image/heic")
detail = ""
try:
    detail = json.loads(body).get("detail", "")
except Exception:
    detail = str(body[:160])
check("HEIC is refused, and the message says to convert",
      status == 415 and "HEIC" in detail and "JPEG" in detail,
      f"status {status}, {detail[:100]}")

# A RIFF container that is not WEBP must not slip through the two-window check.
status, body = call(BASE_URL + "/uploads/vision", key, "POST",
                    b"RIFF" + (36).to_bytes(4, "little") + b"WAVE" + b"\x00" * 32, "image/webp")
check("a WAV announced as image/webp is refused", status == 415, f"status {status}")

status, body = call(BASE_URL + "/uploads/vision", key, "POST", b"", "image/jpeg")
check("an empty body is refused", status == 400, f"status {status}")

# MAX_UPLOAD_IMAGE_BYTES, the documented default. A deployment that raised it fails the next two
# checks, which is the right answer: they would no longer be testing the ceiling they name.
CEILING = 25 * 1024 * 1024

status, body = oversize_declared(BASE_URL + "/uploads/vision", key, CEILING + 1024)
check("a declared length past the ceiling is refused with 413, before any body is read",
      status == 413, f"status {status}")

status, body = oversize_streamed(BASE_URL + "/uploads/vision", key, CEILING)
if status == 0:
    # A reset is a refusal, but only if the server survived it. Without this, a crash caused by
    # the very request under test would read as a pass, the worst outcome a check can have.
    alive, _ = call(f"{BASE_URL}/uploads/vision/" + "x" * 8, key)
    streamed_ok = alive in (400, 404)
    detail = (f"refused by reset, server still answering ({alive})" if streamed_ok
              else f"connection lost and the server did not answer ({alive})")
else:
    streamed_ok = status == 413
    detail = f"status {status}"
check("a streamed body past the ceiling is refused", streamed_ok, detail)

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
