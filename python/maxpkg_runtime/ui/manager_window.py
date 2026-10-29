"""MaxPkg Manager window: header, tabs, filters, Discover/Installed/Details pages, status bar, overlays.

Layout, texts and responsive breakpoints follow the HTML Manager 1.2.0 (docs/ORIGINAL-SPEC.md).
"""

import math
import os

from ..services import max_api
from ..qt_compat import (QShortcut, QtCore, QtGui, QtWidgets, Qt, Signal, disable_max_accelerators, exec_menu,
                         is_valid)
from . import icons
from .details import SINGLE_COLUMN, DetailsPage
from .dialogs import ask_support, confirm
from .frame import (EDGE, WindowChrome, apply_native_frame, bounded_position, glass_border, native_event,
                    paint_window_shape, prepare_window)
from .pages import WIDE_DISCOVER, DiscoverPage, InstalledPage
from .settings_panel import SettingsPanel
from .widgets import (BrandLogo, Button, ClearableDropdown, IconButton, IconLabel, SearchBox, SlideView, add_action,
                      add_danger_action, add_menu_title, hbox, label, themed_menu, vbox)

MIN_WIDTH = 680
HEADER_ICON_ONLY = 850  # 720 in the HTML Manager; the header now also holds the window and Support buttons
DISCOVER_SORTS = (("popular", "Popular"), ("newest", "Newest"), ("rating", "Rating"), ("downloads", "Downloads"),
                  ("name", "Name"))
INSTALLED_SORTS = (("toolbar", "Toolbar order"), ("name", "Name"), ("developer", "Developer"), ("version", "Version"))
INSTALLED_FILTERS = (("all", "All"), ("toolbar", "In toolbar"), ("hidden", "Hidden"))


class TabButton(QtWidgets.QPushButton):
    def __init__(self, text, parent=None):
        QtWidgets.QPushButton.__init__(self, text, parent)
        self.setObjectName("TabButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.count = label("0", "TabCount", parent=self)
        self.count.setAlignment(Qt.AlignCenter)
        self._text = text

    def set_count(self, value):
        self.count.setVisible(value is not None)
        if value is not None:
            self.count.setText(str(value))
            self.count.adjustSize()
        self.setText(self._text + ("     " + " " * len(str(value)) if value is not None else ""))
        self._place()

    def _place(self):
        metrics = self.fontMetrics()
        x = 18 + metrics.horizontalAdvance(self._text) + 6
        self.count.move(x, (self.height() - self.count.height()) // 2)

    def resizeEvent(self, event):
        QtWidgets.QPushButton.resizeEvent(self, event)
        self._place()


class Toast(QtWidgets.QFrame):
    """Glass notification: an animated status icon on a tinted disc, a bold first line and a muted rest, a close
    button and a thin bar that shows the time left (it waits while the pointer is over the toast). It slides in
    from the right. A click anywhere closes it."""

    expired = Signal()  # it closed; screen toasts re-stack on it

    STATES = {"success": ("done", "success"), "error": ("error", "danger"), "warning": ("warning", "warning")}
    LIFETIME_MS = {"error": 8000, "warning": 6500}
    DEFAULT_LIFETIME_MS = 5200
    WIDTH = 340
    RADIUS = 14

    def __init__(self, text, kind, themes, parent, action=None, key=""):
        """`parent` None: a small window of its own (the screen corner toasts while the Manager is closed)."""
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("Toast")
        if parent is None:
            self.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
            self.setAttribute(Qt.WA_TranslucentBackground)  # the rounded corners stay round
            self.setAttribute(Qt.WA_ShowWithoutActivating)
            self.setStyleSheet(themes.qss())
        self.themes = themes
        self.kind = kind
        self.key = key
        state, self._token = self.STATES.get(kind, ("info", "accent"))
        self.icon = StatusIcon(themes, size=28)
        self.icon.set_state(state)
        disc = QtWidgets.QWidget()
        disc.setFixedSize(40, 40)
        disc_layout = hbox(self.icon, margins=(6, 6, 6, 6))
        disc.setLayout(disc_layout)
        self._disc = disc
        lines = (text or "").split("\n", 1)
        # Wrapped labels get an exact width, or the nested layout sizes them for a narrower one (gaps).
        text_width = self.WIDTH - 12 - 40 - 12 - 12 - 22 - 10
        title = label(lines[0], "ToastTitle", wrap=True)
        title.setFixedWidth(text_width)
        texts = vbox(title, spacing=3)
        if len(lines) > 1 and lines[1].strip():
            body = label(lines[1].strip(), "ToastBody", wrap=True)
            body.setFixedWidth(text_width)
            texts.addWidget(body)
        # `action`: one (label, icon, callback) or a list of them; the first is the main (primary) button.
        actions = [action] if isinstance(action, tuple) else list(action or [])
        if actions:
            buttons = hbox(spacing=8)
            for position, (action_text, action_icon, callback) in enumerate(actions):
                button = Button(action_text, action_icon, "primary" if position == 0 else "default", themes,
                                compact=True)
                button.clicked.connect(lambda _checked=False, run=callback: (self._expire(), run()))
                buttons.addWidget(button)
            buttons.addStretch(1)
            texts.addSpacing(6)
            texts.addLayout(buttons)
        if len(lines) > 1 or actions:
            texts.addStretch(1)
        close = IconButton("x", "Close", themes)
        close.setObjectName("ToastClose")
        close.setFixedSize(22, 22)
        themes.bind_icon(close, "x", "iconMuted", 14)
        close.clicked.connect(self._expire)
        row = hbox(spacing=12, margins=(12, 12, 10, 14))
        row.addWidget(disc, 0, Qt.AlignTop)
        row.addLayout(texts, 1)
        row.addWidget(close, 0, Qt.AlignTop)
        if (len(lines) == 1 or not lines[1].strip()) and not actions:
            row.setAlignment(texts, Qt.AlignVCenter)  # a single line sits beside the icon's middle
        self.setLayout(row)
        self.setFixedWidth(self.WIDTH)
        self.setAttribute(Qt.WA_Hover)
        # An offer stays longer: there is something to decide.
        self._lifetime = self.LIFETIME_MS.get(kind, self.DEFAULT_LIFETIME_MS) + (3000 if actions else 0)
        self._left = float(self._lifetime)
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(40)
        self._timer.timeout.connect(self._tick)
        self._timer.start()
        self._slide = QtCore.QPropertyAnimation(self, b"pos", self)
        self._slide.setDuration(260)
        self._slide.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._entered = False
        self._opacity = QtWidgets.QGraphicsOpacityEffect(self)
        self._opacity.setOpacity(0.0)
        self.setGraphicsEffect(self._opacity)
        self._fade = QtCore.QPropertyAnimation(self._opacity, b"opacity", self)
        self._fade.setDuration(220)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        # Drop the effect once visible: it renders through an offscreen buffer that let the page show through.
        self._fade.finished.connect(lambda: self.setGraphicsEffect(None))

    def place(self, point):
        """Move to `point`; the first time it slides in from the right and fades in."""
        if not self._entered:
            self._entered = True
            self.move(point + QtCore.QPoint(28, 0))
            self._slide.setStartValue(self.pos())
            self._slide.setEndValue(point)
            self._slide.start()
            self._fade.start()
        elif self._slide.state() == QtCore.QAbstractAnimation.Running:
            self._slide.setEndValue(point)
        else:
            self.move(point)

    def restart(self):
        """Full time again, and the icon draws itself once more."""
        self._left = float(self._lifetime)
        self._clock.restart()
        self.icon.set_state(self.icon.state())
        self.update()

    def _tick(self):
        elapsed = self._clock.restart()
        if not self.underMouse():  # reading a toast keeps it open
            self._left -= elapsed
        if self._left <= 0:
            self._expire()
            return
        self.update()

    def _expire(self):
        if is_valid(self):
            self._timer.stop()
            parent = self.parentWidget()
            self.hide()
            self.expired.emit()
            self.deleteLater()
            if parent is not None and hasattr(parent, "place_toasts"):
                QtCore.QTimer.singleShot(0, parent.place_toasts)

    def mousePressEvent(self, event):
        self._expire()

    def paintEvent(self, _event):
        theme = self.themes.manager
        accent = theme.color(self._token)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # Opaque: toasts sit over busy pages, any see-through lets buttons below show.
        top, bottom = QtGui.QColor(theme.color("surfaceRaised")), QtGui.QColor(theme.color("surfaceTertiary"))
        top.setAlpha(255)
        bottom.setAlpha(255)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        shape = QtGui.QPainterPath()
        shape.addRoundedRect(rect, self.RADIUS, self.RADIUS)
        painter.fillPath(shape, QtGui.QBrush(gradient))
        # A faint wash of the toast's color from the left, under the icon.
        wash = QtGui.QLinearGradient(rect.topLeft(), QtCore.QPointF(rect.left() + 140, rect.top()))
        tint = QtGui.QColor(accent)
        tint.setAlphaF(0.10)
        wash.setColorAt(0.0, tint)
        tint.setAlphaF(0.0)
        wash.setColorAt(1.0, tint)
        painter.fillPath(shape, QtGui.QBrush(wash))
        painter.setPen(QtGui.QPen(theme.color("borderStrong"), 1))
        painter.drawPath(shape)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 26), 1))  # the bright top edge of the glass
        painter.drawLine(QtCore.QPointF(rect.left() + self.RADIUS, rect.top() + 1),
                         QtCore.QPointF(rect.right() - self.RADIUS, rect.top() + 1))
        # Tinted disc behind the icon.
        disc = QtCore.QRectF(self._disc.geometry())
        fill = QtGui.QColor(accent)
        fill.setAlphaF(0.14)
        painter.setPen(Qt.NoPen)
        painter.setBrush(fill)
        painter.drawEllipse(disc)
        # Time left: a thin bar along the bottom, clipped to the rounded card.
        share = max(0.0, min(1.0, self._left / float(self._lifetime)))
        painter.setClipPath(shape)
        bar = QtGui.QColor(accent)
        bar.setAlphaF(0.75)
        painter.fillRect(QtCore.QRectF(rect.left(), rect.bottom() - 2.5, rect.width() * share, 2.5), bar)
        painter.end()


