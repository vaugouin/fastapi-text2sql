import os
import re
import hashlib
from datetime import datetime, timedelta

# FASTAPI-TEXT2SQL-275: the first binary input path of this repo. Everything else here is JSON
# in and JSON out; this module owns the bytes.
#
# UPLOADS_FOLDER is RELATIVE on purpose, exactly like LOGS_FOLDER in logs.py, and for the same
# reason: on the VPS the host directory /home/debian/docker/shared_data/fastapi-text2sql/uploads
# is bind-mounted on /app/uploads by both restart scripts, so blue, green and the colourless
# third deployment write into one folder and an image deposited on one colour is readable from
# the others. The application knows nothing about that mount, and a laptop checkout keeps its
# own uploads/ folder with no condition in the code. Making this absolute would re-split the
# folder per colour, silently, which is worse than an outage: a replay would simply not find
# its image after a flip.
UPLOADS_FOLDER = os.getenv("UPLOADS_FOLDER", "uploads")

# The vision/ level is not decorative. The purge deletes what it finds, so it must be aimed at a
# directory that holds nothing else: the run log of the purge, and any future kind of deposit,
# live beside it under uploads/, never inside it.
VISION_KIND = "vision"
VISION_FOLDER = os.path.join(UPLOADS_FOLDER, VISION_KIND)

# Retention: a sliding 30-day purge, run by purge-uploads.sh from the host crontab. This is the
# OPPOSITE regime to logs/, which is archived monthly and kept without limit (README, "Why these
# logs are kept"). The two folders are neighbours under the same parent and obey inverse rules;
# the rule belongs on each folder, never on the parent.
UPLOAD_RETENTION_DAYS = int(os.getenv("UPLOAD_RETENTION_DAYS", "30"))

# 25 MB, the ceiling voice-agent already applies to its transcription audio
# (app/main.py MAX_TRANSCRIPTION_AUDIO_BYTES). A phone photo is 2 to 5 MB.
MAX_UPLOAD_IMAGE_BYTES = int(os.getenv("MAX_UPLOAD_IMAGE_BYTES", str(25 * 1024 * 1024)))

# The format is decided by the bytes, never by the Content-Type header and never by a filename.
# A client-supplied name is a path-traversal surface and is not read anywhere in this module.
_MAGIC_NUMBERS = (
    (b"\xff\xd8\xff", "jpg"),
    (b"\x89PNG\r\n\x1a\n", "png"),
)

# WEBP is a RIFF container, so its signature sits in TWO windows, "RIFF" at 0 and "WEBP" at
# 8, with the file length in between. It cannot join the prefix table above, which is the
# only reason it has its own branch in sniff_image_format. Accepted since
# FASTAPI-TEXT2SQL-279 because it costs one signature and nothing else: OpenAI reads WEBP
# natively, so nothing has to decode or convert it here.
_WEBP_RIFF = b"RIFF"
_WEBP_FORM = b"WEBP"

# **HEIC is refused on purpose, and that is a decision rather than an omission**
# (FASTAPI-TEXT2SQL-279, arbitrage de Philippe, 2026-09-20). An iPhone photo taken from the
# library is often HEIC, so the temptation is real. But the vision model does not read HEIC,
# so accepting it would mean converting it here, which means adding an image decoder to a
# path that deliberately has none: no PIL, no ImageMagick, therefore no decoder CVE surface
# on bytes a stranger chose. The clients already resize to JPEG before depositing
# (VOICE-AGENT-179, TMDB-FRONT-088), so the conversion belongs there, where the photo is
# still in the hands of the person who took it. The 415 says so instead of leaving the
# caller guessing.
_MEDIA_TYPES = {"jpg": "image/jpeg", "png": "image/png", "webp": "image/webp"}

# What the deposit accepts, in the words the client gets back on a 415.
ACCEPTED_FORMATS = "JPEG, PNG or WEBP"

# YYYYMMDD-HHMMSS_vision_<version>_<md5 of the bytes>.<ext>, the house convention of
# logs.f_getlogfilename with the payload hash taken over bytes instead of text.
_IMAGE_REF_PATTERN = re.compile(
    r"^(?P<stamp>\d{8}-\d{6})_(?P<kind>[a-z][a-z0-9]*)_"
    r"(?P<version>[A-Za-z0-9][A-Za-z0-9._-]*)_(?P<md5>[0-9a-f]{32})\.(?P<ext>jpg|png|webp)$"
)


