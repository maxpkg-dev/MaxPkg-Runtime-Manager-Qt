"""Compile every module and run tests/unit. Works in 3ds Max (python.ExecuteFile) or a system Python.

Writes logs/unit.txt and prints a one-line summary. The domain tests never import Qt or pymxs.
"""

import io
import py_compile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYTHON = ROOT / "python"


def main():
    if str(PYTHON) not in sys.path:
        sys.path.insert(0, str(PYTHON))
    for name in [name for name in sys.modules if name == "maxpkg_runtime" or name.startswith("maxpkg_runtime.")]:
        if not name.startswith("maxpkg_runtime.domain") and name != "maxpkg_runtime":
            continue
        del sys.modules[name]
    # A Max session keeps the test modules of the previous run: discover would run the old tests again.
    for test_file in (ROOT / "tests" / "unit").glob("test_*.py"):
        sys.modules.pop(test_file.stem, None)
    compile_errors = []
    for path in sorted(PYTHON.rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as error:
            compile_errors.append(str(error))
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests" / "unit"), top_level_dir=str(ROOT / "tests" / "unit"))
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    summary = "UNIT {} python={} tests={} failures={} errors={} compile_errors={}".format(
        "OK" if result.wasSuccessful() and not compile_errors else "FAILED", sys.version.split()[0], result.testsRun,
        len(result.failures), len(result.errors), len(compile_errors))
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "unit.txt").write_text(summary + "\n\n" + "\n".join(compile_errors) + "\n" + stream.getvalue(),
                                            encoding="utf-8")
    print(summary)
    return summary


main()
