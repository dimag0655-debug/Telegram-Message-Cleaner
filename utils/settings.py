import json
import os
import math
from pathlib import Path


def data_dir():
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    target = base / "TelegramMessageCleaner"
    target.mkdir(parents=True, exist_ok=True)
    return target


def read_settings():
    try:
        data = json.loads((data_dir() / "settings.json").read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        safe = {}
        for key in ("width", "height", "delay"):
            value = data.get(key)
            if type(value) in (int, float) and math.isfinite(value):
                safe[key] = value
        return safe
    except (OSError, ValueError, TypeError):
        return {}


def write_settings(width, height, delay):
    # Explicit whitelist: credentials, peer IDs, text and session data cannot enter this file.
    payload = {"width": int(width), "height": int(height), "delay": float(delay)}
    path = data_dir() / "settings.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(payload), encoding="utf-8")
    temp.replace(path)
