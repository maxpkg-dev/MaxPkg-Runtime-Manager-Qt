"""Tiny thread-safe file logger (one file per day under the data folder)."""

import datetime
import os
import threading

_lock = threading.Lock()
_folder = ""
_debug = False


def configure(folder, debug=False):
    global _folder, _debug
    _folder = str(folder)
    _debug = debug
    try:
        os.makedirs(_folder, exist_ok=True)
    except OSError:
        _folder = ""


def _write(level, area, message):
    if not _folder:
        return
    now = datetime.datetime.now()
    line = "{} [{}] {}: {}\n".format(now.strftime("%H:%M:%S"), level, area, message)
    path = os.path.join(_folder, "runtime-" + now.strftime("%Y-%m-%d") + ".log")
    with _lock:
        try:
            with open(path, "a", encoding="utf-8") as stream:
                stream.write(line)
        except OSError:
            pass


def info(area, message):
    _write("INFO", area, message)


def warning(area, message):
    _write("WARN", area, message)


def error(area, message):
    _write("ERROR", area, message)


def debug(area, message):
    if _debug:
        _write("DEBUG", area, message)
