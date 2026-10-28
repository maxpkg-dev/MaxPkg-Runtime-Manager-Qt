"""Own window chrome (same behaviour as TerraScoop / Max Ultra MCP windows).

* No Windows frame: a slim title bar with the maxpkg icon, the window name, minimise and close.
  Drag the bar to move, double-click to maximise/restore, drag the 4 px edges to resize.
* Minimise collapses the window into a small bar: dotted grip and name move it, a click on the name
  opens the window again where it was, x closes it. The bar remembers its place, stays inside a
  screen's work area and follows 3ds Max's main window while it is moved.
"""

import ctypes
import sys

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, event_global_pos, is_valid, screen_at
from . import icons
from .widgets import IconButton

EDGE = 4
WINDOW_RADIUS = 8.0  # Windows 11 DWM "round" corners use 8 px


def _windows_build():
    if sys.platform != "win32":
        return 0
    try:
        return sys.getwindowsversion().build
    except AttributeError:
        return 0


# Windows 11 rounds frameless windows and gives them the system shadow through DWM. Translucent
# (WA_TranslucentBackground) windows never get a shadow, so we only paint our own rounded shape on
# older systems.
NATIVE_FRAME = _windows_build() >= 22000


class _Margins(ctypes.Structure):
    _fields_ = [("left", ctypes.c_int), ("right", ctypes.c_int), ("top", ctypes.c_int), ("bottom", ctypes.c_int)]


def prepare_window(widget):
    """Call before the first show: translucent only when DWM cannot shape the window."""
    if not NATIVE_FRAME:
        widget.setAttribute(Qt.WA_TranslucentBackground)


def apply_native_frame(widget, border_color=None):
    """System shadow, rounded corners and border color for a frameless window (Windows 11). Safe to repeat."""
    if not NATIVE_FRAME:
        return False
    try:
        hwnd = ctypes.c_void_p(int(widget.winId()))
        dwm = ctypes.windll.dwmapi
        margins = _Margins(1, 1, 1, 1)  # a 1 px extended frame makes DWM draw the shadow of a popup window
        dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        corner = ctypes.c_int(2)  # DWMWA_WINDOW_CORNER_PREFERENCE = DWMWCP_ROUND
        dwm.DwmSetWindowAttribute(hwnd, 33, ctypes.byref(corner), ctypes.sizeof(corner))
        if border_color is not None:  # DWMWA_BORDER_COLOR expects COLORREF 0x00BBGGRR
            colorref = ctypes.c_uint(border_color.red() | (border_color.green() << 8) | (border_color.blue() << 16))
            dwm.DwmSetWindowAttribute(hwnd, 34, ctypes.byref(colorref), ctypes.sizeof(colorref))
        return True
    except (AttributeError, OSError, ValueError):
        return False


def paint_window_shape(widget, painter, fill, border):
    """Background of a frameless window: plain rectangle under DWM, rounded shape otherwise."""
    rect = QtCore.QRectF(widget.rect())
    if NATIVE_FRAME:
        painter.fillRect(rect, fill)
        return
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    radius = 0.0 if widget.isMaximized() else WINDOW_RADIUS + 2
    painter.setPen(QtGui.QPen(border, 1))
    painter.setBrush(fill)
    painter.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), radius, radius)
MINI_GAP = 12
_CURSORS = {1: Qt.SizeHorCursor, 2: Qt.SizeHorCursor, 4: Qt.SizeVerCursor, 8: Qt.SizeVerCursor,
            5: Qt.SizeFDiagCursor, 10: Qt.SizeFDiagCursor, 6: Qt.SizeBDiagCursor, 9: Qt.SizeBDiagCursor}


