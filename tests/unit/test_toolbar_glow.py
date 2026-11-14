"""The toolbar highlight: it waits for the toolbar to be on screen, lights only its buttons (two lines along it that
fade out at the ends, no box), rings new buttons (in windows of their
own, so nothing cuts the rings off), lets a laser erase removed ones, and fades out. Needs Qt; skipped where there is none."""

import unittest

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets
    from maxpkg_runtime.ui.toolbar import ACCENT, ToolbarDivider, ToolbarGlow

    class Placeholder(ToolbarDivider):
        """Stands for a toolbar button or divider: only its place matters to the glow."""

        def __init__(self, parent, geometry):
            QtWidgets.QWidget.__init__(self, parent)
            self.setGeometry(geometry)

        def paintEvent(self, _event):
            pass
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

    def global_rect(self, x, y, width, height):
        return QtCore.QRect(self.host.mapToGlobal(QtCore.QPoint(x, y)), QtCore.QSize(width, height))

    def buttons(self, vertical=False, count=5):
        """`count` buttons of 30 px from the start of the toolbar, with the rest of it empty."""
        for index in range(count):
            place = QtCore.QRect(5, 4 + index * 34, 30, 30) if vertical else QtCore.QRect(4 + index * 34, 5, 30, 30)
            Placeholder(self.host, place).show()
        return QtCore.QRect(1, 2, 36, 4 + count * 34 + 1) if vertical else QtCore.QRect(1, 2, 4 + count * 34 + 1, 36)

    def test_lights_only_the_buttons_not_the_empty_toolbar(self):
        lit = self.buttons()
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.STRONG)
        self.assertEqual(glow.lit_rect(), QtCore.QRect(1, 2, 172, 36))
        image = self.frame(glow, 0.05)
        self.assertGreater(accent_pixels(image, QtCore.QRect(40, 6, 100, 28)), 200)
        self.assertEqual(mean_alpha(image, QtCore.QRect(200, 0, 200, 40)), 0)  # the empty rest stays dark
        self.assertLessEqual(lit.right(), 180)

    def test_two_thin_lines_along_the_toolbar_fade_at_the_ends_and_no_box(self):
        self.buttons()
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.STRONG)
        image = self.frame(glow, 0.05)
        middle = 88
        line = image.pixelColor(middle, 2).alpha()
        self.assertGreater(line, 150)  # the top line
        self.assertGreater(image.pixelColor(middle, 37).alpha(), 150)  # the bottom one
        self.assertLess(image.pixelColor(middle, 5).alpha(), line * 0.75)  # 2 px thick at most: lighter below
        self.assertLess(image.pixelColor(2, 2).alpha(), 40)  # faded out at the start
        self.assertLess(image.pixelColor(171, 2).alpha(), 40)  # and at the end
        self.assertLess(mean_alpha(image, QtCore.QRect(1, 8, 2, 24)), 40)  # no line across the ends: no box

    def test_on_a_vertical_toolbar_the_lines_run_down_its_sides(self):
        self.host.setGeometry(-9000, -9000, 40, 400)
        self.buttons(vertical=True)
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(True, ToolbarGlow.STRONG)
        image = self.frame(glow, 0.05)
        self.assertGreater(image.pixelColor(2, 88).alpha(), 150)
        self.assertGreater(image.pixelColor(37, 88).alpha(), 150)
        self.assertLess(image.pixelColor(20, 2).alpha(), 40)  # no line across the top
        self.assertEqual(mean_alpha(image, QtCore.QRect(0, 200, 40, 200)), 0)

    def test_a_button_laid_out_later_is_lit_too(self):
        self.buttons(count=2)
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.SOFT)
        before = glow.lit_rect()
        Placeholder(self.host, QtCore.QRect(250, 5, 30, 30)).show()
        self.assertGreater(glow.lit_rect().right(), before.right())
        self.assertGreaterEqual(glow.lit_rect().right(), 280)

    def test_rings_a_new_button_in_windows_of_their_own(self):
        self.host.show()
        button = QtWidgets.QWidget(self.host)
        button.setGeometry(200, 5, 30, 30)
        button.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.SOFT, [button])
        image = self.frame(glow, 0.2)
        self.assertGreater(mean_alpha(image, QtCore.QRect(200, 5, 30, 30)), 1.5 * mean_alpha(image, QtCore.QRect(300, 5, 30, 30)))
        self.assertEqual(len(glow.bursts), len(ToolbarGlow.RING_DELAYS))
        first = glow.bursts[0]
        self.assertTrue(first.isVisible())  # the first ring starts at once, the second a moment later
        self.assertTrue(first.isWindow())
        self.assertEqual(QtCore.QRectF(first.place).toRect(), self.global_rect(200, 5, 30, 30))
        self.assertLess(first.geometry().top(), self.host.geometry().top())  # it reaches past the toolbar's edges
        self.assertGreater(first.geometry().bottom(), self.host.geometry().bottom())

    def test_rings_the_overflow_button_when_the_new_button_is_hidden_in_it(self):
        self.host.show()
        hidden = QtWidgets.QWidget(self.host)
        hidden.setGeometry(380, 5, 30, 30)  # a crowded toolbar put it in the >> menu
        hidden.hide()
        overflow = QtWidgets.QToolButton(self.host)
        overflow.setObjectName("qt_toolbar_ext_button")
        overflow.setGeometry(200, 5, 14, 30)
        overflow.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.SOFT, [hidden])
        self.assertEqual(QtCore.QRectF(glow.bursts[0].place).toRect(), self.global_rect(200, 5, 14, 30))
        image = self.frame(glow, 0.2)
        self.assertGreater(mean_alpha(image, QtCore.QRect(200, 5, 14, 30)), 1.5 * mean_alpha(image, QtCore.QRect(300, 5, 14, 30)))

    def removed(self, vertical, place):
        self.host.show()
        picture = QtGui.QPixmap(30, 30)
        picture.fill(QtGui.QColor("#ff0000"))
        glow = ToolbarGlow(self.host)
        glow.play(vertical, ToolbarGlow.NONE, ghosts=[(picture, QtCore.QRectF(place))])
        return glow

    def test_a_laser_erases_a_removed_button_from_right_to_left(self):
        glow = self.removed(False, QtCore.QRect(100, 5, 30, 30))
        start = self.frame(glow, 0.05)
        self.assertGreater(red_pixels(start, QtCore.QRect(100, 5, 20, 30)), 50)  # still there, barely faded
        self.assertGreater(accent_pixels(start, QtCore.QRect(124, 5, 10, 30)), 10)  # the laser at its right end
        half = self.frame(glow, ToolbarGlow.ERASE / 2)  # the laser in the middle (x 115)
        self.assertGreater(red_pixels(half, QtCore.QRect(100, 5, 6, 30)), 20)  # ahead of it: fading, not gone
        self.assertEqual(red_pixels(half, QtCore.QRect(123, 5, 7, 30)), 0)  # behind it: erased
        self.assertGreater(accent_pixels(half, QtCore.QRect(112, 5, 6, 30)), 10)
        self.assertEqual(accent_pixels(half, QtCore.QRect(200, 0, 60, 40)), 0)  # only there: no wash on the toolbar
        end = self.frame(glow, ToolbarGlow.ERASE + 0.02)
        self.assertEqual(red_pixels(end, QtCore.QRect(100, 5, 30, 30)), 0)
        self.assertGreater(mean_alpha(end, QtCore.QRect(99, 6, 3, 28)), 150)  # it stopped where the place closes

    def test_on_a_vertical_toolbar_the_laser_goes_up(self):
        self.host.setGeometry(-9000, -9000, 40, 400)
        glow = self.removed(True, QtCore.QRect(5, 100, 30, 30))
        half = self.frame(glow, ToolbarGlow.ERASE / 2)
        self.assertGreater(red_pixels(half, QtCore.QRect(5, 100, 30, 6)), 20)
        self.assertEqual(red_pixels(half, QtCore.QRect(5, 123, 30, 7)), 0)
        self.assertGreater(accent_pixels(half, QtCore.QRect(5, 112, 30, 6)), 10)

    def test_the_closed_place_keeps_a_glowing_mark_a_moment(self):
        self.host.show()
        glow = ToolbarGlow(self.host)
        glow.play(False, ToolbarGlow.NONE, gaps=[(100, 5, 30)])
        image = self.frame(glow, 0.1)
        self.assertGreater(mean_alpha(image, QtCore.QRect(99, 6, 3, 28)), 150)
        self.assertGreater(mean_alpha(image, QtCore.QRect(94, 6, 3, 28)), 10)  # its glow
        self.assertEqual(mean_alpha(image, QtCore.QRect(300, 6, 30, 28)), 0)
        self.assertEqual(mean_alpha(self.frame(glow, 1.0), QtCore.QRect(94, 0, 14, 40)), 0)

    def test_uses_the_toolbar_accent(self):
        self.assertEqual(QtGui.QColor(ACCENT).name(), "#3af1c5")


if __name__ == "__main__":
    unittest.main()