class UploadRefInvalid(ValueError):
    """Raised when an image_ref does not match the house filename convention.

    The guard is the whole point: an image_ref arrives from a client, and a client-supplied
    string must never reach the filesystem as a path. Anything the generator could not have
    produced is refused before a path is built from it.
    """


class UploadUnavailable(LookupError):
    """Raised when a well-formed image_ref points at no file on disk.

    The likeliest cause by far is the 30-day purge, which is why the message says so with the
    deposit date rather than letting a bare FileNotFoundError surface as a stack trace. The JSON
    log of the turn outlives the image it names, so this is the normal end state of every replay
    attempted more than a month later, not an exceptional failure.
    """


def sniff_image_format(imagebytes):
    """Identify an image by its magic number, ignoring any declared type.

    Args:
        imagebytes (bytes): The first twelve bytes of the payload, or all of them.

    Returns:
        str or None: "jpg", "png", "webp", or None when the bytes are none of the three.
        HEIC, GIF, SVG and everything else return None on purpose; see _MEDIA_TYPES.
    """
    for magic, extension in _MAGIC_NUMBERS:
        if imagebytes[:len(magic)] == magic:
            return extension
    if imagebytes[:4] == _WEBP_RIFF and imagebytes[8:12] == _WEBP_FORM:
        return "webp"
    return None


def media_type_for(extension):
    """Return the HTTP media type for a stored image extension.

    Args:
        extension (str): "jpg", "png" or "webp".

    Returns:
        str: The matching media type, defaulting to application/octet-stream.
    """
    return _MEDIA_TYPES.get(extension, "application/octet-stream")


def f_getuploadfilename(kind, imagebytes, strapiversion, strextension):
    """Generate a unique upload filename from the deposit time and the payload bytes.

    Twin of logs.f_getlogfilename, deliberately: the same YYYYMMDD-HHMMSS_<kind>_<version>_<md5>
    shape, so a JSON log file and the image it names sort and pair the same way. The one
    difference is load-bearing: the hash is taken over the RAW BYTES, not over
    contenttext.encode('utf-8'), so f_getlogfilename cannot be reused as is.

    The timestamp and the hash do different jobs. The timestamp gives chronological order and
    the purge its horizon; the hash gives uniqueness and the pairing with the JSON log. The same
    photo deposited twice yields two files, one second apart, and that is accepted:
    de-duplication is not the goal here.

    Args:
        kind (str): The deposit kind, currently only "vision".
        imagebytes (bytes): The image payload, hashed as is.
        strapiversion (str): The current API version string.
        strextension (str): The extension decided by the magic number ("jpg", "png" or
            "webp").

    Returns:
        str: Complete path to the image file, under UPLOADS_FOLDER/<kind>/.
    """
    folder = os.path.join(UPLOADS_FOLDER, kind)
    os.makedirs(folder, exist_ok=True)
    now = datetime.now()
    date_time_str = now.strftime("%Y%m%d-%H%M%S")
    md5_hash = hashlib.md5(imagebytes).hexdigest()
    filename = f"{date_time_str}_{kind}_{strapiversion}_{md5_hash}.{strextension}"
    return os.path.join(folder, filename)


def store_vision_image(imagebytes, strapiversion):
    """Write an image to uploads/vision/ under a name of our own and return its reference.

    Args:
        imagebytes (bytes): The validated image payload.
        strapiversion (str): The current API version string.

    Returns:
        dict: image_ref (the bare filename, which is what a client sends back on later turns),
            path, bytes, image_format, deposited_at and purge_after.

    Raises:
        ValueError: If the bytes are none of the three accepted formats. The size ceiling is
            enforced by
            the caller, which streams the request and must never buffer a payload past it.

    Note:
        Never overwrites an existing file, like logs.log_usage: an identical name means the same
        payload at the same second, so the file already on disk is the right one.
    """
    image_format = sniff_image_format(imagebytes)
    if image_format is None:
        raise ValueError(f"payload is not one of {ACCEPTED_FORMATS} (checked on the bytes)")

    path = f_getuploadfilename(VISION_KIND, imagebytes, strapiversion, image_format)
    if not os.path.exists(path):
        with open(path, "wb") as file:
            file.write(imagebytes)

    image_ref = os.path.basename(path)
    return {
        "image_ref": image_ref,
        "path": path,
        "bytes": len(imagebytes),
        "image_format": image_format,
        "deposited_at": deposited_at(image_ref).isoformat(),
        "purge_after": purge_after(image_ref).isoformat(),
    }


