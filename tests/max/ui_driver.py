"""Helpers for driving the running Runtime from Max Ultra MCP / the Listener and grabbing screenshots.

Usage inside Max (python.execute):
    import runpy; d = runpy.run_path(r"...\\tests\\max\\ui_driver.py"); d["grab_window"]("installed")
"""

import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SHOTS = ROOT / "docs" / "screenshots"
LOG = ROOT / "logs" / "driver.txt"


def owner():
    return sys.modules["_maxpkg_runtime_session"].owner


def window():
    return owner().window


def _qt():
    from maxpkg_runtime.qt_compat import QtCore, QtWidgets
    return QtCore, QtWidgets


def log(text):
    LOG.parent.mkdir(exist_ok=True)
    with open(str(LOG), "a", encoding="utf-8") as stream:
        stream.write(text + "\n")


def guarded(function):
    def wrapper(*args, **kwargs):
        try:
            result = function(*args, **kwargs)
            log("OK {} {}".format(function.__name__, result))
            return result
        except Exception:  # noqa: BLE001 - written to the driver log
            log("FAILED {}\n{}".format(function.__name__, traceback.format_exc()))
            return None
    return wrapper


def pump(seconds=0.4):
    """Let posted LayoutRequest chains settle (one processEvents() is not enough for nested layouts)."""
    import time
    QtCore, QtWidgets = _qt()
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        QtWidgets.QApplication.processEvents()
        time.sleep(0.02)


@guarded
def grab_window(name, width=None, height=None):
    target = window()
    if width and height:
        target.resize(width, height)
    QtCore, QtWidgets = _qt()
    pump()
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / (name + ".png")
    target.grab().save(str(path))
    return str(path)


@guarded
def grab_toolbar(name, margin=6):
    controller = owner().toolbar
    QtCore, QtWidgets = _qt()
    QtWidgets.QApplication.processEvents()
    widget = controller.toolbar if controller.toolbar is not None else controller.floating
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / (name + ".png")
    if controller.toolbar is not None:
        main = controller.main_window
        rect = widget.geometry().adjusted(-margin, -margin, margin, margin)
        if widget.orientation() == QtCore.Qt.Horizontal:
            rect.setLeft(0)
            rect.setRight(min(main.width() - 1, widget.geometry().right() + 300))
        main.grab(rect).save(str(path))
    else:
        widget.grab().save(str(path))
    return str(path)


@guarded
def grab_settings(name, page=""):
    panel = window().settings_panel
    panel.open_page(page)
    pump()
    SHOTS.mkdir(parents=True, exist_ok=True)
    path = SHOTS / (name + ".png")
    panel.grab().save(str(path))
    return str(path)


@guarded
def call(expression):
    """Evaluate a Python expression with `o` (controller) and `w` (Manager window) in scope."""
    return repr(eval(expression, {"o": owner(), "w": window(), "sys": sys}))
