"""Launch the Runtime through bootstrap and record the outcome in logs/launch.txt (run inside Max)."""

import runpy
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    (ROOT / "logs").mkdir(exist_ok=True)
    old_prototype = sys.modules.get("_maxpkg_manager_session")
    if old_prototype is not None and getattr(old_prototype, "owner", None) is not None:
        try:
            old_prototype.owner.stop()
            old_prototype.owner = None
        except Exception:  # noqa: BLE001 - diagnostics only
            pass
    try:
        runpy.run_path(str(ROOT / "python" / "bootstrap.py"), run_name="__main__")
        owner = sys.modules["_maxpkg_runtime_session"].owner
        text = "LAUNCH OK " + repr(owner.describe())
    except Exception:  # noqa: BLE001 - written to the log for the developer
        text = "LAUNCH FAILED\n" + traceback.format_exc()
    (ROOT / "logs" / "launch.txt").write_text(text + "\n", encoding="utf-8")
    print(text)


main()
