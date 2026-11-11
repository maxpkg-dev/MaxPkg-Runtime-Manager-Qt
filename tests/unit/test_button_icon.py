"""Button icons keep their logical size at any device pixel ratio. Needs Qt; skipped where there is none."""

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets
    from maxpkg_runtime.ui.theme import ThemeService
except ImportError:
    QtWidgets = None


def glyph_width(button):
    """Width in device pixels of what the button's icon really draws."""
    size = button.iconSize()
    ratio = button.devicePixelRatioF()
    pixmap = button.icon().pixmap(QtCore.QSize(int(size.width() * ratio), int(size.height() * ratio)))
    image = pixmap.toImage().convertToFormat(QtGui.QImage.Format_ARGB32)
    columns = [x for x in range(image.width()) if any(image.pixelColor(x, y).alpha() > 40 for y in range(image.height()))]
    return columns[-1] - columns[0] + 1 if columns else 0


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class ButtonIconTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])
        cls.themes = ThemeService(ROOT)

    def button(self, text, ratio, right_to_left=False):
        class ScaledButton(QtWidgets.QPushButton):
            def devicePixelRatioF(self):
                return ratio

        button = ScaledButton(text)
        if right_to_left:
            button.setLayoutDirection(QtCore.Qt.RightToLeft)
        self.themes.bind_icon(button, "play", "iconPrimary", 16)
        self.addCleanup(button.deleteLater)
        return button

    def test_icon_next_to_text_grows_with_the_ratio(self):
        normal = glyph_width(self.button("Run", 1.0))
        self.assertGreater(normal, 0)
        for ratio in (1.5, 2.0):
            self.assertAlmostEqual(glyph_width(self.button("Run", ratio)), normal * ratio, delta=2.5)

    def test_icon_on_the_right_of_text_grows_with_the_ratio(self):
        normal = glyph_width(self.button("Next", 1.0, right_to_left=True))
        self.assertAlmostEqual(glyph_width(self.button("Next", 2.0, right_to_left=True)), normal * 2, delta=2.5)

    def test_icon_without_text_grows_with_the_ratio(self):
        normal = glyph_width(self.button("", 1.0))
        self.assertAlmostEqual(glyph_width(self.button("", 2.0)), normal * 2, delta=2.5)


if __name__ == "__main__":
    unittest.main()
