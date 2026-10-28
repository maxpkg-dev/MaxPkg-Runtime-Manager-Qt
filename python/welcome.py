"""Start MaxPkg Runtime (Qt) after installation and show the welcome window."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "entry.py"), run_name="maxpkg_entry")["run"]("welcome")