def _ease(progress):
    return 1.0 - (1.0 - progress) ** 3


def _round_pen(color, width):
    pen = QtGui.QPen(color, width)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    return pen


def _partial(points, fraction):
    """The first `fraction` (0..1) of a polyline, by length."""
    if fraction <= 0:
        return []
    lengths = [math.hypot(end[0] - start[0], end[1] - start[1]) for start, end in zip(points, points[1:])]
    left = sum(lengths) * min(1.0, fraction)
    drawn = [points[0]]
    for (start, end), length in zip(zip(points, points[1:]), lengths):
        if left >= length:
            drawn.append(end)
            left -= length
        else:
            share = left / length if length else 0.0
            drawn.append((start[0] + (end[0] - start[0]) * share, start[1] + (end[1] - start[1]) * share))
            break
    return drawn


class StatusIcon(QtWidgets.QWidget):
    """Animated operation icon drawn with QPainter, the same as TerraScoop's build card (QtSvg plays almost no SVG
    animation). running: the Lucide box draws itself (outline, inner edges, a pulse, a fade, again);
    done: the circle and then the tick draw in with a small spring; error: the alert icon draws in and shakes.
    The timer runs only while something moves.
    """

    SIZE = 44
    FPS = 30
    DONE_SECONDS = 0.9
    ERROR_SECONDS = 0.9
    LOOP = 2.4  # seconds per drawing loop of the box
    # Lucide "box" on its 24-unit grid: the outline (a hexagon) and the inner edges.
    BOX_OUTLINE = ((12, 2), (21, 7), (21, 17), (12, 22), (3, 17), (3, 7), (12, 2))
    BOX_INNER = (((3, 7), (12, 12), (21, 7)), ((12, 12), (12, 22)))

    def __init__(self, themes, size=SIZE, parent=None):
        """Drawn on a 44 px grid and scaled to `size`."""
        QtWidgets.QWidget.__init__(self, parent)
        self.themes = themes
        self._state = "running"
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(int(1000 / self.FPS))
        self._timer.timeout.connect(self._tick)

    def set_state(self, state):
        """'running', 'done', 'error', 'info' or 'warning'."""
        self._state = state
        self._clock.restart()
        if self.isVisible():
            self._timer.start()
        self.update()

    def state(self):
        return self._state

    def _elapsed(self):
        return self._clock.elapsed() / 1000.0

    def _tick(self):
        finished = self.DONE_SECONDS if self._state == "done" else self.ERROR_SECONDS
        if self._state != "running" and self._elapsed() > finished + 0.2:
            self._timer.stop()
        self.update()

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        self._timer.start()

    def hideEvent(self, event):
        self._timer.stop()
        QtWidgets.QWidget.hideEvent(self, event)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.scale(self.width() / float(self.SIZE), self.height() / float(self.SIZE))
        theme = self.themes.manager
        elapsed = self._elapsed()
        progress = min(1.0, elapsed / self.ERROR_SECONDS)
        if self._state == "running":
            self._paint_running(painter, elapsed, theme.color("accent"))
        elif self._state == "done":
            self._paint_done(painter, min(1.0, elapsed / self.DONE_SECONDS), theme.color("success"))
        elif self._state == "info":
            self._paint_info(painter, progress, theme.color("accent"))
        elif self._state == "warning":
            self._paint_error(painter, progress, theme.color("warning"), hop=True)
        else:
            self._paint_error(painter, progress, theme.color("danger"))
        painter.end()

    def _paint_running(self, painter, elapsed, accent):
        phase = (elapsed % self.LOOP) / self.LOOP
        outline = _ease(min(1.0, phase / 0.45))
        inner = _ease(max(0.0, min(1.0, (phase - 0.35) / 0.3)))
        pulse = 1.0 + 0.06 * math.sin(max(0.0, min(1.0, (phase - 0.7) / 0.15)) * math.pi) if phase > 0.7 else 1.0
        alpha = 1.0 if phase < 0.88 else max(0.0, 1.0 - (phase - 0.88) / 0.12)
        painter.translate(self.SIZE / 2.0, self.SIZE / 2.0)
        painter.scale(pulse * self.SIZE / 26.0, pulse * self.SIZE / 26.0)
        painter.translate(-12.0, -12.0)
        faint = QtGui.QColor(accent)
        faint.setAlpha(40)
        painter.setPen(_round_pen(faint, 1.6))
        for line in self._box_paths(1.0, 1.0):
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in line]))
        color = QtGui.QColor(accent)
        color.setAlphaF(alpha)
        painter.setPen(_round_pen(color, 1.9))
        for line in self._box_paths(outline, inner):
            if len(line) > 1:
                painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(x, y) for x, y in line]))

    def _box_paths(self, outline, inner):
        """The box's lines, each cut to the drawn fraction."""
        paths = [_partial(self.BOX_OUTLINE, outline)]
        paths.extend(_partial(line, inner) for line in self.BOX_INNER)
        return paths

    def _paint_done(self, painter, progress, color):
        eased = _ease(progress)
        spring = 1.0 + 0.07 * math.sin(max(0.0, (progress - 0.66) / 0.34) * math.pi) if progress > 0.66 else 1.0
        painter.translate(self.SIZE / 2.0, self.SIZE / 2.0)
        painter.scale(spring, spring)
        painter.translate(-self.SIZE / 2.0, -self.SIZE / 2.0)
        ring = QtCore.QRectF(4, 4, self.SIZE - 8, self.SIZE - 8)  # room for the spring
        painter.setPen(_round_pen(color, 2.6))
        painter.drawArc(ring, 90 * 16, int(-360.0 * min(1.0, eased / 0.6) * 16))
        tick = max(0.0, min(1.0, (eased - 0.45) / 0.45))
        if tick > 0:
            # Lucide circle-check's tick on a 24 grid, scaled to the icon.
            scale = (self.SIZE - 8) / 20.0
            points = [QtCore.QPointF(4 + (x - 2) * scale, 4 + (y - 2) * scale)
                      for x, y in ((8.5, 12.0), (11.0, 14.5), (15.5, 9.5))]
            first = math.hypot(points[1].x() - points[0].x(), points[1].y() - points[0].y())
            second = math.hypot(points[2].x() - points[1].x(), points[2].y() - points[1].y())
            length = (first + second) * tick
            path = QtGui.QPainterPath(points[0])
            if length <= first:
                path.lineTo(points[0] + (points[1] - points[0]) * (length / first))
            else:
                path.lineTo(points[1])
                path.lineTo(points[1] + (points[2] - points[1]) * ((length - first) / second))
            painter.setPen(_round_pen(color, 3.0))
            painter.drawPath(path)

    def _paint_info(self, painter, progress, color):
        """The circle draws in, the dot of the "i" pops in, then its stem grows downwards."""
        ring_part = _ease(min(1.0, progress / 0.45))
        stem_part = _ease(max(0.0, min(1.0, (progress - 0.5) / 0.35)))
        ring = QtCore.QRectF(4, 4, self.SIZE - 8, self.SIZE - 8)
        painter.setPen(_round_pen(color, 2.6))
        painter.drawArc(ring, 90 * 16, int(-360.0 * ring_part * 16))
        middle = self.SIZE / 2.0
        if progress > 0.38:
            pop = min(1.0, (progress - 0.38) / 0.12)
            painter.setPen(_round_pen(color, 3.0 + 1.2 * math.sin(pop * math.pi)))
            painter.drawPoint(QtCore.QPointF(middle, 14.5))
        if stem_part > 0:
            painter.setPen(_round_pen(color, 3.0))
            painter.drawLine(QtCore.QPointF(middle, 20.5), QtCore.QPointF(middle, 20.5 + 9.5 * stem_part))

    def _paint_error(self, painter, progress, color, hop=False):
        """The circle draws in, the "!" is drawn from the top, its dot pops in, and the icon shakes (an error)
        or makes a small hop (a warning)."""
        ring_part = _ease(min(1.0, progress / 0.45))
        bar_part = _ease(max(0.0, min(1.0, (progress - 0.35) / 0.3)))
        if hop:
            lift = -math.sin(max(0.0, min(1.0, (progress - 0.6) / 0.3)) * math.pi) * 3.0 if progress > 0.6 else 0.0
            painter.translate(0, lift)
        else:
            shake = math.sin((progress - 0.45) * math.pi * 8) * 4.5 * (1.0 - progress) if progress > 0.45 else 0.0
            painter.translate(shake, 0)
        ring = QtCore.QRectF(4, 4, self.SIZE - 8, self.SIZE - 8)
        painter.setPen(_round_pen(color, 2.6))
        painter.drawArc(ring, 90 * 16, int(-360.0 * ring_part * 16))
        middle = self.SIZE / 2.0
        painter.setPen(_round_pen(color, 3.0))
        if bar_part > 0:
            painter.drawLine(QtCore.QPointF(middle, 13.5), QtCore.QPointF(middle, 13.5 + 11.0 * bar_part))
        if progress > 0.68:
            painter.drawPoint(QtCore.QPointF(middle, 31.0))


