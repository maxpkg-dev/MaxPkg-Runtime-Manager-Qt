"""Stop MaxPkg Runtime (Qt) before its files are replaced or removed."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "entry.py"), run_name="maxpkg_entry")["run"]("stop")
