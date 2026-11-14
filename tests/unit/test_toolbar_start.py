"""The toolbar does not light up when it comes back with 3ds Max (or after a self-update): it is where the user left it.
A toolbar opened by hand, moved or restyled still lights up. A real ToolbarController on a floating toolbar in a
temporary folder. Needs Qt; skipped where there is none."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

try:
    from maxpkg_runtime.qt_compat import QtWidgets
    from maxpkg_runtime.services import max_api
    from maxpkg_runtime.services import runtime as runtime_module
    from maxpkg_runtime.ui import toolbar as toolbar_module
    from maxpkg_runtime.ui.theme import ThemeService
except ImportError:
    QtWidgets = None

ROOT = Path(__file__).resolve().parents[2]


def _from_this_repository():
    """run_unit.py imports this repository's modules; never patch the ones of a running Package Manager."""
    module = os.path.normcase(str(Path(runtime_module.__file__).resolve()))
    return module.startswith(os.path.normcase(str(ROOT)) + os.sep)


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class ToolbarStartTests(unittest.TestCase):
    def setUp(self):
        if not _from_this_repository():
            self.skipTest("the maxpkg_runtime modules are not this repository's (run tests/run_unit.py)")
        self.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])
        self.base = Path(tempfile.mkdtemp(prefix="maxpkg-toolbar-start-"))
        temp = self.base / "max-temp"
        temp.mkdir()
        originals = (max_api.get_dir, max_api.max_year)
        max_api.get_dir = lambda name: str(temp) if name == "temp" else ""
        max_api.max_year = lambda: 2027
        self.addCleanup(lambda: (setattr(max_api, "get_dir", originals[0]), setattr(max_api, "max_year", originals[1])))
        self.runtime = runtime_module.Runtime(self.base, "2.1.7", "stable")
        self.runtime.network.stop()
        settings = self.runtime.settings
        settings.toolbar_dock_position = "floatinghorizontal"  # no 3ds Max window to dock into here
        settings.floating_horizontal_x = settings.floating_horizontal_y = -9000
        self.highlights = []
        original = toolbar_module.ToolbarController._highlight
        toolbar_module.ToolbarController._highlight = (
            lambda controller, strength, *args, **kwargs: self.highlights.append(strength))
        self.addCleanup(lambda: setattr(toolbar_module.ToolbarController, "_highlight", original))
        self.toolbar = toolbar_module.ToolbarController(self.runtime, ThemeService(ROOT), None, lambda *_: None,
                                                        lambda *_: None, lambda *_args, **_kwargs: None)

    def tearDown(self):
        self.toolbar.stop()
        self.runtime.stop()
        self.runtime.deleteLater()
        shutil.rmtree(str(self.base), ignore_errors=True)

    def test_back_with_3ds_max_it_does_not_light_up(self):
        self.toolbar.start(highlight=False)
        self.assertIsNotNone(self.toolbar.floating)
        self.assertEqual(self.highlights, [])

    def test_opened_by_hand_it_lights_up(self):
        self.toolbar.start()
        self.assertIn(toolbar_module.ToolbarGlow.STRONG, self.highlights)

    def test_after_a_quiet_start_a_move_still_lights_up(self):
        self.toolbar.start(highlight=False)
        self.runtime.settings.toolbar_dock_position = "floatingvertical"
        self.toolbar.sync()
        self.assertEqual(self.highlights, [toolbar_module.ToolbarGlow.STRONG])


if __name__ == "__main__":
    unittest.main()
