"""Entry points used by the installed MaxScript files (startup shim, MacroScript, installer, uninstaller).

python.ExecuteFile cannot pass arguments, so each caller runs one tiny wrapper:
  startup.py  -> start with 3ds Max (honours 'Start Runtime with 3ds Max')
  open.py     -> open the Manager (starts the Runtime when it is not running)
  welcome.py  -> after installation: start and show the welcome window
  stop.py     -> stop the Runtime before its files are replaced or removed
  "start" (no wrapper) -> MaxPkg.start() from MaxScript: start without opening the Manager
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _launch(**options):
    bootstrap = runpy.run_path(str(ROOT / "python" / "bootstrap.py"), run_name="maxpkg_bootstrap")
    return bootstrap["launch"](ROOT, **options)


def owner():
    state = sys.modules.get("_maxpkg_runtime_session")
    candidate = getattr(state, "owner", None) if state is not None else None
    return candidate if candidate is not None and getattr(candidate, "running", False) else None


def run(mode):
    current = owner()
    if mode == "open":
        if current is not None:
            current.open_manager("")
            return current
        return _launch(open_manager=True)
    if mode == "welcome":
        return _launch(open_manager=False, welcome=True)
    if mode == "startup":
        if current is not None:
            return current
        return _launch(open_manager=False, from_startup=True)
    if mode == "start":
        if current is not None:
            return current
        return _launch(open_manager=False)
    if mode == "stop":
        state = sys.modules.get("_maxpkg_runtime_session")
        if state is not None and getattr(state, "owner", None) is not None:
            state.owner.stop()
            state.owner = None
        return None
    raise ValueError("Unknown MaxPkg entry mode: " + str(mode))
