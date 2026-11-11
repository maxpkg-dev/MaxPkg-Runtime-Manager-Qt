"""The toolbar highlight: it waits for the toolbar to be on screen, lights it, rings new buttons, lets removed ones
shrink away, and fades out. Needs Qt; skipped where there is none."""

import unittest

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets
    from maxpkg_runtime.ui.toolbar import InsertionLine, ToolbarGlow
except ImportError:
    QtWidgets = None


def accent_pixels(image, rect):
    """How many pixels inside `rect` lean towards the accent color (green well above red)."""
    count = 0
    for x in range(rect.left(), rect.right() + 1, 2):
        for y in range(rect.top(), rect.bottom() + 1, 2):
            color = image.pixelColor(x, y)
            if color.alpha() > 20 and color.green() > color.red() + 40:
                count += 1
    return count


def red_pixels(image, rect):
    return sum(1 for x in range(rect.left(), rect.right() + 1) for y in range(rect.top(), rect.bottom() + 1)
               if image.pixelColor(x, y).red() > 150 and image.pixelColor(x, y).green() < 80)


def mean_alpha(image, rect):
    values = [image.pixelColor(x, y).alpha() for x in range(rect.left(), rect.right() + 1)
              for y in range(rect.top(), rect.bottom() + 1)]
    return sum(values) / float(len(values))


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class ToolbarGlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])

    def setUp(self):
        self.host = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.host.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.host.setStyleSheet("background: #444444;")
        self.host.setGeometry(-9000, -9000, 400, 40)
        self.addCleanup(self.host.deleteLater)

    def frame(self, glow, progress):
        glow._animation.stop()
        glow.progress = progress
        image = QtGui.QImage(glow.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        glow.render(image, QtCore.QPoint(), QtGui.QRegion(), QtWidgets.QWidget.DrawChildren)  # no window background
        return image

    def test_lets_the_toolbar_show_through(self):
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.STRONG)
        image = self.frame(glow, 0.05)
        self.assertLess(max(image.pixelColor(x, 20).alpha() for x in range(0, 400, 7)), 255)

    def test_waits_until_the_toolbar_is_on_screen(self):
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.STRONG)
        self.assertFalse(glow.isVisible())
        self.assertTrue(glow._retry.isActive())
        self.host.show()
        glow._retry.stop()
        glow._start()
        self.assertTrue(glow.isVisible())
        self.assertEqual(glow.geometry(), self.host.rect())

    def test_lights_the_toolbar_then_fades_out(self):
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.STRONG)
        whole = glow.rect()
        self.assertGreater(accent_pixels(self.frame(glow, 0.05), whole), 500)
        self.assertEqual(accent_pixels(self.frame(glow, 1.0), whole), 0)
        glow._animation.start()
        glow._animation.setCurrentTime(ToolbarGlow.DURATION)
        self.assertFalse(glow.isVisible())

    def test_rings_a_new_button(self):
        self.host.show()
        button = QtWidgets.QWidget(self.host)
        button.setGeometry(200, 5, 30, 30)
        button.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.SOFT, [button])
        image = self.frame(glow, 0.2)
        around = QtCore.QRect(188, 0, 54, 40)
        far = QtCore.QRect(300, 0, 54, 40)
        self.assertGreater(mean_alpha(image, around), 1.5 * mean_alpha(image, far))

    def test_rings_the_overflow_button_when_the_new_button_is_hidden_in_it(self):
        self.host.show()
        hidden = QtWidgets.QWidget(self.host)
        hidden.setGeometry(380, 5, 30, 30)  # a crowded toolbar put it in the >> menu
        overflow = QtWidgets.QToolButton(self.host)
        overflow.setObjectName("qt_toolbar_ext_button")
        overflow.setGeometry(200, 5, 14, 30)
        overflow.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.SOFT, [hidden])
        image = self.frame(glow, 0.2)
        around = QtCore.QRect(188, 0, 38, 40)
        far = QtCore.QRect(300, 0, 38, 40)
        self.assertGreater(mean_alpha(image, around), 1.5 * mean_alpha(image, far))

    def test_a_removed_button_shrinks_away_and_leaves_a_line(self):
        self.host.show()
        picture = QtGui.QPixmap(30, 30)
        picture.fill(QtGui.QColor("#ff0000"))
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.NONE, gaps=[(100, 5, 30)], ghosts=[(picture, QtCore.QRectF(100, 5, 30, 30))])
        place = QtCore.QRect(100, 5, 30, 30)
        self.assertGreater(red_pixels(self.frame(glow, 0.05), place), 50)
        self.assertEqual(red_pixels(self.frame(glow, 0.6), place), 0)
        image = self.frame(glow, 0.1)
        self.assertGreater(mean_alpha(image, QtCore.QRect(99, 6, 3, 28)), 150)
        self.assertEqual(mean_alpha(image, QtCore.QRect(300, 6, 30, 28)), 0)

    def test_uses_the_toolbar_accent(self):
        self.assertEqual(QtGui.QColor(InsertionLine.ACCENT).name(), "#3af1c5")


if __name__ == "__main__":
    unittest.main()