def parse_image_ref(image_ref):
    """Validate a client-supplied image_ref and return its components.

    Args:
        image_ref (str): The filename returned by a deposit.

    Returns:
        dict: stamp, kind, version, md5 and ext.

    Raises:
        UploadRefInvalid: If the reference is not exactly one generated filename. A separator, a
            parent segment, or anything else the generator cannot produce is refused here,
            before any path is built.
    """
    candidate = str(image_ref or "")
    if (candidate != os.path.basename(candidate)
            or "/" in candidate
            or "\\" in candidate
            or ".." in candidate):
        raise UploadRefInvalid(f"image_ref is not a bare filename: {candidate!r}")
    match = _IMAGE_REF_PATTERN.match(candidate)
    if not match:
        raise UploadRefInvalid(f"image_ref does not match the upload naming convention: {candidate!r}")
    return match.groupdict()


def deposited_at(image_ref):
    """Return the deposit datetime read off the reference itself.

    Args:
        image_ref (str): The filename returned by a deposit.

    Returns:
        datetime: The moment the file was named, which is the moment it was written.

    Raises:
        UploadRefInvalid: If the reference is malformed.
    """
    parts = parse_image_ref(image_ref)
    return datetime.strptime(parts["stamp"], "%Y%m%d-%H%M%S")


def purge_after(image_ref):
    """Return the date from which the purge is entitled to delete this image.

    Args:
        image_ref (str): The filename returned by a deposit.

    Returns:
        datetime: Deposit time plus UPLOAD_RETENTION_DAYS.

    Raises:
        UploadRefInvalid: If the reference is malformed.
    """
    return deposited_at(image_ref) + timedelta(days=UPLOAD_RETENTION_DAYS)


def vision_image_path(image_ref):
    """Turn a validated reference into the path of the file it names.

    Args:
        image_ref (str): The filename returned by a deposit.

    Returns:
        str: Path under uploads/vision/. The file may not exist.

    Raises:
        UploadRefInvalid: If the reference is malformed.
    """
    parts = parse_image_ref(image_ref)
    return os.path.join(UPLOADS_FOLDER, parts["kind"], image_ref)


def load_vision_image(image_ref):
    """Read back a deposited image, for a replay or for a later turn of the conversation.

    Args:
        image_ref (str): The filename returned by a deposit.

    Returns:
        tuple: (bytes, str) the payload and its media type.

    Raises:
        UploadRefInvalid: If the reference is malformed.
        UploadUnavailable: If the file is gone, with the purge stated explicitly when the
            deposit is older than the retention window. This is the expected outcome of an old
            replay and must read as such, never as a stack trace.
    """
    parts = parse_image_ref(image_ref)
    path = vision_image_path(image_ref)
    if not os.path.exists(path):
        deposit = deposited_at(image_ref)
        horizon = purge_after(image_ref)
        if datetime.now() >= horizon:
            raise UploadUnavailable(
                f"image {image_ref} is gone: deposited {deposit.date().isoformat()}, "
                f"purged after {UPLOAD_RETENTION_DAYS} days (on or after {horizon.date().isoformat()}). "
                "The JSON log of the turn outlives the image it names."
            )
        raise UploadUnavailable(
            f"image {image_ref} is not in {VISION_FOLDER}, and it is not the purge: "
            f"deposited {deposit.date().isoformat()}, retained until {horizon.date().isoformat()}. "
            "Check the uploads mount of this deployment."
        )
    with open(path, "rb") as file:
        imagebytes = file.read()
    return imagebytes, media_type_for(parts["ext"])
