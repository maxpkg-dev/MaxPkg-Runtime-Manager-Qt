"""Lifecycle stress test inside 3ds Max (python.ExecuteFile). Writes logs/stress.txt.

Each cycle restarts the Runtime through bootstrap (sometimes with the Manager open, sometimes closed,
sometimes collapsed), switches tabs, themes and toolbar positions, then forces MaxScript and Python
garbage collection. Afterwards exactly one toolbar and at most one Manager window may exist.
Toolbar position and theme are restored to the values found before the test.
"""

import gc
import runpy
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CYCLES = 40


def pump(app, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        app.processEvents()
        time.sleep(0.005)


def main():
    from pymxs import runtime as rt
    from maxpkg_runtime.qt_compat import QtWidgets  # noqa: F401  (loaded by bootstrap)
    app = QtWidgets.QApplication.instance()
    owner = sys.modules["_maxpkg_runtime_session"].owner
    settings = owner.runtime.settings
    saved = (settings.toolbar_dock_position, settings.manager_theme)
    positions = ("top", "left", "floatinghorizontal", "bottom", "floatingvertical", "right")
    themes = [theme_id for theme_id, _name in owner.themes.manager_choices()]
    gc_calls = 0
    for cycle in range(CYCLES):
        runpy.run_path(str(ROOT / "python" / "bootstrap.py"), run_name="__main__")
        owner = sys.modules["_maxpkg_runtime_session"].owner
        window = owner.window
        pump(app, 0.08)
        window.show_tab(("discover", "installed", "updates")[cycle % 3])
        if cycle % 4 == 1:
            window.open_settings("toolbar")
        if cycle % 5 == 2:
            window.chrome.collapse()
        owner.runtime.settings.manager_theme = owner.themes.set_manager(themes[cycle % len(themes)])
        owner.runtime.settings.toolbar_dock_position = positions[cycle % len(positions)]
        owner.runtime.save_settings("toolbar")
        pump(app, 0.08)
        if cycle % 3 == 0:
            window.close()
            pump(app, 0.05)
        rt.gc()  # MaxScript garbage collection: the call that crashed the HTML Manager
        gc.collect()
        gc_calls += 1
    owner = sys.modules["_maxpkg_runtime_session"].owner
    owner.runtime.settings.toolbar_dock_position, theme = saved
    owner.runtime.settings.manager_theme = owner.themes.set_manager(theme)
    owner.runtime.save_settings("toolbar")
    pump(app, 0.3)
    rt.gc()
    state = owner.describe()
    ok = state["toolbars"] == 1 and state["visible_windows"] <= 2 and not state["stopped"]
    return "STRESS {} cycles={} maxscript_gc={} state={}".format("OK" if ok else "FAILED", CYCLES, gc_calls, state)


try:
    summary = main()
except Exception:  # noqa: BLE001 - reported in the log
    summary = "STRESS FAILED\n" + traceback.format_exc()
(ROOT / "logs").mkdir(exist_ok=True)
(ROOT / "logs" / "stress.txt").write_text(summary + "\n", encoding="utf-8")
print(summary)
