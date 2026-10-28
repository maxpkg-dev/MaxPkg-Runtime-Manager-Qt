"""The only boundary to 3ds Max (pymxs). Call these functions on the main thread only.

Outside Max (unit tests) every function degrades to a harmless fallback.
"""

import os
import webbrowser

try:
    from pymxs import runtime as rt
except ImportError:  # pragma: no cover - outside 3ds Max
    rt = None

from . import log


def in_max():
    return rt is not None


def max_year():
    """Product year, e.g. 2027 (maxVersion()[8] exists since 3ds Max 2017)."""
    if rt is None:
        return 2027
    try:
        return int(rt.maxVersion()[7])
    except (IndexError, TypeError, ValueError):
        return 2000 + int(rt.maxVersion()[0]) // 1000 - 2


def get_dir(name):
    """getDir #name as a path without a trailing separator, or '' outside Max."""
    if rt is None:
        return ""
    try:
        return str(rt.getDir(rt.Name(name))).rstrip("\\/")
    except Exception:  # noqa: BLE001 - unknown directory names are not fatal
        return ""


def run_package(package):
    """Run the package entry exactly like core/launcher.ms. Returns (ok, message)."""
    entry_path = os.path.join(package.install_path, package.entry)
    if not os.path.isfile(entry_path):
        return False, "Entry file not found: " + entry_path
    if rt is None:
        return False, "3ds Max is not available"
    try:
        if package.runtime.lower() == "python" or entry_path.lower().endswith(".py"):
            rt.python.ExecuteFile(entry_path)
        else:
            rt.fileIn(entry_path)
    except Exception as error:  # noqa: BLE001 - a failing package must not break the Runtime
        log.error("launcher", package.guid + ": " + str(error))
        return False, str(error)
    log.info("launcher", "Ran " + package.guid)
    return True, ""


def file_in(path):
    """fileIn a MaxScript or MZP file. Raises on MaxScript errors."""
    if rt is None:
        raise RuntimeError("3ds Max is not available")
    rt.fileIn(path)


def execute(source):
    if rt is None:
        raise RuntimeError("3ds Max is not available")
    return rt.execute(source)


def open_folder(path):
    if path and os.path.isdir(path):
        os.startfile(path)  # noqa: S606 - explorer on a known package folder
        return True
    return False


def open_url(url):
    if url and url.lower().startswith(("http://", "https://")):
        webbrowser.open(url)
        return True
    return False
