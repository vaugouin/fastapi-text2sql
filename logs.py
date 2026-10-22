import os
import json
import time
import hashlib
import contextvars
import threading
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

import llm_costs

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


# FASTAPI-TEXT2SQL-337. The cost price of a call needs its server time, and only /search had
# one (total_processing_time); the entity endpoints, which spend no token, logged none at all.
# The _RequestClock middleware of main.py starts this clock as each HTTP request enters, and
# log_usage stamps every log written during the request with what it has taken so far.
_request_clock: "contextvars.ContextVar" = contextvars.ContextVar("request_clock", default=None)


# FASTAPI-TEXT2SQL-338. cpu_time counts the API process only; MariaDB and ChromaDB work in
# their own containers, and neither tells a client how much CPU one query took. What the API
# can measure is how long it WAITED for them, so it times every SQL statement (the cursor
# class of main.get_db_connection) and every ChromaDB call (chroma_call). The accumulator is
# a dict installed with the clock and mutated in place: the endpoint's child task (the bearer
# middleware) and its asyncio.to_thread workers get a copy of the context, hence the SAME
# dict, and two workers can add to it at once (entity resolution overlaps the text2sql call).
_backend_usage: "contextvars.ContextVar" = contextvars.ContextVar("backend_usage", default=None)
_backend_lock = threading.Lock()
# Embedding seconds spent by THIS thread: a ChromaDB query embeds its text client-side, through
# OpenAI, and that wait is the provider's, already priced by its tokens, not ChromaDB's work.
_thread_waits = threading.local()


def start_request_clock():
    """Note the wall clock and the process CPU clock as the current request enters."""
    _request_clock.set((time.perf_counter(), time.process_time()))
    _backend_usage.set({"sql_calls": 0, "sql_time": 0.0, "sql_rows": 0,
                        "chroma_calls": 0, "chroma_time": 0.0})


def record_sql(seconds, rows):
    """Add one SQL statement to the request's accounting; a no-op outside a request."""
    usage = _backend_usage.get()
    if usage is None:
        return
    with _backend_lock:
        usage["sql_calls"] += 1
        usage["sql_time"] += seconds
        usage["sql_rows"] += max(int(rows or 0), 0)


def record_embedding_wait(seconds):
    """Note an OpenAI embeddings round trip made by this thread (see chroma_call)."""
    _thread_waits.embedding = getattr(_thread_waits, "embedding", 0.0) + seconds


@contextmanager
def chroma_call():
    """Time one ChromaDB call, minus the embedding round trip it made inside, for the request."""
    start = time.perf_counter()
    embedding_before = getattr(_thread_waits, "embedding", 0.0)
    try:
        yield
    finally:
        usage = _backend_usage.get()
        if usage is not None:
            embedding = getattr(_thread_waits, "embedding", 0.0) - embedding_before
            with _backend_lock:
                usage["chroma_calls"] += 1
                usage["chroma_time"] += max(time.perf_counter() - start - embedding, 0.0)


def request_clock_readings():
    """Return {"server_time", "cpu_time"} in seconds since the request entered, {} outside one.

    server_time is the wall time inside the API, network and NGINX excluded. cpu_time is the
    CPU the whole process spent meanwhile, every thread included: the right figure for a
    /search, whose work runs in worker threads, but it also counts any request served at the
    same moment. At a few dozen calls a day overlap is rare; read a median, not one record.
    """
    clock = _request_clock.get()
    if clock is None:
        return {}
    wall_start, cpu_start = clock
    return {
        "server_time": round(time.perf_counter() - wall_start, 4),
        "cpu_time": round(time.process_time() - cpu_start, 4),
    }


def server_usage():
    """The request's server accounting so far, priced; {} outside a request (FASTAPI-TEXT2SQL-338).

    {server_time, cpu_time, sql_calls, sql_time, sql_rows, chroma_calls, chroma_time,
    server_cost_eur}. sql_time and chroma_time are the API's WAITS on MariaDB and ChromaDB
    (network and PyMySQL's row decoding included), the stand-in for their CPU, which the API
    cannot read; server_cost_eur prices cpu_time + sql_time + chroma_time at the VPS rate of
    llm_costs.py. An upper bound, on purpose: a wait is never shorter than the work.
    """
    readings = request_clock_readings()
    if not readings:
        return {}
    usage = _backend_usage.get() or {}
    with _backend_lock:
        usage = dict(usage)
    readings.update({
        "sql_calls": usage.get("sql_calls", 0),
        "sql_time": round(usage.get("sql_time", 0.0), 4),
        "sql_rows": usage.get("sql_rows", 0),
        "chroma_calls": usage.get("chroma_calls", 0),
        "chroma_time": round(usage.get("chroma_time", 0.0), 4),
    })
    cost = llm_costs.server_cost_eur(readings["cpu_time"], readings["sql_time"], readings["chroma_time"])
    readings["server_cost_eur"] = round(cost, 9) if cost is not None else None
    return readings


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
        During an HTTP request, "server_time" and "cpu_time" follow "ts" (FASTAPI-TEXT2SQL-337):
        seconds of wall time and of process CPU since the request entered the API.
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
    if isinstance(content, dict) and "server_time" not in content:
        # FASTAPI-TEXT2SQL-337: right after "ts", measured up to this line of the handler.
        content = {**{k: v for k, v in content.items() if k == "ts"},
                   **server_usage(),
                   **{k: v for k, v in content.items() if k != "ts"}}
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
