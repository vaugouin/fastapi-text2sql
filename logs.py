import os
import json
import hashlib
from datetime import datetime

LOGS_FOLDER = "logs"

def f_getlogfilename(endpoint, contenttext, strapiversion):
    """Generate a unique log filename based on endpoint, timestamp, and content hash.

    Creates a filename in the format: YYYYMMDD-HHMMSS_endpoint_version_hash.json
    Ensures the logs folder exists before generating the filename.

    Args:
        endpoint (str): The API endpoint name (e.g., 'hello', 'text2sql')
        contenttext (str): The content to be logged (used for MD5 hash)
        strapiversion (str): The current API version string

    Returns:
        str: Complete path to the log file
    """
    os.makedirs(LOGS_FOLDER, exist_ok=True)
    now = datetime.now()
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

    contenttext = json.dumps(content, indent=4, ensure_ascii=False, default=decimal_serializer)
    log_filename = f_getlogfilename(endpoint, contenttext, strapiversion)
    # Create the JSON file if it doesn't exist
    if not os.path.exists(log_filename):
        with open(log_filename, 'w', encoding='utf-8') as file:
            file.write(contenttext)


def log_hot_reload(filename):
    content = {
        "message": f"Hot-loaded data file: {filename}",
        "filename": filename,
        "event": "data_hot_reload",
        "timestamp": datetime.now().isoformat(),
    }
    log_usage("data_hot_reload", content, "hot_reload")
