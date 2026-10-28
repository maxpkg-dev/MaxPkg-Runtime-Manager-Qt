"""Open MaxPkg Manager (MacroScript); starts the Runtime when needed."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "entry.py"), run_name="maxpkg_entry")["run"]("open")