class WorkShade(QtWidgets.QWidget):
    """Frosted backdrop for package operations: a blurred snapshot of the window under a theme tint."""

    BLUR = 12  # the snapshot is shrunk by this factor and smoothly scaled back up

    def __init__(self, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.themes = themes
        self._backdrop = None

    def set_backdrop(self, snapshot):
        width = max(1, snapshot.width() // self.BLUR)
        height = max(1, snapshot.height() // self.BLUR)
        small = snapshot.scaled(width, height, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
        self._backdrop = small.scaled(snapshot.width(), snapshot.height(), Qt.IgnoreAspectRatio,
                                      Qt.SmoothTransformation)
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        if self._backdrop is not None:
            painter.drawPixmap(self.rect(), self._backdrop)
        painter.fillRect(self.rect(), self.themes.manager.color("overlay"))
        painter.end()


class BusyCard(QtWidgets.QFrame):
    """Glass card shown while a package operation runs: animated icon, message and a calm hint.

    Painted here (not QSS) so the glass can be nearly opaque: theme surfaces at ~92% over the frosted backdrop.
    """

    def __init__(self, themes, parent=None):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("BusyCard")
        self.themes = themes
        self.setFixedWidth(300)
        self.icon = StatusIcon(themes)
        self.title = label("Working...", "BusyTitle", wrap=True)
        self.hint = label("", "BusyHint", wrap=True)
        for text in (self.title, self.hint):
            text.setAlignment(Qt.AlignCenter)
        layout = vbox(spacing=6, margins=(24, 22, 24, 20))
        layout.addWidget(self.icon, 0, Qt.AlignHCenter)
        layout.addSpacing(6)
        layout.addWidget(self.title)
        layout.addWidget(self.hint)
        self.setLayout(layout)

    def set_message(self, message):
        """The operation is running."""
        self.icon.set_state("running")
        self.title.setText(message)
        self.hint.setText("This usually takes a few seconds.")
        self.adjustSize()

    def show_result(self, kind, text):
        """The operation ended: 'success' draws the tick, anything else the alert."""
        self.icon.set_state("done" if kind == "success" else "error")
        lines = (text or "").split("\n", 1)
        self.title.setText(lines[0])
        self.hint.setText(lines[1] if len(lines) > 1 else ("" if kind == "success" else "Nothing was changed."))
        self.hint.setVisible(bool(self.hint.text()))
        self.adjustSize()

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        top, bottom = QtGui.QColor(theme.color("surfaceRaised")), QtGui.QColor(theme.color("surfaceTertiary"))
        top.setAlphaF(0.94)
        bottom.setAlphaF(0.9)
        gradient = QtGui.QLinearGradient(rect.topLeft(), rect.bottomLeft())
        gradient.setColorAt(0.0, top)
        gradient.setColorAt(1.0, bottom)
        painter.setPen(QtGui.QPen(theme.color("borderStrong"), 1))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRoundedRect(rect, 18, 18)
        highlight = QtGui.QColor(255, 255, 255, 30)  # the bright top edge of the glass
        painter.setPen(QtGui.QPen(highlight, 1))
        painter.drawLine(QtCore.QPointF(rect.left() + 18, rect.top() + 1), QtCore.QPointF(rect.right() - 18, rect.top() + 1))
        painter.end()


BACKDROP_SCALE = 0.25  # the lightbox blurs a quarter-size copy of the window: cheap, and softer when scaled up
BACKDROP_BLUR = 10     # blur radius in pixels of that copy (about 40 px on the window)
BACKDROP_TINT = 0.55   # share of the theme's overlay colour kept over the blurred window


def blurred(pixmap, scale=BACKDROP_SCALE, radius=BACKDROP_BLUR):
    """A soft copy of `pixmap` at `scale` of its size (draw it stretched over the original area)."""
    small = pixmap.scaled(max(1, int(pixmap.width() * scale)), max(1, int(pixmap.height() * scale)),
                          Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small.setDevicePixelRatio(1.0)
    scene = QtWidgets.QGraphicsScene()
    item = QtWidgets.QGraphicsPixmapItem(small)
    effect = QtWidgets.QGraphicsBlurEffect()
    effect.setBlurRadius(radius)
    effect.setBlurHints(QtWidgets.QGraphicsBlurEffect.QualityHint)
    item.setGraphicsEffect(effect)
    # The blur fades the borders to transparent: render the item a little larger so they fall outside.
    margin = radius * 2
    item.setScale((small.width() + 2.0 * margin) / small.width())
    item.setPos(-margin, -margin * small.height() / float(small.width()))
    scene.addItem(item)
    result = QtGui.QImage(small.size(), QtGui.QImage.Format_ARGB32_Premultiplied)
    result.fill(Qt.transparent)
    painter = QtGui.QPainter(result)
    scene.render(painter, QtCore.QRectF(result.rect()), QtCore.QRectF(result.rect()))
    painter.end()
    return QtGui.QPixmap.fromImage(result)


class ScreenshotPreview(QtWidgets.QWidget):
    """Full-window screenshot viewer with previous/next and close (Esc). Like Fancybox, dragging the image up or
    down fades the backdrop and, past a short distance, throws the image off and closes; the backdrop fades in
    when it opens. The backdrop is the window behind it, blurred and tinted with the theme's overlay colour."""

    def __init__(self, window, shots, index):
        QtWidgets.QWidget.__init__(self, window)
        self.setObjectName("Lightbox")
        self.manager_window = window
        self.themes = window.themes
        self.shots = shots
        self.index = index
        self._shade = 0.0  # backdrop strength 0..1 (it paints itself so a drag can fade it)
        self._backdrop = blurred(window.grab(window.content_rect()))
        images = window.images
        self.image = SlideView(len(shots), lambda position: images.get(shots[position].url), window.themes,
                               inset=70, dismissible=True, parent=self)
        # Transparent over the blurred backdrop; unnamed, 3ds Max's own stylesheet paints it grey.
        self.image.setObjectName("LightboxSlides")
        self.image.set_index(index)
        self.image.index_changed.connect(self._on_index)
        self.image.dismiss_progress.connect(self._on_dismiss_progress)
        self.image.dismissed.connect(self.close_preview)
        self._fade_in = QtCore.QVariantAnimation(self)
        self._fade_in.setDuration(200)
        self._fade_in.setStartValue(0.0)
        self._fade_in.setEndValue(1.0)
        self._fade_in.valueChanged.connect(self._set_shade)
        self.caption = label("", "ToastText", parent=self)
        self.caption.setAlignment(Qt.AlignCenter)
        self.buttons = []
        for icon_name, step in (("gallery-chevron-left", -1), ("gallery-chevron-right", 1), ("x", 0)):
            button = QtWidgets.QPushButton(self)
            button.setObjectName("GalleryNav")
            button.setProperty("large", "true")  # perfectly round 40 px buttons in the lightbox
            button.setFixedSize(40, 40)
            button.setCursor(Qt.PointingHandCursor)
            button.setFocusPolicy(Qt.NoFocus)  # keep the keyboard on the lightbox (Esc, arrows)
            window.themes.bind_icon(button, icon_name, "textStrong", 20)
            button.clicked.connect(lambda _checked=False, delta=step: self._step(delta))
            self.buttons.append(button)
        window.images.ready.connect(lambda _source: self._paint())
        self.setFocusPolicy(Qt.StrongFocus)
        # 3ds Max accelerators swallow Esc and the arrow keys before Qt sees them.
        disable_max_accelerators(self)
        self.setGeometry(window.content_rect())
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.OtherFocusReason)
        self._paint()
        self._fade_in.start()

    def _set_shade(self, value):
        self._shade = float(value)
        self.update()

    def _on_dismiss_progress(self, progress):
        """The image is dragged up or down: the backdrop fades, the controls step aside until it comes back."""
        self._fade_in.stop()
        self._set_shade(1.0 - 0.85 * progress)
        resting = progress < 0.01
        for widget in self.buttons + [self.caption]:
            widget.setVisible(resting)

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        painter.setOpacity(self._shade)
        painter.drawPixmap(self.rect(), self._backdrop)
        painter.setOpacity(1.0)
        color = QtGui.QColor(self.themes.manager.color("backgroundOverlay"))
        color.setAlphaF(color.alphaF() * BACKDROP_TINT * self._shade)
        painter.fillRect(self.rect(), color)
        painter.end()

    def mousePressEvent(self, event):
        event.accept()  # clicks on the backdrop stay in the lightbox

    def close_preview(self):
        self.hide()
        self.deleteLater()

    def _step(self, delta):
        if delta == 0:
            self.close_preview()
            return
        self.image.slide(delta)  # animated; _on_index follows when it lands

    def _on_index(self, index):
        self.index = index
        self._paint()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self._step(0)
        elif key == Qt.Key_Left:
            self._step(-1)
        elif key == Qt.Key_Right:
            self._step(1)

    def _paint(self):
        if not is_valid(self):
            return
        shot = self.shots[self.index]
        # Full width so slides cross the whole lightbox; images are fitted 70 px in from each side.
        self.image.setGeometry(self.rect().adjusted(0, 40, 0, -80))
        self.image.refresh()
        self.caption.setText("<b>{}</b><br>{}".format(shot.title, shot.caption))
        self.caption.setGeometry(70, self.height() - 74, self.width() - 140, 60)
        middle = self.height() // 2 - 20
        self.buttons[0].move(18, middle)
        self.buttons[1].move(self.width() - 58, middle)
        self.buttons[2].move(self.width() - 58, 14)

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._paint()


class ManagerWindow(QtWidgets.QWidget):
    closed = Signal()

    def __init__(self, runtime, themes, images, toolbar, parent=None):
        QtWidgets.QWidget.__init__(self, parent, Qt.Window | Qt.FramelessWindowHint)
        self.setObjectName("ManagerRoot")
        self.setWindowTitle("MaxPkg Manager")
        self.setAttribute(Qt.WA_StyledBackground, False)
        prepare_window(self)  # Windows 11: DWM rounds and shadows the window; older systems: painted shape
        self.runtime = runtime
        self.themes = themes
        self.images = images
        self.toolbar = toolbar
        self.tab = "discover"
        self._before_details = "discover"
        self._toasts = []
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._run_discover_search)
        self._geometry_timer = QtCore.QTimer(self)  # moves/resizes are saved shortly after they stop
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(600)
        self._geometry_timer.timeout.connect(self.save_geometry)
        self._restoring = True
        self.setMinimumSize(MIN_WIDTH, 480)
        settings = runtime.settings
        self.chrome = WindowChrome(self, "MaxPkg Manager", themes,
                                   QtCore.QPoint(settings.manager_mini_x, settings.manager_mini_y),
                                   self._remember_mini_position)
        self._build()
        self._connect()
        self.apply_theme()
        self._restore_geometry()
        self._restoring = False

    # --- construction ---------------------------------------------------------------
    def _build(self):
        themes = self.themes
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(68)
        brand = BrandLogo(themes)
        self.version_label = label("Package Manager " + self.runtime.version, "BrandSubtitle")
        brand_text = vbox(label("maxpkg", "BrandTitle"), self.version_label, spacing=0, margins=(0, 2, 0, 2))
        self.configurator_button = Button("Toolbar Configurator", "panel-top", "default", themes)
        self.check_button = Button("Check Updates", "refresh-cw", "default", themes)
        self.update_all_button = Button("Update All", "download", "primary", themes)
        self.support_button = IconButton("heart", "Support MaxPkg", themes)
        themes.bind_icon(self.support_button, "heart", "iconSuccess", 16)
        self.settings_button = IconButton("settings", "Settings", themes)
        self._header_buttons = (self.configurator_button, self.check_button, self.update_all_button)
        brand_block = QtWidgets.QWidget()
        brand_block.setAttribute(Qt.WA_TransparentForMouseEvents)  # drags on the brand move the window
        brand_block.setLayout(hbox(brand, brand_text, spacing=9))
        # The original header is also the window's title bar (own chrome): drag to move, double-click to
        # maximise, collapse and close at the right end after a thin divider.
        divider = QtWidgets.QFrame()
        divider.setObjectName("HeaderDivider")
        divider.setFixedSize(1, 24)
        chrome_buttons = self.chrome.window_buttons("Close MaxPkg Manager")
        header.setLayout(hbox(brand_block, None, self.configurator_button, self.check_button,
                              self.update_all_button, self.support_button, self.settings_button, 4, divider, 4,
                              *chrome_buttons,
                              spacing=12, margins=(15, 13, 10, 13)))
        self.chrome.attach_title_bar(header)

        tabs = QtWidgets.QFrame()
        tabs.setObjectName("TabBar")
        tabs.setFixedHeight(43)
        self.tab_buttons = {"discover": TabButton("Discover"), "installed": TabButton("Installed"),
                            "updates": TabButton("Updates")}
        tabs.setLayout(hbox(self.tab_buttons["discover"], self.tab_buttons["installed"], self.tab_buttons["updates"],
                            None, spacing=0, margins=(15, 0, 15, 0)))

        self.page_toolbar = QtWidgets.QFrame()
        self.page_toolbar.setObjectName("PageToolbar")
        self.page_toolbar.setFixedHeight(48)
        self.search = SearchBox(themes, "Search Discover")
        self.category = ClearableDropdown(themes, [("", "All Categories")], "", "Filter Discover by category")
        self.discover_sort = ClearableDropdown(themes, DISCOVER_SORTS, "popular", "Sort Discover packages")
        self.installed_filter = ClearableDropdown(themes, INSTALLED_FILTERS, "all", "Filter installed packages")
        self.installed_sort = ClearableDropdown(themes, INSTALLED_SORTS, "toolbar", "Sort installed packages")
        for control in (self.category, self.discover_sort, self.installed_filter, self.installed_sort):
            control.dropdown.setMinimumWidth(150)
        self.category.dropdown.setMinimumWidth(190)
        self.page_toolbar.setLayout(hbox(self.search, self.category, self.discover_sort, self.installed_filter,
                                         self.installed_sort, spacing=10, margins=(16, 7, 16, 7)))
        self.page_toolbar.layout().setStretch(0, 1)

        self.details_nav = QtWidgets.QFrame()
        self.details_nav.setObjectName("DetailsNavigation")
        self.details_nav.setFixedHeight(48)
        back = QtWidgets.QPushButton("Back")
        back.setObjectName("TextLink")
        back.setCursor(Qt.PointingHandCursor)
        themes.bind_icon(back, "breadcrumb-arrow-left", "iconMuted", 14)
        back.clicked.connect(self.details_back)
        self.path_root = label("Installed", "Breadcrumb")
        self.path_name = label("Package", "BreadcrumbCurrent")
        self.details_nav.setLayout(hbox(back, label("/", "Breadcrumb"), self.path_root, label("/", "Breadcrumb"),
                                        self.path_name, None, spacing=8, margins=(16, 0, 16, 0)))

        self.stack = QtWidgets.QStackedWidget()
        self.discover_page = DiscoverPage(self)
        self.installed_page = InstalledPage(self)
        self.details_page = DetailsPage(self)
        for page in (self.discover_page, self.installed_page, self.details_page):
            self.stack.addWidget(page)

        status = QtWidgets.QFrame()
        status.setObjectName("StatusBar")
        status.setFixedHeight(28)
        self.package_status = label("0 packages")
        self.update_status = label("0 updates")
        self.website = QtWidgets.QPushButton("maxpkg.dev")
        self.website.setObjectName("StatusLink")
        self.website.setCursor(Qt.PointingHandCursor)
        self.website.setToolTip("Open the maxpkg.dev catalog in your browser")
        self.website.setLayoutDirection(Qt.RightToLeft)
        themes.bind_icon(self.website, "external-link", "successText", 11)
        self.footer_version = label("Package Manager " + self.runtime.version)
        self.connection_status = label("Offline")
        status.setLayout(hbox(self.package_status, 12, self.update_status, None, self.website, None,
                              self.footer_version, 14, self.connection_status, spacing=0, margins=(14, 0, 14, 0)))

        self.content = QtWidgets.QWidget()
        content_layout = vbox(header, tabs, self.page_toolbar, self.details_nav, self.stack, status, spacing=0)
        content_layout.setStretch(4, 1)
        self.content.setLayout(content_layout)
        root = vbox(self.chrome.mini_bar, self.content, spacing=0, margins=(EDGE, EDGE, EDGE, EDGE))
        root.setStretch(1, 1)
        self.setLayout(root)
        self.details_nav.hide()

        self.busy = WorkShade(themes, self)
        self.busy_card = BusyCard(themes, self.busy)
        self.busy.hide()
        # After an operation the card waits briefly for its result (runtime.notify follows busy_changed("")),
        # shows the tick or the alert, then hides.
        self._busy_finishing = False
        self._busy_toast = None  # (text, kind, action, key) shown when the card hides
        self._busy_timer = QtCore.QTimer(self)
        self._busy_timer.setSingleShot(True)
        self._busy_timer.timeout.connect(self._hide_busy)
        self.settings_panel = SettingsPanel(self, self)
        self.settings_panel.uninstall_requested.connect(self._runtime_uninstall)

    def _connect(self):
        runtime = self.runtime
        for key, button in self.tab_buttons.items():
            button.clicked.connect(lambda _checked=False, tab=key: self.show_tab(tab))
        self.configurator_button.clicked.connect(lambda: self.open_settings("toolbar"))
        self.settings_button.clicked.connect(lambda: self.open_settings(""))  # reopens the last page
        self.support_button.clicked.connect(self.ask_support)
        self.check_button.clicked.connect(lambda: runtime.check_updates(True))
        self.update_all_button.clicked.connect(runtime.update_all)
        self.website.clicked.connect(lambda: runtime.open_catalog())  # the site's catalog, not its home page
        self.search.textChanged.connect(self._on_search)
        self.search.returnPressed.connect(self._run_discover_search)
        self.category.changed.connect(self.select_category)
        self.discover_sort.changed.connect(self._on_discover_sort)
        self.installed_filter.changed.connect(lambda value: self._set_manager("manager_filter", value))
        self.installed_sort.changed.connect(lambda value: self._set_manager("manager_sort", value))
        runtime.packages_changed.connect(self._on_packages)
        runtime.catalog_changed.connect(self._on_catalog)
        runtime.busy_changed.connect(self._on_busy)
        runtime.notify.connect(self.notify)
        runtime.settings_changed.connect(self._on_settings)
        runtime.updates_checking_changed.connect(self._on_checking)
        self.themes.manager_changed.connect(self.apply_theme)
        # Keyboard: Ctrl+F search, Esc back from Details, F5 refresh, Ctrl+1..3 tabs, Ctrl+, Settings.
        shortcuts = (("Ctrl+F", self._focus_search), ("Escape", self._escape), ("F5", self.refresh_all),
                     ("Ctrl+1", lambda: self.show_tab("discover")), ("Ctrl+2", lambda: self.show_tab("installed")),
                     ("Ctrl+3", lambda: self.show_tab("updates")), ("Ctrl+,", lambda: self.open_settings("")))
        for sequence, slot in shortcuts:
            shortcut = QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(slot)

    def _focus_search(self):
        if self.tab == "details":
            self.details_back()
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self):
        # The window-wide Esc shortcut wins over the lightbox's keyPressEvent, so close an open lightbox here first.
        preview = getattr(self, "_preview", None)
        if preview is not None and is_valid(preview) and preview.isVisible():
            preview.close_preview()
        elif self.tab == "details":
            self.details_back()
        elif self.search.hasFocus() and self.search.text():
            self.search.clear()

    def refresh_all(self):
        self.runtime.scan()
        self.runtime.load_collections()
        self.runtime.browse()
        self.images.retry_failed()

    def disconnect_all(self):
        """Detach from long-lived Runtime signals before the window is deleted."""
        runtime = self.runtime
        pairs = ((runtime.packages_changed, self._on_packages), (runtime.catalog_changed, self._on_catalog),
                 (runtime.busy_changed, self._on_busy), (runtime.notify, self.notify),
                 (runtime.settings_changed, self._on_settings), (runtime.updates_checking_changed, self._on_checking),
                 (self.themes.manager_changed, self.apply_theme),
                 (runtime.settings_changed, self.settings_panel._on_settings_changed),
                 (runtime.details_changed, self.details_page._on_details))
        for signal, slot in pairs:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    # --- lifecycle ------------------------------------------------------------------
    def start(self, tab="", settings_page=""):
        self.installed_filter.set_value(self.runtime.settings.manager_filter)
        self.installed_sort.set_value(self.runtime.settings.manager_sort)
        self._on_packages()
        self.runtime.load_collections()
        self.runtime.browse()
        self.show_tab(tab or self.runtime.settings.manager_last_tab or "installed")
        self.content.setFocusPolicy(Qt.StrongFocus)  # no header button shows a focus ring on open
        self.content.setFocus()
        if settings_page:
            self.open_settings(settings_page)

    def _restore_geometry(self):
        """Last size and place (Manager.PositionX/Y, Width, Height, Maximized). A place that is no longer on
        any screen (monitor unplugged, resolution changed) falls back to the centre of 3ds Max."""
        settings = self.runtime.settings
        available = QtWidgets.QApplication.primaryScreen().availableGeometry()
        width = min(max(MIN_WIDTH, settings.manager_width), available.width())
        height = min(max(480, settings.manager_height), available.height())
        self.resize(width, height)
        x, y = settings.manager_position_x, settings.manager_position_y
        title_point = QtCore.QPoint(x + min(120, width // 2), y + 12)  # the title bar must stay reachable
        if x != -1 and y != -1 and QtWidgets.QApplication.screenAt(title_point) is not None:
            self.move(bounded_position(QtCore.QPoint(x, y), self.size(), title_point))
        else:
            parent = self.parentWidget()
            center = parent.frameGeometry().center() if parent is not None else available.center()
            self.move(bounded_position(QtCore.QPoint(center.x() - width // 2, center.y() - height // 2), self.size()))
        self._restore_maximized = settings.manager_maximized

    def show_restored(self):
        """First show: maximised again when it was left maximised."""
        if getattr(self, "_restore_maximized", False):
            self.showMaximized()
        else:
            self.show()

    def save_geometry(self):
        """Persist place, size, maximised state and tab. While collapsed the expanded geometry is saved."""
        if self._restoring:
            return
        self._geometry_timer.stop()
        settings = self.runtime.settings
        if self.chrome.collapsed:
            geometry = self.chrome._mini[0]
        elif self.isMaximized():
            geometry = self.normalGeometry()
        else:
            geometry = self.geometry()
        if geometry.width() >= MIN_WIDTH:
            settings.manager_position_x, settings.manager_position_y = geometry.x(), geometry.y()
            settings.manager_width, settings.manager_height = geometry.width(), geometry.height()
        settings.manager_maximized = self.isMaximized() and not self.chrome.collapsed
        settings.manager_last_tab = self.tab if self.tab != "details" else self._before_details
        self.runtime.save_settings("manager-geometry")

    def _remember_mini_position(self, point):
        settings = self.runtime.settings
        settings.manager_mini_x, settings.manager_mini_y = point.x(), point.y()
        self.runtime.save_settings("manager-geometry")

    def _schedule_geometry_save(self):
        if not self._restoring and not self.chrome.collapsed and self.isVisible():
            self._geometry_timer.start()

    def chrome_parts(self):
        return [self.content]

    def before_collapse(self):
        if self.settings_panel.isVisible():
            self.settings_panel.close_panel()

    def content_rect(self):
        return self.content.geometry()

    def closeEvent(self, event):
        self.save_geometry()
        self.chrome.stop()
        QtWidgets.QWidget.closeEvent(self, event)
        self.closed.emit()

    def moveEvent(self, event):
        QtWidgets.QWidget.moveEvent(self, event)
        self._schedule_geometry_save()

    def changeEvent(self, event):
        QtWidgets.QWidget.changeEvent(self, event)
        if event.type() == QtCore.QEvent.WindowStateChange:
            self._schedule_geometry_save()

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def leaveEvent(self, event):
        if self.chrome._resizing is None:
            self.unsetCursor()
        QtWidgets.QWidget.leaveEvent(self, event)

    # --- painting ------------------------------------------------------------------
    def background_brush(self):
        """The window's theme gradient in window coordinates (also drawn by the pages' fading edges)."""
        theme = self.themes.manager
        gradient = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, theme.color("backgroundGradientTop"))
        gradient.setColorAt(0.48, theme.color("surfaceSecondary"))
        gradient.setColorAt(1.0, theme.color("backgroundGradientBottom"))
        return QtGui.QBrush(gradient)

    def paintEvent(self, _event):
        """Theme gradient. Windows 11 rounds the window and adds the shadow (frame.apply_native_frame)."""
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        paint_window_shape(self, painter, self.background_brush(), glass_border(theme.color("surfaceSecondary")))
        painter.end()

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QWidget.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        apply_native_frame(self, glass_border(self.themes.color("surfaceSecondary")))

    def apply_theme(self):
        self.setStyleSheet(self.themes.qss())
        apply_native_frame(self, glass_border(self.themes.color("surfaceSecondary")))
        self.update()
        if self.isVisible():
            self.refresh_pages()

    # --- tabs and pages -------------------------------------------------------------
    def show_tab(self, tab):
        if tab not in ("discover", "installed", "updates"):
            tab = "installed"
        self.tab = tab
        for key, button in self.tab_buttons.items():
            button.setChecked(key == tab)
        self.details_nav.hide()
        self.page_toolbar.show()
        discover = tab == "discover"
        self.search.setPlaceholderText("Search Discover" if discover else "Search installed packages")
        self.search.blockSignals(True)
        self.search.setText(self.runtime.query.text if discover else self.installed_page.search)
        self.search.blockSignals(False)
        self._update_tools()
        if discover:
            self.stack.setCurrentWidget(self.discover_page)
            self.discover_page.refresh()
        else:
            self.installed_page.view = tab
            self.stack.setCurrentWidget(self.installed_page)
            self.installed_page.refresh()

    def _update_tools(self):
        discover = self.tab == "discover"
        wide = self.width() >= WIDE_DISCOVER
        has_categories = bool(self.runtime.catalog.categories)
        self.category.setVisible(discover and not wide and has_categories)
        self.discover_sort.setVisible(discover)
        self.installed_filter.setVisible(not discover)
        self.installed_sort.setVisible(not discover and self.tab != "updates")

    def refresh_pages(self):
        current = self.stack.currentWidget()
        if current is self.discover_page:
            self.discover_page.refresh()
        elif current is self.installed_page:
            self.installed_page.refresh()
        elif current is self.details_page:
            self.details_page.refresh()

    def open_details(self, guid, tab=""):
        """`tab`: open on that Details tab ("changelog"), otherwise on Description."""
        if self.tab != "details":
            self._before_details = self.tab
        self.tab = "details"
        self.page_toolbar.hide()
        self.details_nav.show()
        self.stack.setCurrentWidget(self.details_page)
        self.details_page.set_single_column(self.width() < SINGLE_COLUMN)
        self.details_page.show_package(guid)
        if tab:
            self.details_page.show_tab(tab)

    def set_details_path(self, package):
        installed = self.runtime.package(package.guid) is not None and self._before_details != "discover"
        self.path_root.setText("Installed" if installed else "Discover")
        self.path_name.setText(package.display_name)

    def details_back(self):
        self.show_tab(self._before_details)

    def open_settings(self, page=""):
        self.settings_panel.open_page(page)

    def ask_support(self):
        """Header heart: why MaxPkg needs donations; Donate opens the donation page in the browser."""
        if ask_support(self, self.themes):
            self.runtime.open_link(_SITE, "purchase")

    # --- actions used by cards/pages ------------------------------------------------
    def run(self, guid):
        self.runtime.run(guid)

    def install(self, guid):
        self.runtime.install(guid)

    def update_package(self, guid):
        self.runtime.update(guid)

    def uninstall(self, guid):
        package = self.runtime.package(guid)
        if package is None:
            return
        accepted = confirm(self, self.themes, "Uninstall {}?".format(package.display_name),
                           "The package files, its 3ds Max buttons and menu entries will be removed. "
                           "Your scenes are not changed.", "Uninstall", "trash-2", danger=True, icon_name="trash-2")
        if accepted and self.runtime.uninstall(guid) and self.tab == "details":
            self.details_back()

    def package_menu(self, guid, anchor, position=None, remote=None):
        """The card's actions below `anchor` (its ... button), or at the global `position` (a right-click).
        `remote`: the catalog package of a Discover card, for a package that is not installed."""
        package = self.runtime.package(guid)
        if package is None and remote is None:
            return
        themes = self.themes
        menu = themed_menu(self)
        self._menu_title(menu, package or remote)
        if package is None:
            self._remote_actions(menu, remote)
        else:
            self._installed_actions(menu, package)
        exec_menu(menu, position if position is not None else anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + 4)))
        menu.deleteLater()

    def _menu_title(self, menu, package):
        # The same header as the toolbar's menu: the script, its byline and (when set) a link to its Donate page.
        byline = "v" + package.version + (" · " + package.developer if package.developer else "")
        purchase = package.purchase_label() if package.purchase_url else ""
        add_menu_title(menu, package.display_name, self.themes,
                       pixmap=self.images.get(package.icon_file or package.icon_url), icon_name="package",
                       subtitle=byline, on_click=(lambda: self.open_purchase(package)) if package.purchase_url else None,
                       link_icon="heart" if purchase.lower() in ("donate", "support", "sponsor") else "shopping-cart",
                       link_tip="{}: opens the author's page in your browser".format(purchase or "Donate"))

    def _site_actions(self, menu, package):
        """Package page and Copy link (packages from the catalog), Help (when the package has documentation)."""
        themes = self.themes
        if package.documentation_url:
            add_action(menu, "Help", lambda: self.runtime.open_link(package, "documentation"), themes, "book-open")
        if package.slug:
            add_action(menu, "Package page", lambda: self.runtime.open_link(package, "maxpkg"), themes,
                       "external-link")
            add_action(menu, "Copy link", lambda: self.copy_text(self.runtime.link_url(package, "maxpkg"),
                                                                 "Link copied."), themes, "copy")

    def _remote_actions(self, menu, package):
        """Discover card of a package that is not installed."""
        guid = package.guid
        themes = self.themes
        add_action(menu, "Install", lambda: self.install(guid), themes, "download", "iconSuccess")
        add_action(menu, "Details", lambda: self.open_details(guid), themes, "info")
        menu.addSeparator()
        self._site_actions(menu, package)

    def _installed_actions(self, menu, package):
        guid = package.guid
        developer = self.runtime.settings.developer_mode
        themes = self.themes
        if package.update_available:  # first: it is why the card is in Updates
            add_action(menu, "Update to " + package.latest_version, lambda: self.update_package(guid), themes,
                       "download", "iconSuccess")
            add_action(menu, "What's new", lambda: self.open_details(guid, "changelog"), themes, "sparkles")
            menu.addSeparator()
        add_action(menu, "Run", lambda: self.run(guid), themes, "play")
        add_action(menu, "Details", lambda: self.open_details(guid), themes, "info")
        if developer:
            add_action(menu, "Open Folder", lambda: self.runtime.open_folder(guid), themes, "folder-open")
        self._site_actions(menu, package)
        menu.addSeparator()
        on_toolbar = self.runtime.is_on_toolbar(package)
        add_action(menu, "Hide from Toolbar" if on_toolbar else "Show in Toolbar",
                   lambda: self.set_on_toolbar(guid, not on_toolbar), themes, "eye-off" if on_toolbar else "eye")
        if developer:
            menu.addSeparator()
            add_action(menu, "Copy GUID", lambda: self.copy_text(package.guid, "GUID copied."), themes, "copy")
            add_action(menu, "Copy Path", lambda: self.copy_text(package.install_path, "Path copied."), themes, "copy")
        menu.addSeparator()
        add_danger_action(menu, "Uninstall", lambda: self.uninstall(guid), themes)

    def open_purchase(self, package):
        if self.runtime.open_link(package, "purchase"):
            self.notify("Opened the {} page of {} in your browser.\nThank you for supporting the author.".format(
                package.purchase_label(), package.display_name), "success")

    def set_on_toolbar(self, guid, visible):
        package = self.runtime.package(guid)
        if package is None or not self.runtime.set_toolbar_visible(guid, visible):
            return
        if visible:
            self.notify("{} is on the toolbar again.".format(package.display_name), "success")
        else:
            self.notify("{} is hidden from the toolbar.\nIt stays installed; show it again any time.".format(
                package.display_name), "info", action=("Show", "eye", lambda: self.set_on_toolbar(guid, True)))

    def copy_text(self, text, message):
        QtWidgets.QApplication.clipboard().setText(text)
        self.notify(message, "success")

    def preview_screenshots(self, shots, index):
        if shots:
            self._preview = ScreenshotPreview(self, shots, index)

    def reset_toolbar_position(self):
        if self.toolbar is not None:
            self.toolbar.reset_floating_position()

    def select_collection(self, value):
        query = self.runtime.query.copy()
        query.page = 1
        query.featured = value == "featured"
        query.collection = "" if value in ("all", "featured") else value
        query.category = ""
        self.category.set_value("")
        self.runtime.browse(query)

    def select_category(self, slug):
        query = self.runtime.query.copy()
        query.page = 1
        query.category = slug or ""
        query.featured = False
        query.collection = ""
        self.category.set_value(query.category)
        self.runtime.browse(query)

    def _on_discover_sort(self, value):
        query = self.runtime.query.copy()
        query.sort = value or "popular"
        query.page = 1
        self.runtime.browse(query)

    def _on_search(self, text):
        if self.tab == "discover":
            self._search_timer.start()
        else:
            self.installed_page.search = text.strip()
            self.installed_page.refresh()

    def _run_discover_search(self):
        if self.tab != "discover":
            return
        query = self.runtime.query.copy()
        if query.text == self.search.text().strip():
            return
        query.text = self.search.text().strip()
        query.page = 1
        self.runtime.browse(query)

    def _set_manager(self, attribute, value):
        setattr(self.runtime.settings, attribute, value)
        self.runtime.save_settings("manager")
        if self.tab in ("installed", "updates"):
            self.installed_page.refresh()

    def _runtime_uninstall(self):
        """Settings > Uninstall: run the installed uninstall.ms after this click has returned to the event loop
        (it stops this Runtime, so it must not run inside the window's own handler)."""
        script = os.path.join(str(self.runtime.root), "uninstall.ms")
        if not os.path.isfile(script):
            self.notify("uninstall.ms was not found next to the Package Manager.", "error")
            return
        self.settings_panel.close_panel()
        self.close()
        QtCore.QTimer.singleShot(0, lambda: max_api.file_in(script))

    # --- runtime -> view ----------------------------------------------------------------
    def _on_packages(self):
        runtime = self.runtime
        count = len(runtime.packages)
        updates = runtime.update_count()
        self.tab_buttons["installed"].set_count(count)
        self.tab_buttons["updates"].set_count(updates)
        self.package_status.setText("{} package{}".format(count, "" if count == 1 else "s"))
        self.update_status.setText("{} update{}".format(updates, "" if updates == 1 else "s"))
        self.update_all_button.setVisible(updates > 0)
        if self.tab in ("installed", "updates"):
            self.installed_page.refresh()
        elif self.tab == "discover":
            self.discover_page.refresh()
        elif self.tab == "details":
            self.details_page.refresh()

    def _on_catalog(self):
        catalog = self.runtime.catalog
        total = catalog.total_packages
        self.tab_buttons["discover"].set_count(total if total >= 0 else None)
        choices = [("", "All Categories")] + [(category.slug, category.name) for category in catalog.categories]
        self.category.set_choices(choices)
        self.category.set_value(self.runtime.query.category if not (self.runtime.query.featured or
                                                                    self.runtime.query.collection) else "")
        online = self.runtime.connection == "online"
        self.connection_status.setText("Online" if online else ("Offline" if self.runtime.connection == "offline"
                                                                else ""))
        self.connection_status.setProperty("tone", "success" if online else "warning")
        self.connection_status.style().polish(self.connection_status)
        self._update_tools()
        # Catalog requests are asynchronous: Discover shows its own loading state and the rest of the window
        # stays usable (the HTML Manager blocked everything because its requests froze 3ds Max).
        if self.tab == "discover":
            self.discover_page.refresh()

    BUSY_RESULT_WAIT_MS = 250
    BUSY_DONE_MS = 1400
    BUSY_ERROR_MS = 2600

    def _on_busy(self, message):
        if message:
            self._busy_timer.stop()
            self._busy_finishing = False
            pending, self._busy_toast = self._busy_toast, None
            if pending is not None:  # the next operation started before the card hid: keep its result
                self.notify(*pending)
            self._show_busy(message)
        elif self.busy.isVisible() and not self._busy_finishing and self.busy_card.icon.state() == "running":
            # A result already on the card keeps its own timer; a second "operation ended" must not cut it short.
            self._busy_finishing = True
            self._busy_timer.start(self.BUSY_RESULT_WAIT_MS)

    def _hide_busy(self):
        self._busy_finishing = False
        self.busy.hide()
        pending, self._busy_toast = self._busy_toast, None
        if pending is not None:
            self.notify(*pending)  # the result stays readable as a toast once the card is gone

    def _on_checking(self, checking):
        self.check_button.set_label("Checking updates..." if checking else "Check Updates")
        self.check_button.setEnabled(not checking)

    def _on_settings(self, area):
        if area in ("cards", "manager", "toolbar"):
            if self.tab in ("installed", "updates"):
                self.installed_page.refresh()
        if area == "developer" and self.tab == "details":
            self.details_page.refresh()

    def _show_busy(self, message):
        self.busy_card.set_message(message)
        area = self.content_rect()
        if not self.busy.isVisible():
            self.busy.set_backdrop(self.grab(area))  # what the frosted glass blurs
        self.busy.setGeometry(area)
        self._place_busy()
        self.busy.show()
        self.busy.raise_()

    def _place_busy(self):
        card = self.busy_card
        card.adjustSize()
        card.move((self.busy.width() - card.width()) // 2, max(0, int(self.busy.height() * 0.42) - card.height() // 2))

    def notify(self, text, kind="info", action=None, key=""):
        """A toast. `action`: (label, icon name, callback) adds a button; `key`: a toast with the same key that is
        still open is shown again for its full time instead of a second one."""
        if key:
            for toast in self._toasts:
                if is_valid(toast) and toast.isVisible() and toast.key == key:
                    toast.restart()
                    return
        if self._busy_finishing and kind in ("success", "error"):
            # The card shows the result first; the same message follows as a toast when the card hides.
            self._busy_finishing = False
            self.busy_card.show_result(kind, text)
            self._place_busy()
            self._busy_timer.start(self.BUSY_DONE_MS if kind == "success" else self.BUSY_ERROR_MS)
            self._busy_toast = (text, kind, action, key)
            return
        toast = Toast(text, kind, self.themes, self, action=action, key=key)
        toast.show()
        self._toasts = [item for item in self._toasts if is_valid(item) and item.isVisible()] + [toast]
        self.place_toasts()

    def notify_toolbar_locked(self):
        """Sorting was tried while the toolbar is locked: say so, with an Unlock button."""
        self.notify("The toolbar is locked.\nUnlock it to change the order of its buttons.", "warning",
                    action=("Unlock", "lock-open", self._unlock_toolbar), key="toolbar-locked")

    def _unlock_toolbar(self):
        if self.runtime.set_toolbar_locked(False):
            self.notify("The toolbar is unlocked.", "success")

    def place_toasts(self):
        area = self.content_rect()
        y = area.top() + 74
        alive = []
        for toast in self._toasts:
            if not is_valid(toast) or not toast.isVisible():
                continue
            toast.adjustSize()
            toast.place(QtCore.QPoint(area.right() - toast.width() - 14, y))
            toast.raise_()
            y += toast.height() + 8
            alive.append(toast)
        self._toasts = alive

    # --- responsive layout ----------------------------------------------------------
    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._schedule_geometry_save()
        if self.chrome.collapsed:
            return
        width = self.width() - 2 * EDGE
        icon_only = width < HEADER_ICON_ONLY
        for button in self._header_buttons:
            button.set_icon_only(icon_only)
        wide = width >= WIDE_DISCOVER
        if self.discover_page.wide != wide:
            self.discover_page.set_wide(wide)
        self._update_tools()
        self.details_page.set_single_column(width < SINGLE_COLUMN)
        self.busy.setGeometry(self.content_rect())
        self._place_busy()
        for child in self.findChildren(ScreenshotPreview):
            child.setGeometry(self.content_rect())
        self.place_toasts()


class _Site:
    """Pseudo package so the header's Support button reuses Runtime.open_link."""

    homepage_url = "https://maxpkg.dev"
    purchase_url = "https://store.payproglobal.com/checkout?products[1][id]=137822"  # MaxPkg donation
    documentation_url = support_url = license_url = ""
    slug = guid = ""


_SITE = _Site()

__all__ = ["ManagerWindow", "icons", "QtGui"]
