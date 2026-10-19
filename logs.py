import os
import json
import hashlib
from datetime import datetime
from zoneinfo import ZoneInfo

LOGS_FOLDER = "logs"

# FASTAPI-TEXT2SQL-328 (DEPLOYMENT-015): one clock for the T2S stack. Every date a human reads
# (log and upload file names, the "ts" inside each log JSON, the startup banner) is Europe/Paris
# time, and when written in full it carries its offset (2026-10-19T14:59:03+02:00). Always the
# zone, never a fixed +02:00, so the October and March changes are followed. The container sets
# no TZ and the VPS host stays on Etc/UTC, which is why the zone is named here rather than read
# from the system; the tzdata package in requirements.txt supplies the zone database the slim
# image lacks. Names written before the switch (2026-10-19, effective at the next deployment)
# are UTC with no offset: see AGENTS.md, "One clock".
PARIS_TZ = ZoneInfo("Europe/Paris")


def now_paris():
    """Return the current time as an aware datetime in Europe/Paris.

    Returns:
        datetime: Aware datetime; isoformat() carries the offset (+01:00 or +02:00).
    """
    return datetime.now(PARIS_TZ)


def f_getlogfilename(endpoint, contenttext, strapiversion, now=None):
    """Generate a unique log filename based on endpoint, timestamp, and content hash.

    Creates a filename in the format: YYYYMMDD-HHMMSS_endpoint_version_hash.json
    Ensures the logs folder exists before generating the filename.

    Args:
        endpoint (str): The API endpoint name (e.g., 'hello', 'text2sql')
        contenttext (str): The content to be logged (used for MD5 hash)
        strapiversion (str): The current API version string
        now (datetime, optional): The moment to stamp, Paris time; defaults to now_paris().
            log_usage passes the same moment it writes as "ts", so name and record agree.

    Returns:
        str: Complete path to the log file
    """
    os.makedirs(LOGS_FOLDER, exist_ok=True)
    if now is None:
        now = now_paris()
    date_time_str = now.strftime("%Y%m%d-%H%M%S")
    md5_hash = hashlib.md5(contenttext.encode('utf-8')).hexdigest()
    filename = f"{LOGS_FOLDER}/{date_time_str}_{endpoint}_{strapiversion}_{md5_hash}.json"
    return filename

def log_usage(endpoint, content, strapiversion):
    """Log API usage data to a JSON file.

    Serializes the provided content to JSON format with custom handling for
    Decimal and datetime objects, then writes it to a uniquely named log file.

    Args:
        endpoint (str): The API endpoint name for log categorization
        content (dict): The data to be logged (request/response information)
        strapiversion (str): The current API version string

    Note:
        Creates log files only if they don't already exist to avoid overwrites.
        Uses UTF-8 encoding and pretty-printed JSON format.
        A dict content gets "ts" as its first key: the moment of the log in Paris time with its
        offset (FASTAPI-TEXT2SQL-328). It is the reference time of the record; the file name
        carries the same moment without offset, for humans, and repeats 02:00 to 03:00 on the
        last Sunday of October. A caller's own "ts" key, if any, is left as it is.
    """
    def decimal_serializer(obj):
        """JSON serializer for objects not serializable by default json code"""
        from decimal import Decimal
        import datetime

        if isinstance(obj, Decimal):
            return float(obj)
        elif isinstance(obj, (datetime.date, datetime.datetime)):
            return obj.isoformat()
        raise TypeError(f"Object of type {obj.__class__.__name__} is not JSON serializable")

    now = now_paris()
    if isinstance(content, dict) and "ts" not in content:
        content = {"ts": now.isoformat(timespec="seconds"), **content}
    contenttext = json.dumps(content, indent=4, ensure_ascii=False, default=decimal_serializer)
    log_filename = f_getlogfilename(endpoint, contenttext, strapiversion, now)
    # Create the JSON file if it doesn't exist
    if not os.path.exists(log_filename):
        with open(log_filename, 'w', encoding='utf-8') as file:
            file.write(contenttext)


def log_hot_reload(filename):
    content = {
        "message": f"Hot-loaded data file: {filename}",
        "filename": filename,
        "event": "data_hot_reload",
        "timestamp": now_paris().isoformat(timespec="seconds"),
    }
    log_usage("data_hot_reload", content, "hot_reload")