def bounded_position(position, size, anchor=None):
    """`position` moved so a window of `size` stays inside the work area of the screen under `anchor`."""
    target = anchor if anchor is not None else position + QtCore.QPoint(size.width() // 2, size.height() // 2)
    area = screen_at(target).availableGeometry()
    return QtCore.QPoint(max(area.left(), min(position.x(), area.right() - size.width() + 1)),
                         max(area.top(), min(position.y(), area.bottom() - size.height() + 1)))


class BrandIcon(QtWidgets.QLabel):
    def __init__(self, themes, size=18, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # drags on the bar pass through
        themes.bind_icon(self, "maxpkg-logo", "accent", size)


class WindowChrome(QtCore.QObject):
    """Title bar, collapsed bar and frameless move/resize for `window` (a top-level QWidget).

    The window keeps its content in `content`; `parts()` are hidden while collapsed.
    `on_mini_position(point)` stores where the user leaves the collapsed bar.
    """

    def __init__(self, window, title, themes, mini_position=None, on_mini_position=None, collapsible=True,
                 flags=Qt.Window):
        QtCore.QObject.__init__(self, window)
        self.window = window
        self.themes = themes
        self.title = title
        self.collapsible = collapsible
        self.on_mini_position = on_mini_position
        self.saved_mini = mini_position
        window.setWindowFlags(flags | Qt.FramelessWindowHint)
        window.setMouseTracking(True)
        self._resizing = None
        self._drag = None
        self._drag_from = None
        self._dragged = False
        self._mini = None
        self._host = None
        self._host_pos = None
        # Qt calls eventFilter while the filters are being installed: every watched name exists first.
        self.title_bar = self.mini_grip = self.mini_title = None
        self.mini_bar = None
        if collapsible:
            self._build_mini_bar(title)

    def attach_title_bar(self, widget):
        """Make `widget` the title bar: drag it to move, double-click to maximise (labels pass clicks through)."""
        self.title_bar = widget
        widget.installEventFilter(self)

    def window_buttons(self, close_tip="Close"):
        """Minimise (collapse) and close buttons for the end of the title bar."""
        buttons = []
        specs = [("x", close_tip, self.window.close)]
        if self.collapsible:
            specs.insert(0, ("minus", "Collapse to a small bar (click its name to open again)", self.collapse))
        for icon_name, tip, slot in specs:
            button = IconButton(icon_name, tip, self.themes)
            button.setObjectName("ChromeButton")
            button.setFixedSize(28, 28)
            button.clicked.connect(slot)
            buttons.append(button)
        return buttons

    def _build_mini_bar(self, title):
        themes = self.themes
        window = self.window
        self.mini_bar = QtWidgets.QFrame()
        self.mini_bar.setObjectName("MiniBar")
        mini = QtWidgets.QHBoxLayout(self.mini_bar)
        mini.setContentsMargins(4, 2, 2, 2)
        mini.setSpacing(4)
        self.mini_grip = QtWidgets.QLabel()
        self.mini_grip.setFixedSize(18, 26)
        self.mini_grip.setAlignment(Qt.AlignCenter)
        self.mini_grip.setCursor(Qt.SizeAllCursor)
        self.mini_grip.setToolTip("Drag to move")
        themes.bind_icon(self.mini_grip, "grip-vertical", "iconMuted", 16)
        self.mini_grip.installEventFilter(self)
        mini.addWidget(self.mini_grip)
        mini.addWidget(BrandIcon(themes, 16))
        self.mini_title = QtWidgets.QPushButton(title)
        self.mini_title.setObjectName("MiniTitle")
        self.mini_title.setCursor(Qt.PointingHandCursor)
        self.mini_title.setToolTip("Open MaxPkg Manager again")
        self.mini_title.installEventFilter(self)  # a click opens the window, a drag moves the bar
        mini.addWidget(self.mini_title, 1)
        mini_close = IconButton("x", "Close MaxPkg Manager", themes)
        mini_close.setObjectName("ChromeButton")
        mini_close.setFixedSize(26, 26)
        mini_close.clicked.connect(window.close)
        mini.addWidget(mini_close)
        self.mini_bar.hide()

    @property
    def collapsed(self):
        return self._mini is not None

    # --- title bar and collapsed bar mouse handling ------------------------------------------
    def eventFilter(self, watched, event):
        kind = event.type()
        window = self.window
        if watched in (self.mini_grip, self.mini_title):
            if kind == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag = event_global_pos(event) - window.frameGeometry().topLeft()
                self._drag_from = event_global_pos(event)
                self._dragged = False
                return True
            if kind == QtCore.QEvent.MouseMove and self._drag is not None:
                if (event_global_pos(event) - self._drag_from).manhattanLength() > 4:
                    self._dragged = True
                if self._dragged:
                    window.move(bounded_position(event_global_pos(event) - self._drag, window.frameGeometry().size(),
                                                 event_global_pos(event)))
                return True
            if kind == QtCore.QEvent.MouseButtonRelease and self._drag is not None:
                self._drag = None
                if self._dragged:
                    self._remember_mini()
                elif watched is self.mini_title:
                    QtCore.QTimer.singleShot(0, self.restore)
                return True
            return False
        if watched is self.title_bar and self.title_bar is not None:
            if kind == QtCore.QEvent.MouseButtonDblClick and event.button() == Qt.LeftButton:
                if self.collapsible:
                    window.showNormal() if window.isMaximized() else window.showMaximized()
                return True
            if kind == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag = event_global_pos(event) - window.frameGeometry().topLeft()
                return True
            if kind == QtCore.QEvent.MouseMove and self._drag is not None:
                if window.isMaximized():  # dragging a maximised window restores it under the cursor
                    ratio = float(self._drag.x()) / max(1, window.width())
                    window.showNormal()
                    self._drag = QtCore.QPoint(int(window.width() * ratio), self._drag.y())
                window.move(event_global_pos(event) - self._drag)
                return True
            if kind == QtCore.QEvent.MouseButtonRelease:
                self._drag = None
        if watched is self._host and kind == QtCore.QEvent.Move and self._mini is not None:
            self._follow_host()
        return False

    # --- edge resizing (called from the window's mouse events) ---------------------------
    def edges(self, pos):
        window = self.window
        if self._mini is not None or window.isMaximized():
            return 0
        x, y, width, height, edge = pos.x(), pos.y(), window.width(), window.height(), EDGE + 2
        return ((1 if x <= edge else 0) | (2 if x >= width - edge else 0) | (4 if y <= edge else 0) |
                (8 if y >= height - edge else 0))

    def mouse_press(self, event):
        edges = self.edges(event.pos())
        if edges and event.button() == Qt.LeftButton:
            self._resizing = (edges, event_global_pos(event), self.window.geometry())
            return True
        return False

    def mouse_move(self, event):
        window = self.window
        if self._resizing is not None:
            edges, start, geometry = self._resizing
            delta = event_global_pos(event) - start
            rect = QtCore.QRect(geometry)
            minimum = window.minimumSize()
            if edges & 1:
                rect.setLeft(min(rect.left() + delta.x(), rect.right() - minimum.width()))
            if edges & 2:
                rect.setRight(max(rect.right() + delta.x(), rect.left() + minimum.width()))
            if edges & 4:
                rect.setTop(min(rect.top() + delta.y(), rect.bottom() - minimum.height()))
            if edges & 8:
                rect.setBottom(max(rect.bottom() + delta.y(), rect.top() + minimum.height()))
            window.setGeometry(rect)
            return True
        cursor = _CURSORS.get(self.edges(event.pos()))
        if cursor is not None:
            window.setCursor(cursor)
        else:
            window.unsetCursor()
        return False

    def mouse_release(self, _event):
        self._resizing = None

    # --- collapse / restore ------------------------------------------------------------
    def collapse(self):
        window = self.window
        if self._mini is not None:
            return
        if window.isMaximized():
            window.showNormal()
        if hasattr(window, "before_collapse"):
            window.before_collapse()
        parts = [part for part in window.chrome_parts() if part.isVisible()]
        self._mini = (window.geometry(), window.minimumSize(), parts)
        for part in parts:
            part.hide()
        self.mini_bar.show()
        window.setMinimumSize(0, 0)
        hint = self.mini_bar.sizeHint()
        size = QtCore.QSize(max(250, hint.width()) + 2 * EDGE, hint.height() + 2 * EDGE)
        window.resize(size)
        saved = self.saved_mini
        if saved is not None and saved.x() >= 0 and saved.y() >= 0 and \
                QtWidgets.QApplication.screenAt(saved + QtCore.QPoint(10, 10)) is not None:
            window.move(bounded_position(saved, size))
        else:
            window.move(bounded_position(self._mini_home(size), size))
        self._watch_host(True)

    def _mini_home(self, size):
        """Bottom-left of 3ds Max, above the time slider, when the user has not placed the bar yet."""
        host = self.window.parentWidget()
        if host is None:
            area = QtWidgets.QApplication.primaryScreen().availableGeometry()
            return QtCore.QPoint(area.left() + MINI_GAP, area.bottom() - size.height() - MINI_GAP)
        frame = host.frameGeometry()
        return QtCore.QPoint(frame.left() + MINI_GAP, frame.bottom() - size.height() - 110)

    def restore(self):
        if self._mini is None:
            return
        self._watch_host(False)
        geometry, minimum, parts = self._mini
        self._mini = None
        self.mini_bar.hide()
        for part in parts:
            part.show()
        window = self.window
        window.setMinimumSize(minimum)
        window.setGeometry(geometry)
        window.raise_()
        window.activateWindow()

    def _remember_mini(self):
        self.saved_mini = self.window.pos()
        if self.on_mini_position is not None:
            self.on_mini_position(self.saved_mini)

    def _watch_host(self, on):
        """While collapsed the bar moves together with 3ds Max's main window."""
        if self._host is not None and is_valid(self._host):
            self._host.removeEventFilter(self)
        self._host = None
        if on and self.window.parentWidget() is not None:
            self._host = self.window.parentWidget()
            self._host_pos = self._host.pos()
            self._host.installEventFilter(self)

    def _follow_host(self):
        if self._host is None or not is_valid(self._host):
            return
        position = self._host.pos()
        delta = position - self._host_pos
        self._host_pos = position
        if position.x() < -30000:  # Windows parks a minimised window at (-32000, -32000)
            return
        window = self.window
        window.move(bounded_position(window.pos() + delta, window.size()))

    def stop(self):
        self._watch_host(False)


def paint_frame(widget, theme):
    """1 px window border so the frameless window stays readable on any background."""
    painter = QtGui.QPainter(widget)
    painter.setPen(theme.color("borderStrong"))
    painter.drawRect(widget.rect().adjusted(0, 0, -1, -1))
    painter.end()


__all__ = ["WindowChrome", "BrandIcon", "EDGE", "paint_frame", "icons"]
