"""Shared controls. Every dialog composes these; none restyles them locally.

Variants are Qt properties read by assets/manager.qss (``variant``, ``badge``, ``compact``...).
"""

import math

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, disable_max_accelerators, event_pos, is_valid
from . import icons


def repolish(widget):
    """Re-apply stylesheet rules after a property change.

    `widget.style()` can return a wrapper whose C++ style is already gone when another tool replaced the
    application style (seen with TerraScoop in Max 2026). Re-setting the widget's own sheet re-polishes it.
    """
    try:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
    except RuntimeError:
        widget.setStyleSheet(widget.styleSheet() + " ")
    widget.update()


def hbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    layout = QtWidgets.QHBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for item in items:
        _add(layout, item)
    return layout


def vbox(*items, spacing=8, margins=(0, 0, 0, 0)):
    layout = QtWidgets.QVBoxLayout()
    layout.setContentsMargins(*margins)
    layout.setSpacing(spacing)
    for item in items:
        _add(layout, item)
    return layout


def _add(layout, item):
    if item is None:
        layout.addStretch(1)
    elif isinstance(item, int):
        layout.addSpacing(item)
    elif isinstance(item, QtWidgets.QLayout):
        layout.addLayout(item)
    else:
        layout.addWidget(item)


def label(text="", object_name="", wrap=False, parent=None):
    widget = QtWidgets.QLabel(text, parent)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


class Button(QtWidgets.QPushButton):
    """Text button with an optional Lucide icon. variant: default/primary/success/danger/installed."""

    def __init__(self, text="", icon_name="", variant="default", themes=None, compact=False, parent=None,
                 tooltip=""):
        QtWidgets.QPushButton.__init__(self, text, parent)
        self.setProperty("variant", variant)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.TabFocus)
        if compact:
            self.setProperty("compact", "true")
        if not text:
            self.setProperty("iconOnly", "true")
        if tooltip or not text:
            self.setToolTip(tooltip or text)
        self.icon_name = icon_name
        self._themes = themes
        self._full_text = text
        if icon_name and themes is not None:
            themes.bind_icon(self, icon_name, self._icon_token(), 16)

    def _icon_token(self):
        return {"primary": "textStrong", "success": "iconSuccess", "danger": "iconDanger",
                "installed": "iconSuccess"}.get(self.property("variant"), "iconPrimary")

    def set_variant(self, variant):
        self.setProperty("variant", variant)
        if self.icon_name and self._themes is not None:
            self._themes.bind_icon(self, self.icon_name, self._icon_token(), 16)
        repolish(self)

    def set_icon_only(self, icon_only):
        """Responsive header: collapse to the icon and keep the text as tooltip."""
        self.setText("" if icon_only else self._full_text)
        self.setProperty("iconOnly", "true" if icon_only else "false")
        self.setToolTip(self._full_text)
        self._reapply_icon()
        repolish(self)

    def set_label(self, text):
        self._full_text = text
        if self.property("iconOnly") != "true":
            self.setText(text)
        self.setToolTip(text)
        self._reapply_icon()

    def _reapply_icon(self):
        if self.icon_name and self._themes is not None:
            self._themes.reapply(self)

    def changeEvent(self, event):
        QtWidgets.QPushButton.changeEvent(self, event)
        if event.type() == QtCore.QEvent.LayoutDirectionChange:
            self._reapply_icon()


class IconButton(Button):
    def __init__(self, icon_name, tooltip, themes, parent=None):
        Button.__init__(self, "", icon_name, "default", themes, parent=parent, tooltip=tooltip)


class Badge(QtWidgets.QLabel):
    def __init__(self, text, kind="default", parent=None):
        QtWidgets.QLabel.__init__(self, text, parent)
        self.setProperty("badge", kind)
        self.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)


