"""The ring that spreads from a button in a see-through window of its own: it reaches past the toolbar's edges, never
takes the mouse or the focus, waits for a button laid out late, and closes itself. Needs Qt; skipped where there is none."""

import time
import unittest

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets
    from maxpkg_runtime.ui.toolbar import RingBurst
except ImportError:
    QtWidgets = None


def accent_pixels(image, rect):
    count = 0
    for x in range(rect.left(), rect.right() + 1):
        for y in range(rect.top(), rect.bottom() + 1):
            color = image.pixelColor(x, y)
            if color.alpha() > 40 and color.green() > color.red() + 40:
                count += 1
    return count


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class RingBurstTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])

    def setUp(self):
        self.host = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.host.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.host.setGeometry(-9000, -9000, 200, 40)
        self.host.show()
        self.addCleanup(self.host.deleteLater)
        self.place = QtCore.QRectF(QtCore.QPointF(self.host.mapToGlobal(QtCore.QPoint(80, 5))), QtCore.QSizeF(30, 30))

    def pump(self, seconds, until=None):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not (until is not None and until()):
            QtWidgets.QApplication.processEvents()
            time.sleep(0.005)

    def frame(self, burst, progress):
        burst.progress = progress
        image = QtGui.QImage(burst.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        burst.render(image, QtCore.QPoint(), QtGui.QRegion(), QtWidgets.QWidget.DrawChildren)
        return image

    def test_spreads_past_the_button_and_the_toolbar(self):
        burst = RingBurst(self.host, lambda: self.place, duration=5000)
        self.addCleanup(burst.close)
        self.assertTrue(burst.isWindow())
        self.assertTrue(burst.isVisible())
        self.assertEqual(burst.parentWidget(), self.host.window())
        self.assertTrue(burst.windowFlags() & QtCore.Qt.WindowTransparentForInput)
        self.assertTrue(burst.windowFlags() & QtCore.Qt.WindowDoesNotAcceptFocus)
        self.assertTrue(burst.testAttribute(QtCore.Qt.WA_TranslucentBackground))
        self.assertLess(burst.geometry().top(), self.host.geometry().top())
        image = self.frame(burst, 0.5)
        margin = RingBurst.MARGIN
        above = QtCore.QRect(margin, 0, 30, margin - 2)  # over the button, outside the toolbar
        self.assertGreater(accent_pixels(image, above), 10)
        self.assertEqual(accent_pixels(image, QtCore.QRect(margin + 4, margin + 4, 22, 22)), 0)  # the button shows through
        rect, _radius, opacity = burst.ring()
        self.assertLess(opacity, 1.0)
        self.assertGreater(rect.width(), 30 + 4)

    def test_closes_itself_when_the_ring_is_gone(self):
        closed = []
        burst = RingBurst(self.host, lambda: self.place, duration=120)
        burst.destroyed.connect(lambda: closed.append(True))
        self.pump(1.5, until=lambda: closed)
        self.assertTrue(closed)

    def test_waits_for_a_button_laid_out_late(self):
        places = [None]
        burst = RingBurst(self.host, lambda: places[0], duration=2000)
        self.addCleanup(lambda: burst.close() if not closed else None)
        closed = []
        burst.destroyed.connect(lambda: closed.append(True))
        self.pump(0.1)
        self.assertFalse(closed)
        self.assertFalse(burst.isVisible())
        places[0] = self.place
        self.pump(0.1)
        self.assertTrue(burst.isVisible())
        self.assertEqual(burst.place, self.place)
        places[0] = None  # the button went
        self.pump(0.5, until=lambda: closed)
        self.assertTrue(closed)

    def test_starts_after_its_delay(self):
        burst = RingBurst(self.host, lambda: self.place, delay=150, duration=2000)
        self.addCleanup(burst.close)
        self.assertFalse(burst.isVisible())
        self.pump(0.6, until=burst.isVisible)
        self.assertTrue(burst.isVisible())


if __name__ == "__main__":
    unittest.main()
