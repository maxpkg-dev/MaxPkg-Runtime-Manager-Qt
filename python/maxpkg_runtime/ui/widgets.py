"""Shared controls. Every dialog composes these; none restyles them locally.

Variants are Qt properties read by assets/manager.qss (``variant``, ``badge``, ``compact``...).
"""

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, disable_max_accelerators, is_valid
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
        repolish(self)

    def set_label(self, text):
        self._full_text = text
        if self.property("iconOnly") != "true":
            self.setText(text)
        self.setToolTip(text)


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
            layout.addWidget(widget, 0, Qt.AlignHCenter)
        self.setLayout(layout)


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


def themed_menu(parent):
    menu = QtWidgets.QMenu(parent)
    menu.setObjectName("ContextMenu")
    menu.setWindowFlags(menu.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
    menu.setAttribute(Qt.WA_TranslucentBackground)
    return menu


def add_action(menu, text, callback, themes=None, icon_name="", token="iconPrimary"):
    action = menu.addAction(text)
    if icon_name and themes is not None:
        action.setIcon(icons.icon(icon_name, themes.color(token), 16, menu.devicePixelRatioF()))
    action.triggered.connect(callback)
    return action
