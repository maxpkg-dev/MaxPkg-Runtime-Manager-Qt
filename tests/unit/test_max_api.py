"""Pure tests for the parts of services/max_api.py that do not need 3ds Max. Run with tests/run_unit.py."""

import sys
import unittest

from maxpkg_runtime.services import max_api


class ErrorTextTests(unittest.TestCase):
    def test_drops_the_pymxs_first_line(self):
        error = RuntimeError("MAXScript exception raised.\n-- Runtime error: TopoLandia needs 3ds Max 2024\n")
        self.assertEqual(max_api.error_text(error), "-- Runtime error: TopoLandia needs 3ds Max 2024")

    def test_keeps_other_errors(self):
        self.assertEqual(max_api.error_text(RuntimeError("Bad entry")), "Bad entry")
        self.assertEqual(max_api.error_text(RuntimeError("MAXScript exception raised.")), "MAXScript exception raised.")
        self.assertEqual(max_api.error_text(ValueError("")), "ValueError")


class FacadeTests(unittest.TestCase):
    def test_offers_what_the_maxpkg_dev_installers_look_for(self):
        # The collection installer checks `isProperty MaxPkg #installLayout` before it calls it.
        for command in ("install", "installMany", "installLayout"):
            self.assertIn("fn {} ".format(command), max_api._FACADE_SOURCE)
            self.assertIn('call "{}"'.format(command), max_api._FACADE_SOURCE)


class OwnFileTests(unittest.TestCase):
    def setUp(self):
        self.main = sys.modules["__main__"]
        self.had_file = "__file__" in self.main.__dict__
        self.saved = self.main.__dict__.get("__file__")

    def tearDown(self):
        if self.had_file:
            self.main.__dict__["__file__"] = self.saved
        else:
            self.main.__dict__.pop("__file__", None)

    def test_caller_file_is_hidden_during_the_call_and_restored(self):
        self.main.__dict__["__file__"] = "caller.py"
        with max_api._OwnFile():
            self.assertNotIn("__file__", self.main.__dict__)
            self.main.__dict__["__file__"] = "package_entry.py"  # what 3ds Max sets for the package
        self.assertEqual(self.main.__dict__["__file__"], "caller.py")

    def test_restored_after_an_error(self):
        self.main.__dict__["__file__"] = "caller.py"
        with self.assertRaises(RuntimeError):
            with max_api._OwnFile():
                raise RuntimeError("package failed")
        self.assertEqual(self.main.__dict__["__file__"], "caller.py")

    def test_no_caller_file_stays_absent(self):
        self.main.__dict__.pop("__file__", None)
        with max_api._OwnFile():
            self.main.__dict__["__file__"] = "package_entry.py"
        self.assertNotIn("__file__", self.main.__dict__)


if __name__ == "__main__":
    unittest.main()
