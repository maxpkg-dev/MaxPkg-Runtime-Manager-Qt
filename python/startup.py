"""Start MaxPkg Runtime (Qt) with 3ds Max (startup shim)."""

import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parent / "entry.py"), run_name="maxpkg_entry")["run"]("startup")
