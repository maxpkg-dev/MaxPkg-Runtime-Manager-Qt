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


def apply_update(staged_root, reopen=False):
    """Replace the installed program with an unpacked, verified release and start it.

    Called by services/self_update.py from a timer. This file lives outside the reloadable package so it keeps
    working while the package is stopped and replaced. Order: stop the Runtime, swap the files (with rollback),
    start the new code; if the new code does not start, put the old files back and start them again.
    """
    state = sys.modules.get("_maxpkg_runtime_session")
    previous = getattr(state, "owner", None) if state is not None else None
    rules = sys.modules.get("maxpkg_runtime.domain.self_update")
    if previous is None or rules is None:
        raise RuntimeError("The Package Manager is not running; nothing to update")
    old_version = previous.runtime.version if previous.runtime is not None else ""
    previous.stop()  # releases the toolbar, windows, timers and network of the old code
    state.owner = None
    swap = None
    problem = ""
    try:
        swap = rules.install_staged(ROOT, Path(staged_root))
    except Exception as error:  # noqa: BLE001 - the old files were restored by install_staged
        problem = "The update could not be installed: " + (str(error) if isinstance(error, rules.UpdateError)
                                                          else error.__class__.__name__)
    try:
        if problem:  # same files as before: start them again and tell the user
            started = _launch(open_manager=bool(reopen))
            if started is not None and getattr(started, "runtime", None) is not None:
                started.runtime.say(problem, "error")
            return started
        return _launch(open_manager=bool(reopen), updated_from=old_version)
    except Exception:
        if swap is None:
            raise
        swap.rollback()  # the new code did not start: back to the previous version
        return _launch(open_manager=bool(reopen))
