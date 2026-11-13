"""Reordering toolbar buttons by drag: the stage pictures the buttons, makes room, lands and gives the real buttons
back; a locked toolbar shakes the button. Needs Qt; skipped where there is none."""

import time
import unittest

try:
    from maxpkg_runtime.qt_compat import QtCore, QtGui, QtWidgets
    from maxpkg_runtime.ui.toolbar import SHAKE_MS, DragStage, shake_offset
except ImportError:
    QtWidgets = None


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class ShakeTests(unittest.TestCase):
    def test_shakes_and_comes_to_rest(self):
        self.assertAlmostEqual(shake_offset(0.0), 0.0)
        self.assertAlmostEqual(shake_offset(1.0), 0.0, places=6)
        self.assertGreater(max(abs(shake_offset(step / 100.0)) for step in range(100)), 2.0)
        self.assertGreater(SHAKE_MS, 0)


@unittest.skipIf(QtWidgets is None, "Qt is not available")
class DragStageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication(["maxpkg-tests"])

    def setUp(self):
        self.host = QtWidgets.QWidget(None, QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.host.setAttribute(QtCore.Qt.WA_ShowWithoutActivating)
        self.host.setGeometry(-9000, -9000, 200, 40)
        self.buttons = []
        for index in range(4):
            button = QtWidgets.QWidget(self.host)
            button.setGeometry(index * 34, 5, 30, 30)
            button.staged = False
            self.buttons.append(button)
        self.host.show()
        self.addCleanup(self.host.deleteLater)

    def pump(self, stage, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end and stage.active:
            QtWidgets.QApplication.processEvents()
            time.sleep(0.005)

    def offsets(self, stage):
        return {id(item[0]): item[3] for item in stage.items}

    def test_the_neighbours_make_room_and_the_buttons_come_back(self):
        first, dragged, third, fourth = self.buttons
        stage = DragStage(self.host)
        self.assertTrue(stage.begin(self.buttons, dragged, False))
        self.assertTrue(all(button.staged for button in self.buttons))
        moved = [first, third, fourth, dragged]
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(50, 20)), moved)
        self.assertEqual(stage.slots[id(third)], 34)
        self.assertEqual(stage.slots[id(dragged)], 102)
        for _frame in range(30):
            stage._tick()
        self.assertAlmostEqual(self.offsets(stage)[id(third)], 34, delta=0.5)
        stage.drop(moved)
        self.pump(stage, 2.0)
        self.assertFalse(stage.active)
        self.assertFalse(stage.isVisible())
        self.assertFalse(any(button.staged for button in self.buttons))
        # The ring spreads from where it landed, in a window of its own so the toolbar's edges do not cut it off.
        landed = QtCore.QRect(self.host.mapToGlobal(QtCore.QPoint(102, 5)), QtCore.QSize(30, 30))
        self.assertIsNotNone(stage.burst)
        self.assertEqual(stage.burst.locate().toRect(), landed)
        self.assertTrue(stage.burst.isWindow())

    def test_the_dragged_button_follows_the_cursor_within_the_line(self):
        stage = DragStage(self.host)
        stage.begin(self.buttons, self.buttons[1], False)
        order = list(self.buttons)
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(40, 20)), order)  # grabbed 6 px into the button
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(80, 20)), order)
        stage._tick()
        self.assertAlmostEqual(stage.dragged[3], 74, delta=0.5)
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(900, 20)), order)
        stage._tick()
        self.assertLessEqual(stage.dragged[3], max(stage.slots.values()))
        stage.finish()

    def test_a_drop_without_a_move_glides_back_home(self):
        stage = DragStage(self.host)
        stage.begin(self.buttons, self.buttons[1], False)
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(40, 20)), list(self.buttons))
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(60, 20)), list(self.buttons))
        stage._tick()
        stage.drop(list(self.buttons))
        stage._clock.restart()
        end = time.monotonic() + 0.4
        while time.monotonic() < end:
            stage._tick()
            time.sleep(0.01)
            if not stage.active:
                break
        if stage.active:
            self.assertAlmostEqual(stage.dragged[3], 34, delta=0.5)
        stage.finish()

    def test_a_button_in_the_overflow_menu_is_not_staged(self):
        hidden = self.buttons[3]
        hidden.hide()
        stage = DragStage(self.host)
        self.assertFalse(stage.begin(self.buttons, hidden, False))
        self.assertFalse(stage.active)
        self.assertFalse(any(button.staged for button in self.buttons))

    def test_paints_the_lifted_button_over_the_toolbar(self):
        for button in self.buttons:
            button.setStyleSheet("background: #ff0000;")
            button.setAttribute(QtCore.Qt.WA_StyledBackground)
        stage = DragStage(self.host)
        stage.begin(self.buttons, self.buttons[0], False)
        stage.drag(self.host.mapToGlobal(QtCore.QPoint(10, 20)), list(self.buttons))
        image = QtGui.QImage(stage.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(QtCore.Qt.transparent)
        stage.render(image, QtCore.QPoint(), QtGui.QRegion(), QtWidgets.QWidget.DrawChildren)
        self.assertGreater(image.pixelColor(49, 20).red(), 150)  # the second button's picture
        stage.finish()


if __name__ == "__main__":
    unittest.main()
