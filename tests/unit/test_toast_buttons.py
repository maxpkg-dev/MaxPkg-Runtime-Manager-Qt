"""Toast buttons stay inside the toast: those that do not fit beside each other go to the next line. Needs Qt; runs
inside 3ds Max through tests/run_unit.py and is skipped where there is no Qt. The toasts are never shown."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    from maxpkg_runtime.qt_compat import QtWidgets
    from maxpkg_runtime.ui.manager_window import Toast
    from maxpkg_runtime.ui.theme import ThemeService
    from maxpkg_runtime.ui.widgets import Button, IconButton
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None or QtWidgets.QApplication.instance() is None, "Qt is not running")
class ToastButtonTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.themes = ThemeService(ROOT)

    def toast(self, actions):
        toast = Toast("Package Manager could not be updated.\nThe checksum could not be downloaded.", "error",
                      self.themes, None, action=[(text, icon, lambda: None) for text, icon in actions])
        self.addCleanup(toast.deleteLater)
        toast.layout().activate()
        toast.adjustSize()
        toast.layout().activate()
        buttons = [button for button in toast.findChildren(Button) if not isinstance(button, IconButton)]
        return toast, buttons

    def test_long_second_button_goes_to_the_next_line(self):
        toast, (retry, manual) = self.toast([("Try Again", "refresh-cw"), ("Download manually", "external-link")])
        self.assertGreater(manual.geometry().top(), retry.geometry().bottom())
        self.assertEqual(manual.geometry().left(), retry.geometry().left())
        for button in (retry, manual):
            self.assertGreaterEqual(button.width(), button.sizeHint().width())  # never squeezed
            self.assertLessEqual(button.mapTo(toast, button.rect().topRight()).x(), toast.width())

    def test_screen_corner_toast_has_no_gap_under_its_text(self):
        toast = Toast("Package Manager 2.1.1 is up to date.\nNo installed packages to check.", "success", self.themes,
                      None)
        self.addCleanup(toast.deleteLater)
        toast.fit()
        self.assertEqual(toast.height(), toast.heightForWidth(toast.width()))
        self.assertLess(toast.height(), 100)  # adjustSize() made every window with a stretch at least 100 px tall
        offer, _buttons = self.toast([("Try Again", "refresh-cw"), ("Download manually", "external-link")])
        offer.fit()
        self.assertGreaterEqual(offer.height(), offer.sizeHint().height())

    def test_short_buttons_share_one_line(self):
        _toast, (update, retry) = self.toast([("Update", "download"), ("Try Again", "refresh-cw")])
        self.assertEqual(update.geometry().top(), retry.geometry().top())
        self.assertLess(update.geometry().right(), retry.geometry().left())


if __name__ == "__main__":
    unittest.main()