class IconLabel(QtWidgets.QLabel):
    def __init__(self, icon_name, themes, token="iconPrimary", size=16, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        self.setFixedSize(size, size)
        themes.bind_icon(self, icon_name, token, size)


class SearchBox(QtWidgets.QLineEdit):
    """Search field with the Lucide search glyph; 3ds Max shortcuts are disabled while typing."""

    def __init__(self, themes, placeholder="Search", parent=None):
        QtWidgets.QLineEdit.__init__(self, parent)
        self.setObjectName("SearchInput")
        self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(False)
        self._glyph = IconLabel("search", themes, "iconMuted", 16, self)
        self._glyph.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._clear = QtWidgets.QPushButton(self)
        self._clear.setObjectName("ClearButton")
        self._clear.setCursor(Qt.PointingHandCursor)
        self._clear.setToolTip("Clear search (Esc)")
        self._clear.setFocusPolicy(Qt.NoFocus)
        self._clear.setFixedSize(22, 22)
        themes.bind_icon(self._clear, "x", "iconMuted", 14)
        self._clear.clicked.connect(self.clear)
        self._clear.hide()
        self.textChanged.connect(lambda text: self._clear.setVisible(bool(text)))
        self.setTextMargins(0, 0, 22, 0)
        disable_max_accelerators(self)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape and self.text():
            self.clear()
            return
        QtWidgets.QLineEdit.keyPressEvent(self, event)

    def resizeEvent(self, event):
        QtWidgets.QLineEdit.resizeEvent(self, event)
        self._glyph.move(11, (self.height() - 16) // 2)
        self._clear.move(self.width() - 28, (self.height() - 22) // 2)


class Dropdown(QtWidgets.QComboBox):
    """Themed combo box with a Lucide chevron; `active` highlights a non-default choice."""

    def __init__(self, themes, choices=(), parent=None):
        QtWidgets.QComboBox.__init__(self, parent)
        self.setProperty("field", "true")
        self.setCursor(Qt.PointingHandCursor)
        self.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToContents)
        view = QtWidgets.QListView()
        self.setView(view)
        self.view().window().setWindowFlags(Qt.Popup | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        self.view().window().setAttribute(Qt.WA_TranslucentBackground)
        self._chevron = IconLabel("chevron-down", themes, "iconMuted", 14, self)
        self._chevron.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.set_choices(choices)

    def set_choices(self, choices, current=None):
        """choices: [(value, label)]; keeps the current value when it still exists."""
        wanted = current if current is not None else self.value()
        self.blockSignals(True)
        self.clear()
        for value, text in choices:
            self.addItem(text, value)
        index = self.findData(wanted)
        self.setCurrentIndex(index if index >= 0 else 0)
        self.blockSignals(False)

    def value(self):
        return self.currentData()

    def set_value(self, value):
        index = self.findData(value)
        if index >= 0 and index != self.currentIndex():
            self.blockSignals(True)
            self.setCurrentIndex(index)
            self.blockSignals(False)

    def set_active(self, active):
        if (self.property("active") == "true") != active:
            self.setProperty("active", "true" if active else "false")
            repolish(self)

    def resizeEvent(self, event):
        QtWidgets.QComboBox.resizeEvent(self, event)
        self._chevron.move(self.width() - 24, (self.height() - 14) // 2)


class ClearableDropdown(QtWidgets.QWidget):
    """Dropdown plus the small 'x' reset button the HTML Manager shows for a non-default choice."""

    changed = Signal(object)

    def __init__(self, themes, choices, default_value, tooltip, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.default_value = default_value
        self.dropdown = Dropdown(themes, choices, self)
        self.dropdown.setToolTip(tooltip)
        self.clear_button = QtWidgets.QPushButton(self)
        self.clear_button.setObjectName("ClearButton")
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setToolTip("Reset")
        themes.bind_icon(self.clear_button, "x", "iconMuted", 14)
        self.setLayout(hbox(self.dropdown, self.clear_button, spacing=4))
        self.dropdown.currentIndexChanged.connect(self._on_changed)
        self.clear_button.clicked.connect(lambda: self.set_value(self.default_value, emit=True))
        self._sync()

    def value(self):
        return self.dropdown.value()

    def set_value(self, value, emit=False):
        self.dropdown.set_value(value)
        self._sync()
        if emit:
            self.changed.emit(self.value())

    def set_choices(self, choices):
        self.dropdown.set_choices(choices)
        self._sync()

    def _on_changed(self, _index):
        self._sync()
        self.changed.emit(self.value())

    def _sync(self):
        is_default = self.value() == self.default_value
        self.clear_button.setVisible(not is_default)
        self.dropdown.set_active(not is_default)


class Switch(QtWidgets.QAbstractButton):
    """Green toggle switch with a text label (Settings rows)."""

    def __init__(self, text, themes, parent=None):
        QtWidgets.QAbstractButton.__init__(self, parent)
        self.setCheckable(True)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self._themes = themes
        self.setSizePolicy(QtWidgets.QSizePolicy.Preferred, QtWidgets.QSizePolicy.Fixed)

    def sizeHint(self):
        metrics = self.fontMetrics()
        return QtCore.QSize(45 + metrics.horizontalAdvance(self.text()) + 4, max(22, metrics.height() + 4))

    def paintEvent(self, _event):
        theme = self._themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        track = QtCore.QRectF(0.5, (self.height() - 18) / 2.0 + 0.5, 36, 18)
        checked = self.isChecked()
        painter.setPen(QtGui.QPen(theme.color("switchChecked" if checked else
                                              ("textDisabled" if self.underMouse() else "borderStrong")), 1))
        painter.setBrush(theme.color("switchChecked" if checked else "surfaceDisabled"))
        painter.drawRoundedRect(track, 9, 9)
        thumb_x = track.left() + (19 if checked else 1.5)
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("selectionBlueText"))
        painter.drawEllipse(QtCore.QRectF(thumb_x, track.top() + 1.5, 15, 15))
        painter.setPen(theme.color("textPrimary"))
        painter.drawText(QtCore.QRect(45, 0, self.width() - 45, self.height()), Qt.AlignVCenter | Qt.AlignLeft,
                         self.text())
        painter.end()

    def enterEvent(self, event):
        self.update()
        QtWidgets.QAbstractButton.enterEvent(self, event)

    def leaveEvent(self, event):
        self.update()
        QtWidgets.QAbstractButton.leaveEvent(self, event)


class ElidedLabel(QtWidgets.QLabel):
    """Single-line label that shows '...' instead of overflowing; the full text is the tooltip."""

    def __init__(self, text="", object_name="", parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        if object_name:
            self.setObjectName(object_name)
        self._full = text
        self.setMinimumWidth(10)
        self.setSizePolicy(QtWidgets.QSizePolicy.Ignored, QtWidgets.QSizePolicy.Preferred)
        self.setText(text)

    def set_full_text(self, text):
        self._full = text
        self._elide()

    def full_text(self):
        return self._full

    def _elide(self):
        shown = self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(10, self.width()))
        QtWidgets.QLabel.setText(self, shown)
        self.setToolTip(self._full if shown != self._full else "")

    def resizeEvent(self, event):
        QtWidgets.QLabel.resizeEvent(self, event)
        self._elide()

    def minimumSizeHint(self):
        return QtCore.QSize(10, QtWidgets.QLabel.minimumSizeHint(self).height())


class ElidedText(QtWidgets.QWidget):
    """Multi-line text that ends with '...' when it does not fit `max_lines`."""

    def __init__(self, text="", max_lines=6, object_name="CardDescription", line_height=18, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setObjectName(object_name)
        self._text = text
        self._max_lines = max_lines
        self._line_height = line_height
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.setFixedHeight(max_lines * line_height)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)

    def set_text(self, text):
        self._text = text
        self.update()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setPen(self.palette().color(QtGui.QPalette.WindowText))
        metrics = self.fontMetrics()
        layout = QtGui.QTextLayout(self._text, self.font())
        layout.beginLayout()
        lines = []
        while len(lines) < self._max_lines:
            line = layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(self.width())
            lines.append((line.textStart(), line.textLength()))
        layout.endLayout()
        top = (self._line_height - metrics.height()) / 2.0
        for index, (start, length) in enumerate(lines):
            piece = self._text[start:start + length].rstrip("\n")
            if index == len(lines) - 1 and start + length < len(self._text):
                remainder = self._text[start:].replace("\n", " ")
                piece = metrics.elidedText(remainder, Qt.ElideRight, self.width() - metrics.horizontalAdvance(".."))
                piece = piece.replace("…", "...")
            y = int(top + index * self._line_height + metrics.ascent())
            painter.drawText(0, y, piece)
        painter.end()


class StatePanel(QtWidgets.QFrame):
    """Centered empty/error state: icon, title, text and an optional action button."""

    def __init__(self, themes, icon_name, title, text, action_text="", action_icon="", parent=None):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("StatePanel")
        self.setFixedWidth(430)
        glyph = IconLabel(icon_name, themes, "iconMuted", 42)
        self.title = label(title, "StateTitle")
        self.text = label(text, "StateText", wrap=True)
        for widget in (self.title, self.text):
            widget.setAlignment(Qt.AlignCenter)
        items = [glyph, self.title, self.text]
        self.action = None
        if action_text:
            self.action = Button(action_text, action_icon, "default", themes)
            items.append(self.action)
        layout = vbox(spacing=10, margins=(28, 28, 28, 28))
        for widget in items:
            if isinstance(widget, QtWidgets.QLabel) and widget is not glyph:
                # Full width + centered text: an AlignHCenter layout item gives a wrapped label too little height.
                layout.addWidget(widget)
            else:
                layout.addWidget(widget, 0, Qt.AlignHCenter)
        self.setLayout(layout)


DRAG_THRESHOLD = 6  # px of movement before a press becomes a drag instead of a click
SWIPE_DISTANCE = 40  # px of horizontal drag that switches to the next/previous image


def _event_global(event):
    position = event.globalPosition() if hasattr(event, "globalPosition") else event.globalPos()
    return position.x(), position.y()


def _event_x(event):
    return _event_global(event)[0]


class DragScroll(QtCore.QObject):
    """Drag a horizontal QScrollArea (and the buttons inside it) with the mouse; a plain click still clicks."""

    def __init__(self, area):
        QtCore.QObject.__init__(self, area)
        self.area = area
        self._start = None  # (x, scroll value, pressed widget)
        self._dragging = False
        area.viewport().installEventFilter(self)
        area.viewport().setCursor(Qt.OpenHandCursor)

    def watch(self, widget):
        widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._start = (_event_x(event), self.area.horizontalScrollBar().value(), watched)
            self._dragging = False
        elif kind == QtCore.QEvent.MouseMove and self._start is not None and event.buttons() & Qt.LeftButton:
            delta = _event_x(event) - self._start[0]
            if not self._dragging and abs(delta) > DRAG_THRESHOLD:
                self._dragging = True
                self.area.viewport().setCursor(Qt.ClosedHandCursor)
                pressed = self._start[2]
                if isinstance(pressed, QtWidgets.QAbstractButton):
                    pressed.setDown(False)  # the drag must not end as a click
            if self._dragging:
                self.area.horizontalScrollBar().setValue(int(self._start[1] - delta))
                return True
        elif kind == QtCore.QEvent.MouseButtonRelease and self._start is not None:
            dragged = self._dragging
            self._start = None
            self._dragging = False
            if dragged:
                self.area.viewport().setCursor(Qt.OpenHandCursor)
                return True
        return False


class Swipe(QtCore.QObject):
    """Drag on a widget: `dragged(dx)` while it moves sideways, `released(dx)` when it ends, `clicked()` for a press
    and release without a drag. With `vertical=True` a drag that starts mostly up or down reports
    `dragged_vertical(dy)` / `released_vertical(dy)` instead (the direction is decided by the first pixels)."""

    dragged = Signal(int)
    released = Signal(int)
    dragged_vertical = Signal(int)
    released_vertical = Signal(int)
    clicked = Signal()

    def __init__(self, widget, vertical=False):
        QtCore.QObject.__init__(self, widget)
        self.vertical = vertical
        self._start = None
        self._axis = None  # None until the drag starts, then "x" or "y"
        self._cursor = None
        widget.installEventFilter(self)

    def _deltas(self, event):
        x, y = _event_global(event)
        return x - self._start[0], y - self._start[1]

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind == QtCore.QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
            self._start = _event_global(event)
            self._axis = None
            return True
        if kind == QtCore.QEvent.MouseMove and self._start is not None:
            dx, dy = self._deltas(event)
            if self._axis is None and max(abs(dx), abs(dy)) > DRAG_THRESHOLD:
                self._axis = "y" if self.vertical and abs(dy) > abs(dx) else "x"
                self._cursor = watched.cursor()
                watched.setCursor(Qt.ClosedHandCursor)
            if self._axis == "x":
                self.dragged.emit(int(dx))
            elif self._axis == "y":
                self.dragged_vertical.emit(int(dy))
            return self._axis is not None
        if kind == QtCore.QEvent.MouseButtonRelease and self._start is not None and event.button() == Qt.LeftButton:
            dx, dy = self._deltas(event)
            axis = self._axis
            self._start = None
            self._axis = None
            if axis is not None:
                watched.setCursor(self._cursor)
            if axis == "x":
                self.released.emit(int(dx))
            elif axis == "y":
                self.released_vertical.emit(int(dy))
            else:
                self.clicked.emit()
            return True
        return False


class SlideView(QtWidgets.QWidget):
    """Image carousel: the current image follows a horizontal drag with its neighbour sliding in beside it; a
    drag past SWIPE_DISTANCE (or `slide(step)`) animates to that neighbour, a shorter one springs back.

    `pixmap_for(index)` returns a QPixmap or None (still loading). `clicked()` is a press without a drag.
    """

    index_changed = Signal(int)
    clicked = Signal()
    dismiss_progress = Signal(float)  # 0..1 while the image is dragged up or down (dismissible only)
    dismissed = Signal()              # it was thrown off the screen: close the viewer
    GAP = 24
    DISMISS_DISTANCE = 110  # px of vertical drag that closes, like Fancybox; a shorter one springs back

    def __init__(self, count, pixmap_for, themes, radius=0, inset=2, dismissible=False, parent=None):
        """radius: rounded clip of the frame; inset: side margin each image is fitted into (slides still cross
        the whole widget); dismissible: drag the image up or down to close (the lightbox)."""
        QtWidgets.QWidget.__init__(self, parent)
        self.lift = 0.0  # vertical offset of the dragged image
        self._lift_animation = QtCore.QVariantAnimation(self)
        self._lift_animation.setDuration(260)
        self._lift_animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._lift_animation.valueChanged.connect(self._set_lift)
        self._lift_animation.finished.connect(self._lift_settled)
        self._dismissing = False
        self.setAttribute(Qt.WA_StyledBackground)  # the #ScreenshotMain frame still comes from the stylesheet
        self.count = count
        self.pixmap_for = pixmap_for
        self.themes = themes
        self.radius = radius
        self.inset = inset
        self.index = 0
        self.offset = 0.0
        self._scaled = {}  # index -> (source cacheKey, target size, scaled pixmap)
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setDuration(240)
        self._animation.setEasingCurve(QtCore.QEasingCurve.OutCubic)
        self._animation.valueChanged.connect(self._set_offset)
        self._animation.finished.connect(self._settle)
        self._target_step = 0
        # Preloader: a spinning arc where an image is still downloading; the timer runs only while one shows.
        self._spin = QtCore.QElapsedTimer()
        self._spin.start()
        self._spin_timer = QtCore.QTimer(self)
        self._spin_timer.setInterval(33)
        self._spin_timer.timeout.connect(self.update)
        self._swipe = Swipe(self, vertical=dismissible)
        self._swipe.dragged.connect(self._on_drag)
        self._swipe.released.connect(self._on_release)
        self._swipe.dragged_vertical.connect(self._on_lift)
        self._swipe.released_vertical.connect(self._on_lift_release)
        self._swipe.clicked.connect(self.clicked.emit)

    # --- drag up or down to dismiss (Fancybox style) ---------------------------------
    def _progress(self):
        return min(1.0, abs(self.lift) / max(1.0, self.height() * 0.45))

    def _set_lift(self, value):
        self.lift = float(value)
        self.update()
        self.dismiss_progress.emit(self._progress())

    def _on_lift(self, delta):
        self._lift_animation.stop()
        self._set_lift(delta)

    def _on_lift_release(self, delta):
        self._dismissing = abs(delta) >= self.DISMISS_DISTANCE
        end = (self.height() if delta > 0 else -self.height()) if self._dismissing else 0.0
        self._lift_animation.setDuration(220 if self._dismissing else 320)
        self._lift_animation.setEasingCurve(QtCore.QEasingCurve.InCubic if self._dismissing
                                            else QtCore.QEasingCurve.OutBack)
        self._lift_animation.setStartValue(float(self.lift))
        self._lift_animation.setEndValue(float(end))
        self._lift_animation.start()

    def _lift_settled(self):
        if self._dismissing:
            self._dismissing = False
            self.dismissed.emit()
        else:
            self._set_lift(0.0)

    def set_index(self, index):
        self._animation.stop()
        self.index = index % self.count if self.count else 0
        self.offset = 0.0
        self.update()
        self.index_changed.emit(self.index)

    def slide(self, step):
        """Animate to the next (+1) or previous (-1) image."""
        if self.count < 2:
            return
        if self._animation.state() == QtCore.QAbstractAnimation.Running:
            self._animation.stop()
            self._settle()
        self._animate_to(step)

    def refresh(self):
        self.update()

    def _span(self):
        return self.width() + self.GAP

    def _set_offset(self, value):
        self.offset = float(value)
        self.update()

    def _animate_to(self, step):
        self._target_step = step
        self._animation.setStartValue(float(self.offset))
        self._animation.setEndValue(float(-step * self._span()))
        self._animation.start()

    def _on_drag(self, delta):
        if self.count < 2:
            return
        self._animation.stop()
        self._set_offset(max(-self._span(), min(self._span(), delta)))

    def _on_release(self, delta):
        if self.count < 2:
            return
        self._animate_to(0 if abs(delta) < SWIPE_DISTANCE else (1 if delta < 0 else -1))

    def _settle(self):
        step, self._target_step = self._target_step, 0
        if step:
            self.index = (self.index + step) % self.count
            self.index_changed.emit(self.index)
        self.offset = 0.0
        self.update()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._scaled = {}

    def _scaled_pixmap(self, index, size):
        source = self.pixmap_for(index)
        if source is None:
            return None
        cached = self._scaled.get(index)
        if cached is not None and cached[0] == source.cacheKey() and cached[1] == size:
            return cached[2]
        dpr = self.devicePixelRatioF()
        # Never enlarge: a small screenshot keeps its real size, a large one shrinks to fit.
        natural = source.size()
        fitted = natural if natural.width() <= size.width() and natural.height() <= size.height() else \
            natural.scaled(size, Qt.KeepAspectRatio)
        scaled = source.scaled(int(fitted.width() * dpr), int(fitted.height() * dpr), Qt.KeepAspectRatio,
                               Qt.SmoothTransformation)
        scaled.setDevicePixelRatio(dpr)
        self._scaled[index] = (source.cacheKey(), size, scaled)
        return scaled

    def paintEvent(self, event):
        QtWidgets.QWidget.paintEvent(self, event)
        option = QtWidgets.QStyleOption()
        option.initFrom(self)
        painter = QtGui.QPainter(self)
        self.style().drawPrimitive(QtWidgets.QStyle.PE_Widget, option, painter, self)
        if not self.count:
            painter.end()
            return
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        frame = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        if self.radius:
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(frame, self.radius, self.radius)
            painter.setClipPath(clip)
        area = QtCore.QRectF(self.rect()).adjusted(self.inset, 2, -self.inset, -2)
        size = QtCore.QSize(int(area.width()), int(area.height()))
        if self.lift:
            # Dragged up or down: the image follows and shrinks a little (up to 15 %), around its centre.
            scale = 1.0 - 0.15 * self._progress()
            middle = area.center()
            painter.translate(middle.x(), middle.y() + self.lift)
            painter.scale(scale, scale)
            painter.translate(-middle.x(), -middle.y())
        neighbours = (-1, 0, 1) if self.count > 1 and not self.lift else (0,)
        loading = False
        for step in neighbours:
            left = area.left() + step * self._span() + self.offset
            if left - self.inset >= frame.right() or left + area.width() + self.inset <= frame.left():
                continue
            pixmap = self._scaled_pixmap((self.index + step) % self.count, size)
            if pixmap is None:
                loading = True
                self._paint_preloader(painter, QtCore.QPointF(left + area.width() / 2.0, area.center().y()))
                continue
            logical = pixmap.size() / pixmap.devicePixelRatio()
            target = QtCore.QRectF(left + (area.width() - logical.width()) / 2.0,
                                   area.top() + (area.height() - logical.height()) / 2.0,
                                   logical.width(), logical.height())
            painter.drawPixmap(target, pixmap, QtCore.QRectF(pixmap.rect()))
        painter.end()
        if loading and not self._spin_timer.isActive():
            self._spin_timer.start()
        elif not loading and self._spin_timer.isActive():
            self._spin_timer.stop()

    def _paint_preloader(self, painter, center):
        """A faint ring with an accent arc that turns and breathes in length."""
        theme = self.themes.manager
        seconds = self._spin.elapsed() / 1000.0
        ring = QtCore.QRectF(center.x() - 14, center.y() - 14, 28, 28)
        pen = QtGui.QPen(theme.color("borderStrong"), 3)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(ring)
        pen.setColor(theme.color("accent"))
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        start = -seconds * 300.0
        span = 60.0 + 120.0 * (0.5 + 0.5 * math.sin(seconds * 3.2))
        painter.drawArc(ring, int(start * 16), int(-span * 16))

    def hideEvent(self, event):
        self._spin_timer.stop()
        QtWidgets.QWidget.hideEvent(self, event)


class BrandLogo(QtWidgets.QWidget):
    """The maxpkg mark without a tile: the logo filled with a vertical accent gradient (lighter at the top) over
    a soft radial glow. Colors are read from the Manager theme at paint time, so theme changes apply at once."""

    def __init__(self, themes, size=40, glyph=30, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.themes = themes
        self.glyph = glyph
        self.setFixedSize(size, size)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)  # drags on the brand still move the window

    def paintEvent(self, _event):
        theme = self.themes.manager
        accent, light = theme.color("accent"), theme.color("accentHover")
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        center = QtCore.QPointF(self.width() / 2.0, self.height() / 2.0)
        glow = QtGui.QRadialGradient(center, self.width() / 2.0)
        for stop, alpha in ((0.0, 0.30), (0.55, 0.12), (1.0, 0.0)):
            color = QtGui.QColor(accent)
            color.setAlphaF(alpha)
            glow.setColorAt(stop, color)
        painter.fillRect(self.rect(), QtGui.QBrush(glow))
        dpr = self.devicePixelRatioF()
        mark = QtGui.QImage(icons.pixmap("maxpkg-logo", QtGui.QColor("#ffffff"), self.glyph, dpr).toImage())
        mark.setDevicePixelRatio(dpr)
        tint = QtGui.QPainter(mark)
        tint.setCompositionMode(QtGui.QPainter.CompositionMode_SourceIn)
        fill = QtGui.QLinearGradient(0, 0, 0, self.glyph)
        fill.setColorAt(0.0, light)
        fill.setColorAt(1.0, accent)
        tint.fillRect(QtCore.QRectF(0, 0, self.glyph, self.glyph), QtGui.QBrush(fill))
        tint.end()
        offset = (self.width() - self.glyph) / 2.0
        painter.drawImage(QtCore.QPointF(offset, offset), mark)
        painter.end()


class EdgeFade(QtWidgets.QWidget):
    """Soft edge of a scroll area: the window's own background drawn over the content with an alpha ramp, so the
    content fades out instead of being cut off. Top edge only once scrolled, bottom edge while more is below.

    The brush comes from the top-level window's `background_brush()` (window coordinates); without it the
    palette window color is used.
    """

    SIZE = 28

    def __init__(self, area, edge="top"):
        QtWidgets.QWidget.__init__(self, area.viewport())
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.area = area
        self.edge = edge
        bar = area.verticalScrollBar()
        bar.valueChanged.connect(self._follow)
        bar.rangeChanged.connect(lambda _low, _high: self._follow())
        area.viewport().installEventFilter(self)
        self._follow()

    def eventFilter(self, watched, event):
        if event.type() in (QtCore.QEvent.Resize, QtCore.QEvent.Show):
            self._follow()
        return False

    def _follow(self):
        viewport = self.area.viewport()
        bar = self.area.verticalScrollBar()
        needed = bar.value() > bar.minimum() if self.edge == "top" else bar.value() < bar.maximum()
        top = 0 if self.edge == "top" else viewport.height() - self.SIZE
        self.setGeometry(0, top, viewport.width(), self.SIZE)
        self.setVisible(needed)
        if needed:
            self.raise_()
            self.update()

    def paintEvent(self, _event):
        window = self.window()
        dpr = self.devicePixelRatioF()
        image = QtGui.QImage(int(self.width() * dpr), int(self.height() * dpr), QtGui.QImage.Format_ARGB32_Premultiplied)
        image.setDevicePixelRatio(dpr)
        image.fill(Qt.transparent)
        painter = QtGui.QPainter(image)
        origin = self.mapTo(window, QtCore.QPoint(0, 0))
        painter.translate(-origin.x(), -origin.y())
        brush = window.background_brush() if hasattr(window, "background_brush") else self.palette().window()
        painter.fillRect(QtCore.QRect(origin, self.size()), brush)
        painter.resetTransform()
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        ramp = QtGui.QLinearGradient(0, 0, 0, self.height())
        solid, clear = (0.0, 1.0) if self.edge == "top" else (1.0, 0.0)
        ramp.setColorAt(solid, QtGui.QColor(0, 0, 0, 255))
        ramp.setColorAt(clear, QtGui.QColor(0, 0, 0, 0))
        painter.fillRect(QtCore.QRectF(0, 0, self.width(), self.height()), QtGui.QBrush(ramp))
        painter.end()
        target = QtGui.QPainter(self)
        target.drawImage(0, 0, image)
        target.end()


class Shimmer(QtWidgets.QWidget):
    """A light diagonal band that sweeps across `target` every few seconds to draw the eye (same as TerraScoop's
    Show Layers button). Painted over the button, clipped to its rounded corners; mouse events pass through.

    With `hover_area` (a card) the band only sweeps while the pointer is over that area: the first sweep starts
    on entering, and a sweep in progress finishes after leaving instead of vanishing mid-way."""

    SWEEP_MS = 900
    PAUSE_MS = 2600
    SLANT = 0.45  # the band leans this much (horizontal per vertical)

    def __init__(self, target, radius=10, hover_area=None):
        QtWidgets.QWidget.__init__(self, target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.radius = radius
        self._hover_area = hover_area
        self._hovered = hover_area is None
        self._finishing_cycle = -1  # sweep cycle that still plays to its end after the pointer left
        self._clock = QtCore.QElapsedTimer()
        self._clock.start()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._tick)
        target.installEventFilter(self)
        if hover_area is not None:
            hover_area.installEventFilter(self)
            self._hovered = hover_area.underMouse()
        self._follow()

    def _tick(self):
        """Frames only while the band sweeps; in the pause one wake-up for the next sweep (many cards share it)."""
        self.update()
        if not self._hovered and self.phase() is None:
            self._timer.stop()  # left the card and the last sweep has finished
            return
        elapsed = self._clock.elapsed() % (self.SWEEP_MS + self.PAUSE_MS)
        self._timer.setInterval(33 if elapsed < self.SWEEP_MS else self.SWEEP_MS + self.PAUSE_MS - elapsed)

    def _follow(self):
        target = self.parentWidget()
        if target is not None and target.isVisible():
            self.setGeometry(target.rect())
            self.raise_()
            self.show()
            if self._hovered:
                self._timer.start()
        else:
            self._timer.stop()
            self.hide()

    def eventFilter(self, watched, event):
        kind = event.type()
        if watched is self._hover_area:
            if kind == QtCore.QEvent.Enter and not self._hovered:
                self._hovered = True
                if self.phase() is None:
                    self._clock.restart()  # start a sweep now, unless the previous one is still running
                self._timer.setInterval(33)
                self._timer.start()
            elif kind == QtCore.QEvent.Leave and self._hovered:
                in_sweep = self.phase() is not None
                self._hovered = False
                cycle = self._clock.elapsed() // (self.SWEEP_MS + self.PAUSE_MS)
                self._finishing_cycle = cycle if in_sweep else -1
        elif kind in (QtCore.QEvent.Show, QtCore.QEvent.Hide, QtCore.QEvent.Resize):
            self._follow()
        return False

    def phase(self):
        """0..1 while the band sweeps, None in the pause (and after the last sweep once the pointer left)."""
        total = self._clock.elapsed()
        if not self._hovered and total // (self.SWEEP_MS + self.PAUSE_MS) != self._finishing_cycle:
            return None
        elapsed = total % (self.SWEEP_MS + self.PAUSE_MS)
        return elapsed / float(self.SWEEP_MS) if elapsed < self.SWEEP_MS else None

    def paintEvent(self, _event):
        progress = self.phase()
        if progress is None:
            return
        progress = progress * progress * (3.0 - 2.0 * progress)  # ease in and out
        width, height = float(self.width()), float(self.height())
        band = max(28.0, width * 0.35)
        x = -band - self.SLANT * height + progress * (width + 2.0 * band + 2.0 * self.SLANT * height)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(QtCore.QRectF(self.rect()), self.radius, self.radius)
        painter.setClipPath(clip)
        # Across the band (perpendicular to its slant): clear, a soft light middle, clear.
        gradient = QtGui.QLinearGradient(x - band / 2.0, 0.0, x + band / 2.0, self.SLANT * band)
        for stop, alpha in ((0.0, 0), (0.42, 46), (0.5, 80), (0.58, 46), (1.0, 0)):
            gradient.setColorAt(stop, QtGui.QColor(255, 255, 255, alpha))
        painter.fillRect(self.rect(), QtGui.QBrush(gradient))
        painter.end()


class ResponsiveGrid(QtWidgets.QWidget):
    """Equal-width columns computed from the available width (min_width per item)."""

    def __init__(self, min_width=270, spacing=14, max_columns=4, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self._items = []
        self._min_width = min_width
        self._spacing = spacing
        self._max_columns = max_columns
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)

    def set_items(self, widgets):
        for widget in self._items:
            if is_valid(widget) and widget not in widgets:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._items = list(widgets)
        for widget in self._items:
            widget.setParent(self)
            widget.show()
        self._relayout(self.width())

    def items(self):
        return list(self._items)

    def columns_for(self, width):
        columns = max(1, (width + self._spacing) // (self._min_width + self._spacing))
        return int(min(self._max_columns, columns))

    def _relayout(self, width):
        if width <= 0:
            return
        columns = self.columns_for(width)
        column_width = (width - self._spacing * (columns - 1)) / float(columns)
        y = 0
        row_height = 0
        for index, widget in enumerate(self._items):
            column = index % columns
            if column == 0 and index:
                y += row_height + self._spacing
                row_height = 0
            height = widget.heightForWidth(int(column_width)) if widget.hasHeightForWidth() else widget.sizeHint().height()
            height = max(height, widget.minimumHeight())
            x = int(round(column * (column_width + self._spacing)))
            widget.setGeometry(x, y, int(column_width), height)
            row_height = max(row_height, height)
        total = y + row_height if self._items else 0
        if self.minimumHeight() != total:
            self.setMinimumHeight(total)
            self.updateGeometry()

    def item_at(self, point):
        for widget in self._items:
            if widget.geometry().contains(point):
                return widget
        return None

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._relayout(event.size().width())

    def sizeHint(self):
        return QtCore.QSize(self._min_width, self.minimumHeight())


class FlowRow(QtWidgets.QWidget):
    """Wrapping row of small widgets (collection pills, badges, action buttons)."""

    def __init__(self, spacing=6, row_spacing=8, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self._items = []
        self._spacing = spacing
        self._row_spacing = row_spacing
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Minimum)

    def add(self, widget):
        widget.setParent(self)
        widget.show()
        self._items.append(widget)
        self._relayout(self.width())

    def clear(self):
        for widget in self._items:
            widget.hide()
            widget.deleteLater()
        self._items = []
        self._relayout(self.width())

    def _arrange(self, width, apply):
        """Place items in rows for `width`; returns the total height. `apply=False` only measures."""
        x = y = row_height = 0
        width = max(width, 1)
        for widget in self._items:
            hint = widget.sizeHint()
            if x and x + hint.width() > width:
                x = 0
                y += row_height + self._row_spacing
                row_height = 0
            if apply:
                widget.setGeometry(x, y, hint.width(), hint.height())
            x += hint.width() + self._spacing
            row_height = max(row_height, hint.height())
        return y + row_height

    def _relayout(self, width):
        height = self._arrange(width, True)
        if height != self._last_height:
            self._last_height = height
            self.updateGeometry()

    _last_height = -1

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._arrange(width, False)

    def sizeHint(self):
        width = self.width() if self.width() > 1 else 400
        return QtCore.QSize(width, self._arrange(width, False))

    def minimumSizeHint(self):
        return QtCore.QSize(0, self._arrange(max(self.width(), 1), False))

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._relayout(event.size().width())

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        self._relayout(self.width())


def paint_check(painter, rect, checked, hovered, theme, radio=False, dpr=1.0):
    """The one checkbox/radio look of the Manager: accent fill with a dark Lucide check (or dot) when checked,
    a soft outline otherwise. `rect` is a QRectF square (16-22 px)."""
    painter.save()
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    accent = theme.color("accent")
    radius = rect.width() / 2.0 if radio else max(3.0, rect.width() * 0.25)
    if checked:
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("accentHover") if hovered else accent)
        painter.drawRoundedRect(rect, radius, radius)
        if radio:
            painter.setBrush(theme.color("backgroundWindow"))
            inner = rect.width() * 0.36
            painter.drawEllipse(rect.center(), inner / 2.0, inner / 2.0)
        else:
            size = int(round(rect.width() * 0.72))
            mark = icons.pixmap("check", theme.color("backgroundWindow"), size, dpr)
            painter.drawPixmap(QtCore.QPointF(rect.center().x() - size / 2.0, rect.center().y() - size / 2.0), mark)
    else:
        painter.setPen(QtGui.QPen(theme.color("textDisabled" if hovered else "borderStrong"), 1.5))
        painter.setBrush(theme.color("surfaceHover") if hovered else Qt.NoBrush)
        painter.drawRoundedRect(rect.adjusted(0.75, 0.75, -0.75, -0.75), radius, radius)
    painter.restore()


def add_choice_action(menu, text, checked, callback, themes):
    """One option of a group, drawn as our radio (ring; accent dot when chosen) in the icon column, instead of
    Qt's own check mark."""
    dpr = menu.devicePixelRatioF()
    pixmap = QtGui.QPixmap(int(16 * dpr), int(16 * dpr))
    pixmap.setDevicePixelRatio(dpr)
    pixmap.fill(Qt.transparent)
    painter = QtGui.QPainter(pixmap)
    paint_check(painter, QtCore.QRectF(1, 1, 14, 14), checked, False, themes.manager, radio=True, dpr=dpr)
    painter.end()
    action = menu.addAction(text)
    action.setIcon(QtGui.QIcon(pixmap))
    if checked:
        font = QtGui.QFont(action.font())
        font.setBold(True)
        action.setFont(font)
    action.triggered.connect(callback)
    return action


def themed_submenu(menu, text, themes, icon_name=""):
    """A submenu with the same frameless rounded look as `themed_menu` and an icon on its row."""
    submenu = themed_menu(menu)
    submenu.setTitle(text)
    if icon_name:
        submenu.menuAction().setIcon(icons.icon(icon_name, themes.color("iconPrimary"), 16, menu.devicePixelRatioF()))
    menu.addMenu(submenu)
    return submenu


def themed_menu(parent):
    menu = QtWidgets.QMenu(parent)
    menu.setObjectName("ContextMenu")
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    return menu


class _DangerRow(QtWidgets.QWidget):
    """One red menu row (QSS styles every QMenu item alike, so a destructive item paints itself).

    ICON_X, TEXT_X and HEIGHT match the ::item / ::icon paddings in manager.qss, measured against a normal item in
    3ds Max (same icon, same text): change them together.
    """

    triggered = Signal()
    ICON_X = 9
    TEXT_X = 37
    PADDING = 7  # ::item vertical padding

    def __init__(self, text, icon_name, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.text = text
        self.icon_name = icon_name
        self.themes = themes
        self.setMouseTracking(True)
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumWidth(150)
        self.setFixedHeight(max(16, self.fontMetrics().height()) + 2 * self.PADDING + 1)

    def sizeHint(self):
        return QtCore.QSize(self.TEXT_X + self.fontMetrics().horizontalAdvance(self.text) + 14, self.height())

    def event(self, event):
        if event.type() in (QtCore.QEvent.HoverEnter, QtCore.QEvent.HoverLeave):
            self.update()
        return QtWidgets.QWidget.event(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event_pos(event)):
            self.triggered.emit()

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        enabled = self.isEnabled()
        if enabled and self.underMouse():
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("dangerSurface"))
            painter.drawRoundedRect(QtCore.QRectF(self.rect()), 7, 7)  # the same shape as ::item:selected
        tint = theme.color("iconDanger" if enabled else "textDisabled")
        glyph = icons.pixmap(self.icon_name, tint, 16, self.devicePixelRatioF())
        painter.drawPixmap(QtCore.QPointF(self.ICON_X, (self.height() - 16) / 2.0), glyph)
        painter.setPen(theme.color("dangerText" if enabled else "textDisabled"))
        painter.drawText(QtCore.QRect(self.TEXT_X, 0, self.width() - self.TEXT_X, self.height()),
                         int(Qt.AlignLeft | Qt.AlignVCenter), self.text)
        painter.end()


class _MenuTitle(QtWidgets.QWidget):
    """The header of a context menu: what was clicked (a script with its icon, a divider, the toolbar) on its own
    darker band, with a bold name and a muted line under it, so it never reads as a menu item."""

    ICON = 22
    HEIGHT = 48
    LINE_GAP = 3  # px between the name and the line under it

    triggered = Signal()

    def __init__(self, text, themes, pixmap=None, icon_name="", subtitle="", link_icon="", link_tip="", parent=None):
        """`link_icon`: the header is clickable (e.g. the author's Donate page) and shows this icon on the right."""
        QtWidgets.QWidget.__init__(self, parent)
        self.text = text
        self.subtitle = subtitle
        self.themes = themes
        self.pixmap = pixmap
        self.icon_name = icon_name
        self.link_icon = link_icon
        if link_icon:
            self.setAttribute(Qt.WA_Hover)
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(link_tip)
        self.title_font = QtGui.QFont(self.font())
        self.title_font.setBold(True)
        self.title_font.setPixelSize(13)
        self.sub_font = QtGui.QFont(self.font())
        self.sub_font.setPixelSize(11)
        self.setMinimumWidth(150)
        self.setFixedHeight(self.HEIGHT)

    def sizeHint(self):
        width = max(QtGui.QFontMetrics(self.title_font).horizontalAdvance(self.text),
                    QtGui.QFontMetrics(self.sub_font).horizontalAdvance(self.subtitle))
        return QtCore.QSize(_DangerRow.TEXT_X + 4 + width + 14 + (24 if self.link_icon else 0), self.HEIGHT)

    def event(self, event):
        if self.link_icon and event.type() in (QtCore.QEvent.HoverEnter, QtCore.QEvent.HoverLeave):
            self.update()
        return QtWidgets.QWidget.event(self, event)

    def mouseReleaseEvent(self, event):
        if self.link_icon and event.button() == Qt.LeftButton and self.rect().contains(event_pos(event)):
            self.triggered.emit()

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        band = QtCore.QRectF(self.rect()).adjusted(0, 0, 0, -2)
        hovered = bool(self.link_icon) and self.underMouse()
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("surfaceHover"))  # a lighter band than the items: clearly the header
        painter.drawRoundedRect(band, 7, 7)
        # Donate / purchase links hover in the green of the Donate buttons, other links (the site) in the accent.
        support = self.link_icon in ("heart", "shopping-cart")
        if hovered:
            painter.setBrush(theme.color("successSurface" if support else "accentActive"))
            painter.setPen(QtGui.QPen(theme.color("successBorder" if support else "borderFocus"), 1))
            painter.drawRoundedRect(band.adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
            painter.setPen(Qt.NoPen)
        if self.link_icon:
            glyph = icons.pixmap(self.link_icon, theme.color("iconSuccess" if support else "iconAccent"), 14,
                                 self.devicePixelRatioF())
            painter.drawPixmap(QtCore.QPointF(band.right() - 24, (band.height() - 14) / 2.0), glyph)
        icon_rect = QtCore.QRectF(_DangerRow.ICON_X - 3, (band.height() - self.ICON) / 2.0, self.ICON, self.ICON)
        if self.pixmap is not None and not self.pixmap.isNull():
            clip = QtGui.QPainterPath()
            clip.addRoundedRect(icon_rect, 5, 5)
            painter.setClipPath(clip)
            painter.drawPixmap(icon_rect, self.pixmap, QtCore.QRectF(self.pixmap.rect()))
            painter.setClipping(False)
        elif self.icon_name:
            glyph = icons.pixmap(self.icon_name, theme.color("iconAccent"), self.ICON, self.devicePixelRatioF())
            painter.drawPixmap(icon_rect.topLeft(), glyph)
        left = _DangerRow.TEXT_X + 4
        width = self.width() - left - 10 - (24 if self.link_icon else 0)
        title_metrics = QtGui.QFontMetrics(self.title_font)
        if self.subtitle:
            # Both lines centred as one block, LINE_GAP apart (they no longer touch).
            sub_height = QtGui.QFontMetrics(self.sub_font).height()
            block = title_metrics.height() + self.LINE_GAP + sub_height
            title_top = (band.height() - block) / 2.0
            sub_top = title_top + title_metrics.height() + self.LINE_GAP
        else:
            title_top = (band.height() - title_metrics.height()) / 2.0
        painter.setFont(self.title_font)
        painter.setPen(theme.color("textStrong"))
        painter.drawText(QtCore.QRectF(left, title_top, width, title_metrics.height()), int(Qt.AlignLeft | Qt.AlignVCenter),
                         title_metrics.elidedText(self.text, Qt.ElideRight, int(width)))
        if self.subtitle:
            sub_metrics = QtGui.QFontMetrics(self.sub_font)
            painter.setFont(self.sub_font)
            painter.setPen(theme.color("textMuted"))
            painter.drawText(QtCore.QRectF(left, sub_top, width, sub_metrics.height()), int(Qt.AlignLeft | Qt.AlignVCenter),
                             sub_metrics.elidedText(self.subtitle, Qt.ElideRight, int(width)))
        painter.end()


def add_menu_title(menu, text, themes, pixmap=None, icon_name="", subtitle="", on_click=None, link_icon="heart",
                   link_tip=""):
    """The menu's header (what was clicked), then a separator. With `on_click` it is a link (the menu closes
    first): hover, a pointing hand and `link_icon` on the right; without it the header is not clickable."""
    title = _MenuTitle(text, themes, pixmap, icon_name, subtitle, link_icon if on_click else "", link_tip)
    action = QtWidgets.QWidgetAction(menu)
    action.setDefaultWidget(title)
    action.setEnabled(on_click is not None)
    if on_click is not None:
        title.triggered.connect(menu.close)
        title.triggered.connect(lambda: QtCore.QTimer.singleShot(0, on_click))
    menu.addAction(action)
    menu.addSeparator()
    return action


def add_danger_action(menu, text, callback, themes, icon_name="trash-2", enabled=True):
    """A red destructive item at the end of a themed menu; the menu closes before `callback` runs."""
    row = _DangerRow(text, icon_name, themes)
    row.setEnabled(enabled)
    action = QtWidgets.QWidgetAction(menu)
    action.setEnabled(enabled)
    action.setDefaultWidget(row)
    row.triggered.connect(menu.close)
    row.triggered.connect(lambda: QtCore.QTimer.singleShot(0, callback))  # after the menu's own loop ends
    menu.addAction(action)
    return action


def add_action(menu, text, callback, themes=None, icon_name="", token="iconPrimary"):
    action = menu.addAction(text)
    if icon_name and themes is not None:
        action.setIcon(icons.icon(icon_name, themes.color(token), 16, menu.devicePixelRatioF()))
    action.triggered.connect(callback)
    return action
