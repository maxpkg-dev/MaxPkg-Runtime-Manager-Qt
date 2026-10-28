"""Run .github/scripts/build_mzp.py with 3ds Max's Python (no system Python needed). Writes logs/build.txt."""

import contextlib
import io
import runpy
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    output = io.StringIO()
    arguments = ["build_mzp.py", "--root", str(ROOT), "--manifest", str(ROOT / ".github" / "mzp-files.txt"),
                 "--output", str(ROOT / "dist" / "MaxPkg-Runtime-Manager-Qt.mzp"),
                 "--changelog", str(ROOT / "CHANGELOG.md"), "--notes-output", str(ROOT / "dist" / "release-notes.md")]
    saved = sys.argv
    sys.argv = arguments
    code = 0
    try:
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            runpy.run_path(str(ROOT / ".github" / "scripts" / "build_mzp.py"), run_name="__main__")
    except SystemExit as exit_request:
        code = exit_request.code or 0
    except Exception:  # noqa: BLE001 - written to the log
        output.write(traceback.format_exc())
        code = 1
    finally:
        sys.argv = saved
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "build.txt").write_text("exit={}\n{}".format(code, output.getvalue()), encoding="utf-8")


main()
