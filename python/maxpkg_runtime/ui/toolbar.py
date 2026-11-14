"""MaxPkg toolbar: a native QToolBar in the 3ds Max main window (top/bottom/left/right) or a small
frameless floating window with a dotted grip (floating horizontal/vertical).

One model, targeted updates: buttons are created/removed/reordered individually; the toolbar
itself is never destroyed while the Runtime runs. Package buttons look like the HTML toolbar
(icon, name, version/developer line, update badge on the maxpkg button) but are painted by Qt.
"""

import math

from ..domain.packages import DIVIDER, is_divider
from ..qt_compat import (QAction, QtCore, QtGui, QtWidgets, Qt, Signal, event_global_pos, exec_menu, is_valid,
                         max_main_window, screen_at)
from . import icons
from .dialogs import confirm
from .frame import apply_native_frame, native_event
from .widgets import add_action, add_choice_action, add_danger_action, add_menu_title, themed_menu, themed_submenu

AREAS = {"top": Qt.TopToolBarArea, "bottom": Qt.BottomToolBarArea, "left": Qt.LeftToolBarArea,
         "right": Qt.RightToolBarArea}
TEXT_WIDTHS = {"large": 150, "medium": 116, "small": 88}
TEXT_HEIGHTS = {"small": 30, "medium": 34, "large": 38}
# Icon-only buttons: Icon size (S/M/L) alone sets the icon; Spacing only sets the air around it and between buttons.
ICON_SIZES = {"small": 18, "medium": 22, "large": 26}
ICON_AIR = {"regular": 2, "compact": 1}  # px on each side of the icon
BRAND_WIDTH = 96
GRIP = 17
UPDATE_DOT = 6.0  # px: a package's update dot at the right end of a text button


# Toolbar look choices offered in the maxpkg button menu: (setting, title, icon, ((value, text), ...)).
LOOK_CHOICES = (
    ("toolbar_density", "Spacing", "move-horizontal", (("regular", "Regular"), ("compact", "Compact"))),
    ("toolbar_icon_size", "Icon size", "maximize", (("small", "Small"), ("medium", "Medium"), ("large", "Large"))),
    ("toolbar_button_size", "Button style", "rectangle-horizontal",
     (("icon", "Icons only"), ("small", "Narrow"), ("medium", "Medium"), ("large", "Wide"))),
    ("toolbar_subtitle_mode", "Second line", "text", (("none", "None"), ("version", "Version"), ("developer", "Developer"))),
)


class ToolbarStyle:
    """Geometry derived from settings, shared by the real toolbar and the Settings preview."""

    def __init__(self, settings, vertical=None):
        position = settings.toolbar_dock_position
        self.vertical = position in ("left", "right", "floatingvertical") if vertical is None else vertical
        self.floating = position.startswith("floating")
        self.icon_only = self.vertical or self.floating or settings.toolbar_button_size == "icon"
        self.density = settings.toolbar_density
        self.icon_size_key = settings.toolbar_icon_size
        self.button_size = settings.toolbar_button_size
        self.title_mode = settings.toolbar_title_mode
        self.subtitle_mode = settings.toolbar_subtitle_mode
        compact = self.density == "compact"
        self.gap = 2 if compact else 4
        self.padding = 2 if compact else 5
        if self.icon_only:
            # Flat Max-style button: the icon fills it but for a thin strip of air on each side.
            self.icon = ICON_SIZES[self.icon_size_key]
            self.length = self.icon + 2 * ICON_AIR[self.density]
            self.button = QtCore.QSize(self.length, self.length)
        else:
            height = TEXT_HEIGHTS[self.icon_size_key] - (4 if compact else 0)
            self.button = QtCore.QSize(TEXT_WIDTHS.get(self.button_size, 116), height)
            self.icon = {"small": 18, "medium": 20, "large": 24}[self.icon_size_key]

    def brand_size(self):
        if self.icon_only:
            return QtCore.QSize(self.button)
        return QtCore.QSize(BRAND_WIDTH, self.button.height())


class ToolbarItem:
    """What one button shows. Built from a Package so the toolbar never keeps Package objects alive."""

    __slots__ = ("guid", "title", "subtitle", "tooltip", "icon_source", "initials", "update_available")

    def __init__(self, guid, title, subtitle, tooltip, icon_source, initials, update_available):
        self.guid, self.title, self.subtitle, self.tooltip = guid, title, subtitle, tooltip
        self.icon_source, self.initials, self.update_available = icon_source, initials, update_available

    def key(self):
        return (self.title, self.subtitle, self.tooltip, self.icon_source, self.update_available)

    @classmethod
    def from_package(cls, package, settings):
        title = package.button_name if settings.toolbar_title_mode == "buttonName" and package.button_name else package.name
        subtitle = {"none": "", "developer": package.developer}.get(settings.toolbar_subtitle_mode, "v" + package.version)
        tooltip = package.display_name + " " + package.version
        if package.update_available:
            tooltip += "\nUpdate available: " + package.latest_version
        tooltip += "\nDrag to reorder"
        return cls(package.guid, title, subtitle, tooltip, package.icon_file or package.icon_url, package.initials,
                   package.update_available)


class ToolbarButton(QtWidgets.QAbstractButton):
    """Painted toolbar button; `brand=True` is the maxpkg button with the update counter."""

    alt_drag = Signal(object, object)  # button, QMouseEvent-like global QPoint (None = finished)

    def __init__(self, item, style, toolbar_theme, images, brand=False, brand_icon=None, parent=None):
        QtWidgets.QAbstractButton.__init__(self, parent)
        self.item = item
        self.style_info = style
        self.theme = toolbar_theme
        self.images = images
        self.brand = brand
        self.brand_icon = brand_icon
        self.badge_count = 0
        self.locked = False  # Toolbar lock: no drag reorder (set by ToolbarController)
        self.vanished = False  # removed: it keeps its place, unpainted, while the laser erases its picture
        self.closing = 1.0  # share of its place a removed button still takes while that place closes
        self.staged = False  # a reorder is animated over the toolbar: DragStage paints its picture instead
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self._dragging = False
        self._press_point = None  # global point of a plain press that may still become a drag
        self._cancelled = False  # the current press was dragged on a locked toolbar
        self._shake = QtCore.QVariantAnimation(self)  # the toolbar is locked: the button shakes "no"
        self._shake.setStartValue(0.0)
        self._shake.setEndValue(1.0)
        self._shake.setDuration(SHAKE_MS)
        self._shake.valueChanged.connect(lambda _value: self.update())
        if images is not None and not brand:
            images.ready.connect(self._on_image)
        self.apply(item, style, toolbar_theme)

    def apply(self, item, style, toolbar_theme):
        self.item = item
        self.style_info = style
        self.theme = toolbar_theme
        self.setFixedSize(self._size())
        self.setToolTip(item.tooltip)
        self.update()

    def set_badge(self, count):
        """Update count on the maxpkg button. It never covers the logo: the button grows to hold it beside the
        logo (the caller lays the toolbar out again)."""
        if count != self.badge_count:
            self.badge_count = count
            self.setFixedSize(self._size())
            self.update()

    def _size(self):
        style = self.style_info
        if not self.brand:
            size = QtCore.QSize(style.button)
            if self.closing < 1.0:  # along the toolbar only: the line of buttons keeps its thickness
                if style.vertical:
                    size.setHeight(int(round(size.height() * self.closing)))
                else:
                    size.setWidth(int(round(size.width() * self.closing)))
            return size
        size = style.brand_size()
        if self.badge_count:
            pill = self._badge_metrics()[2]
            if not style.icon_only:
                # logo, name, then the count close after it: wide enough for all three, never narrower than usual
                name = QtGui.QFontMetricsF(self._name_font()).horizontalAdvance("maxpkg")
                needed = 7 + 20 + 6 + name + 6 + pill.width() + 5
                size.setWidth(max(size.width(), int(math.ceil(needed))))
            elif style.vertical:
                size.setHeight(size.height() + int(math.ceil(pill.height())) + 2)
            else:
                size.setWidth(size.width() + int(math.ceil(pill.width())) + 2)
        return size

    def _name_font(self):
        font = QtGui.QFont(self.font())
        font.setPixelSize(10 if self.style_info.button.height() <= 30 else 11)
        font.setBold(True)
        return font

    def _badge_metrics(self):
        """(text, font, pill size) of the maxpkg button's update count, sized to the button."""
        style = self.style_info
        count = self.badge_count
        if style.icon_only:
            height = max(12, min(16, int(round(style.length * 0.6))))
            font_size = height - 4
        else:
            height, font_size = 16, 10
        text = str(count) if count < 100 else "99+"
        if style.icon_only and style.vertical and count > 9:
            text = "9+"  # the pill sits under the logo and may not be wider than the toolbar
        font = QtGui.QFont(self.font())
        font.setPixelSize(font_size)
        font.setBold(True)
        width = max(float(height), QtGui.QFontMetricsF(font).horizontalAdvance(text) + 8.0)
        if style.icon_only and style.vertical:
            width = min(width, float(style.length))
        return text, font, QtCore.QSizeF(width, height)

    def _on_image(self, source):
        if source == self.item.icon_source:
            self.update()

    # --- painting -----------------------------------------------------------------
    def paintEvent(self, _event):
        if self.vanished or self.staged:
            return
        theme = self.theme
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        if self._shake.state() == QtCore.QAbstractAnimation.Running:
            offset = shake_offset(float(self._shake.currentValue()))
            painter.translate(0, offset) if self.style_info.vertical else painter.translate(offset, 0)
        hovered = self.underMouse() or self.isDown() or self._dragging
        style = self.style_info
        frame = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if style.icon_only:
            # Like 3ds Max's own toolbars: flat, no border; a soft highlight only under the mouse.
            if hovered:
                painter.setPen(Qt.NoPen)
                highlight = theme.color("buttonHoverBackground")
                painter.setBrush(highlight.darker(115) if self.isDown() else highlight)
                painter.drawRoundedRect(frame, 3, 3)
        else:
            painter.setPen(QtGui.QPen(theme.color("buttonHoverBorder" if hovered else "buttonBorder"), 1))
            painter.setBrush(theme.color("buttonHoverBackground" if hovered else "buttonBackground"))
            painter.drawRoundedRect(frame, 4, 4)
        icon_rect = self._icon_rect()
        self._paint_icon(painter, icon_rect)
        if not style.icon_only:
            self._paint_text(painter, icon_rect, hovered)
        if self.brand and self.badge_count:
            self._paint_badge(painter)
        elif not self.brand and self.item.update_available:
            self._paint_update_mark(painter, icon_rect)
        painter.end()

    def _icon_rect(self):
        style = self.style_info
        size = style.icon if not self.brand or style.icon_only else 20
        if style.icon_only:
            # Centred in the square part; a maxpkg button with updates is longer and keeps its count beside it.
            length = style.length
            return QtCore.QRect((length - size) // 2, (length - size) // 2, size, size)
        return QtCore.QRect(7, (self.height() - size) // 2, size, size)

    def _paint_update_mark(self, painter, icon_rect):
        """A package with an update: a small red dot in the bottom-right corner of an icon-only button (ringed in
        the toolbar colour, so it stays apart from the icon's corner), a dot after the text on a text button."""
        painter.setBrush(self.theme.color("updateBadgeBackground"))
        if self.style_info.icon_only:
            icon = self.style_info.icon  # by icon size, so Spacing does not change the dot
            diameter = max(4.0, round((icon - 6) * 0.4))  # icon 18: 5, 22: 6, 26: 8
            ring = 1.0 if icon <= 18 else 1.5
            rect = QtCore.QRectF(self.width() - diameter - ring / 2.0, self.height() - diameter - ring / 2.0,
                                 diameter, diameter)
            painter.setPen(QtGui.QPen(self.theme.color("toolbarBackground"), ring))
            painter.drawEllipse(rect)
            return
        painter.setPen(QtGui.QPen(self.theme.color("updateBadgeBorder"), 1))
        painter.drawEllipse(QtCore.QRectF(self.width() - 5 - UPDATE_DOT, (self.height() - UPDATE_DOT) / 2.0,
                                          UPDATE_DOT, UPDATE_DOT))

    def _paint_icon(self, painter, rect):
        dpr = self.devicePixelRatioF()
        if self.brand:
            pixmap = icons.pixmap("maxpkg-logo", self.theme.color("brandIcon"), rect.width(), dpr)
            painter.drawPixmap(rect, pixmap)
            return
        source = self.images.get(self.item.icon_source) if self.images is not None else None
        if source is not None:
            scaled = source.scaled(int(rect.width() * dpr), int(rect.height() * dpr), Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            offset_x = rect.x() + (rect.width() - scaled.width() / dpr) / 2.0
            offset_y = rect.y() + (rect.height() - scaled.height() / dpr) / 2.0
            painter.drawPixmap(QtCore.QPointF(offset_x, offset_y), scaled)
            return
        painter.setPen(Qt.NoPen)
        painter.setBrush(self.theme.color("fallbackBackground"))
        painter.drawRoundedRect(QtCore.QRectF(rect), 3, 3)
        painter.setPen(self.theme.color("buttonHoverText"))
        font = QtGui.QFont(self.font())
        font.setBold(True)
        font.setPixelSize(max(8, rect.height() // 2 - 1))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignCenter, self.item.initials[:2])

    def _paint_text(self, painter, icon_rect, hovered):
        """Name (+ optional second line) centred on real glyph extents (cap height to descent), not on line
        boxes: Segoe UI line boxes carry extra leading that pushed the HTML-sized text off centre."""
        left = icon_rect.right() + 6
        width = self.width() - left - 5
        if self.brand and self.badge_count:
            width -= self._badge_metrics()[2].width() + 4  # the count sits after the name
        elif not self.brand and self.item.update_available:
            width -= UPDATE_DOT + 4
        compact = self.height() <= 30
        name_font = self._name_font()
        color = self.theme.color("buttonHoverText" if hovered else "buttonText")
        title = self.item.title if not self.brand else "maxpkg"
        subtitle = "" if self.brand else self.item.subtitle
        name_metrics = QtGui.QFontMetricsF(name_font)
        name_cap = name_metrics.capHeight()
        painter.setFont(name_font)
        painter.setPen(color)
        if not subtitle:
            baseline = (self.height() + name_cap) / 2.0
            painter.drawText(QtCore.QPointF(left, baseline), name_metrics.elidedText(title, Qt.ElideRight, width))
            return
        sub_font = QtGui.QFont(self.font())
        sub_font.setPixelSize(9)
        sub_metrics = QtGui.QFontMetricsF(sub_font)
        gap = 4.0 if not compact else 2.0
        # Visible block: name caps + name descenders ("g", "y" must not touch the second line) + gap +
        # second-line caps + part of its descenders.
        name_descent = name_metrics.descent()
        block = name_cap + name_descent + gap + sub_metrics.capHeight() + sub_metrics.descent() * 0.5
        top = (self.height() - block) / 2.0
        name_baseline = top + name_cap
        sub_baseline = name_baseline + name_descent + gap + sub_metrics.capHeight()
        painter.drawText(QtCore.QPointF(left, round(name_baseline)),
                         name_metrics.elidedText(title, Qt.ElideRight, width))
        painter.setFont(sub_font)
        painter.setPen(self.theme.color("buttonSecondaryText"))
        painter.drawText(QtCore.QPointF(left, round(sub_baseline)),
                         sub_metrics.elidedText(subtitle, Qt.ElideRight, width))

    def _paint_badge(self, painter):
        """The update count beside the logo: after the name on a text button, after (horizontal) or under
        (vertical) the logo on an icon-only one."""
        text, font, pill = self._badge_metrics()
        style = self.style_info
        if not style.icon_only:
            origin = QtCore.QPointF(self.width() - pill.width() - 5, (self.height() - pill.height()) / 2.0)
        elif style.vertical:
            origin = QtCore.QPointF((self.width() - pill.width()) / 2.0, style.length)
        else:
            origin = QtCore.QPointF(style.length, (self.height() - pill.height()) / 2.0)
        rect = QtCore.QRectF(origin, pill).adjusted(0.5, 0.5, -0.5, -0.5)
        painter.setPen(QtGui.QPen(self.theme.color("updateBadgeBorder"), 1))
        painter.setBrush(self.theme.color("updateBadgeBackground"))
        painter.drawRoundedRect(rect, rect.height() / 2.0, rect.height() / 2.0)
        painter.setFont(font)
        painter.setPen(self.theme.color("updateBadgeText"))
        painter.drawText(rect, Qt.AlignCenter, text)

    # --- drag reorder ---------------------------------------------------------------
    # A press that moves past the drag distance reorders the button, like a divider; a press that stays put is a
    # click. Alt + press still starts the drag at once (the shortcut the earlier versions taught).
    def mousePressEvent(self, event):
        self._press_point = None
        self._cancelled = False
        if not self.brand and event.button() == Qt.LeftButton:
            if event.modifiers() & Qt.AltModifier:
                if self.locked:
                    show_locked_hint(event)
                    self.shake()
                else:
                    self._start_drag()
                event.accept()
                return
            self._press_point = event_global_pos(event)
        QtWidgets.QAbstractButton.mousePressEvent(self, event)

    def shake(self):
        """The toolbar is locked: the button shakes side to side a moment, like a head saying no."""
        self._shake.stop()
        self._shake.start()

    def _start_drag(self):
        self._dragging = True
        self.setDown(False)  # the release after a drag is not a click
        self.setCursor(Qt.ClosedHandCursor)
        self.update()

    def mouseMoveEvent(self, event):
        point = self._press_point
        if not self._dragging and point is not None:
            if (event_global_pos(event) - point).manhattanLength() >= QtWidgets.QApplication.startDragDistance():
                self._press_point = None
                if self.locked:
                    show_locked_hint(event)
                    self.shake()
                    self._cancelled = True  # a drag on a locked toolbar is neither a move nor a click
                    self.setDown(False)
                else:
                    self._start_drag()
        if self._cancelled:
            return
        if self._dragging:
            self.alt_drag.emit(self, event_global_pos(event))
            return
        QtWidgets.QAbstractButton.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self._press_point = None
        if self._cancelled:
            self._cancelled = False
            self.setDown(False)
            event.accept()
            return
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.PointingHandCursor)
            self.update()
            self.alt_drag.emit(self, None)
            event.accept()
            return
        QtWidgets.QAbstractButton.mouseReleaseEvent(self, event)


LOCKED_HINT = "The toolbar is locked. Right-click it and choose Unlock Toolbar to arrange it."
SHAKE_MS = 480


def shake_offset(progress):
    """px a shaking button moves at `progress` (0..1) of its shake: three swings that die down."""
    return math.sin(progress * math.pi * 6) * 3.5 * (1.0 - progress)


def show_locked_hint(event):
    QtWidgets.QToolTip.showText(event_global_pos(event), LOCKED_HINT)


class ToolbarDivider(QtWidgets.QWidget):
    """A divider between toolbar buttons: a thin rounded line across the line of buttons. It has no click, so a
    plain drag moves it at once (buttons start a drag after the drag distance); its menu moves or removes it."""

    alt_drag = Signal(object, object)
    THICKNESS = 9

    def __init__(self, style, toolbar_theme, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.item = ToolbarItem(DIVIDER, "", "", "Divider - drag to move, right-click to remove", "", "", False)
        self.setToolTip(self.item.tooltip)
        self.setAttribute(Qt.WA_Hover)  # the normal arrow on hover; a closed hand only while it is dragged
        self._dragging = False
        self.locked = False
        self.staged = False  # see ToolbarButton.staged
        self.apply(style, toolbar_theme)

    def apply(self, style, toolbar_theme):
        self.style_info = style
        self.theme = toolbar_theme
        across = style.button.width() if style.vertical else style.button.height()
        self.setFixedSize(QtCore.QSize(across, self.THICKNESS) if style.vertical else QtCore.QSize(self.THICKNESS, across))
        self.update()

    def paintEvent(self, _event):
        """Etched like 3ds Max's own toolbar separators: a dark and a light 1 px line side by side, half the button
        height, so it reads on any toolbar color. Under the mouse or while dragged both lines brighten."""
        if self.staged:
            return
        painter = QtGui.QPainter(self)
        active = self.underMouse() or self._dragging
        background = QtGui.QColor(self.theme.color("toolbarBackground"))
        dark = QtGui.QColor(self.theme.color("toolbarBorder"))
        # The light line moves the toolbar color toward white (lighter() barely changes very dark themes).
        lift = 0.36 if active else 0.24
        light = QtGui.QColor(*(int(channel + (255 - channel) * lift) for channel in
                               (background.red(), background.green(), background.blue())))
        dark = dark.darker(150 if active else 125)
        vertical = self.style_info.vertical
        across = self.width() if vertical else self.height()
        reach = int(round(across * 0.25))  # the lines cover half of the button height
        middle_across = across // 2
        middle_along = (self.height() if vertical else self.width()) // 2 - 1
        for offset, color in ((0, dark), (1, light)):
            if vertical:
                painter.fillRect(middle_across - reach, middle_along + offset, 2 * reach, 1, color)
            else:
                painter.fillRect(middle_along + offset, middle_across - reach, 1, 2 * reach, color)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            if self.locked:
                show_locked_hint(event)
                event.accept()
                return
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            event.accept()
            return
        QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.alt_drag.emit(self, event_global_pos(event))
            return
        QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.unsetCursor()
            self.update()
            self.alt_drag.emit(self, None)
            event.accept()
            return
        QtWidgets.QWidget.mouseReleaseEvent(self, event)


class ButtonStrip(QtWidgets.QWidget):
    """Brand + package buttons in a row or column. Used inside the QToolBar and in the preview."""

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.brand = None
        self.buttons = []
        self.style_info = None

    def relayout(self):
        style = self.style_info
        widgets = [self.brand] + self.buttons if self.brand is not None else list(self.buttons)
        position = 0
        thickness = 0
        for widget in widgets:
            size = widget.size()
            if style.vertical:
                widget.move(0, position)
                position += size.height() + style.gap
                thickness = max(thickness, size.width())
            else:
                widget.move(position, 0)
                position += size.width() + style.gap
                thickness = max(thickness, size.height())
        length = max(0, position - style.gap)
        self.setFixedSize(QtCore.QSize(thickness, length) if style.vertical else QtCore.QSize(length, thickness))

    def index_at(self, global_point):
        local = self.mapFromGlobal(global_point)
        coordinate = local.y() if self.style_info.vertical else local.x()
        for index, button in enumerate(self.buttons):
            geometry = button.geometry()
            middle = geometry.center().y() if self.style_info.vertical else geometry.center().x()
            if coordinate < middle:
                return index
        return len(self.buttons)


ACCENT = "#3af1c5"  # toolbar highlights, the same accent the Manager's markers use


def _ease_in_out(value):
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def _ease_out(value):
    value = max(0.0, min(1.0, value))
    return 1.0 - (1.0 - value) ** 3


class RingBurst(QtWidgets.QWidget):
    """One accent ring that spreads out from a button and fades. It has a small see-through window of its own, a little
    bigger than the button: drawn inside the toolbar, the ring would be cut off at the toolbar's edges. The window never
    takes the mouse or the focus, follows the button if the toolbar moves it, and closes itself when the ring is gone
    (or the button is)."""

    MARGIN = 16  # px around the button: room for the ring at its widest
    FRAME_MS = 16

    def __init__(self, anchor, locate, delay=0, duration=600, spread=9.0, width=2.0):
        """`locate()` gives the button's place on screen now (a global QRectF), or None when it is gone."""
        QtWidgets.QWidget.__init__(self, anchor.window(), Qt.Tool | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint
                                   | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setFocusPolicy(Qt.NoFocus)
        self.locate = locate
        self.duration = max(1, int(duration))
        self.spread = float(spread)
        self.pen_width = float(width)
        self.progress = 0.0
        self.place = None  # the button's global QRectF the window was last fitted to
        self._clock = QtCore.QElapsedTimer()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        if delay > 0:
            self._wait = QtCore.QTimer(self)
            self._wait.setSingleShot(True)
            self._wait.timeout.connect(self._start)
            self._wait.start(int(delay))
        else:
            self._start()

    def _fit(self):
        """Fit the window around the button; False while it is not on screen."""
        try:
            place = self.locate()
        except RuntimeError:  # its widgets were deleted
            place = None
        if place is None or place.isEmpty():
            return False
        if place != self.place:
            self.place = QtCore.QRectF(place)
            self.setGeometry(place.adjusted(-self.MARGIN, -self.MARGIN, self.MARGIN, self.MARGIN).toAlignedRect())
        return True

    def _start(self):
        self._clock.start()
        self._timer.start()
        self._tick()

    def _tick(self):
        """A new button may be laid out a moment after this starts: the ring waits for it, within its own time."""
        self.progress = self._clock.elapsed() / float(self.duration)
        located = self.progress < 1.0 and self._fit()
        if not located and (self.progress >= 1.0 or self.isVisible()):
            self._timer.stop()
            self.close()
            return
        if located and not self.isVisible():
            self.show()
            self.raise_()
        self.update()

    def ring(self):
        """The ring now, in this window: (rect, corner radius, opacity)."""
        grow = 2.0 + self.spread * _ease_out(self.progress)
        button = QtCore.QRectF(self.MARGIN, self.MARGIN, self.place.width(), self.place.height())
        return button.adjusted(-grow, -grow, grow, grow), 4.0 + grow, max(0.0, 1.0 - self.progress)

    def paintEvent(self, _event):
        if self.place is None:
            return
        rect, radius, opacity = self.ring()
        color = QtGui.QColor(ACCENT)
        color.setAlphaF(opacity)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setPen(QtGui.QPen(color, self.pen_width))
        painter.setBrush(Qt.NoBrush)
        painter.drawRoundedRect(rect, radius, radius)
        painter.end()


def _global_rect(widget):
    return QtCore.QRectF(QtCore.QPointF(widget.mapToGlobal(QtCore.QPoint(0, 0))), QtCore.QSizeF(widget.size()))


class ToolbarGlow(QtWidgets.QWidget):
    """Draws the eye to the toolbar. When it appears, moves or changes its look: an accent wash that a bright band
    sweeps along once, then fades out. It lights only the stretch with buttons (not the empty rest of a docked
    toolbar) and draws no box around it: two thin lines along the toolbar mark it (top and bottom; left and right on
    a vertical toolbar), and the lines, the wash and the band all fade out toward both ends. A new button: a softer
    wash and two rings that spread out from it (RingBursts, so the toolbar's edges do not cut them off). A removed
    button:
    a picture of it fades in its still empty place while a glowing laser line crosses it from its end to its start
    (right to left; bottom to top on a vertical toolbar) and erases what it passed; the line stops where the place
    closes and stays there a moment as the mark of where the button was.
    It covers the toolbar, never takes the mouse, and waits until the toolbar is on screen (3ds Max may still be
    starting)."""

    DURATION = 1600  # ms
    PULSE = 0.55  # share of the duration one ring takes
    RING_DELAYS = (0.0, 0.3)  # shares of the duration after which each of the two rings starts
    ERASE = 0.4  # share of the duration the laser takes to erase a removed button
    LASER_GLOW = 14.0  # px: the soft light around the laser line
    LASER_CORE = "#eafff9"  # the line's hot middle
    STRONG, SOFT, NONE = 1.0, 0.55, 0.0  # strength of the wash: appeared, moved or restyled; a new button; a removed one
    PAD = 3  # px around the buttons the light reaches
    EDGE_FADE = 0.18  # share of the lit stretch, at each end, over which it fades out
    LINE_WIDTH = 2  # px: the lines along the toolbar (never thicker)

    def __init__(self, host):
        QtWidgets.QWidget.__init__(self, host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)  # only what paintEvent draws: the toolbar shows through
        self.setAutoFillBackground(False)
        self.vertical = False
        self.strength = self.STRONG
        self.rings = []  # new buttons, measured on every frame: the toolbar lays them out after this starts
        self.gaps = []  # (offset along the toolbar, start across it, length across it)
        self.ghosts = []  # (picture, QRectF in this widget) of removed buttons
        self.bursts = []  # the RingBursts this started
        self.progress = 1.0
        self._tries = 0
        self._animation = QtCore.QVariantAnimation(self)
        self._animation.setStartValue(0.0)
        self._animation.setEndValue(1.0)
        self._animation.setDuration(self.DURATION)
        self._animation.valueChanged.connect(self._step)
        self._animation.finished.connect(self.hide)
        self._retry = QtCore.QTimer(self)
        self._retry.setSingleShot(True)
        self._retry.timeout.connect(self._start)
        self.hide()

    def play(self, vertical, strength, rings=(), gaps=(), ghosts=()):
        self.vertical = vertical
        self.strength = strength
        self.rings = list(rings)
        self.gaps = list(gaps)
        self.ghosts = list(ghosts)
        self._tries = 0
        self._start()

    def _start(self):
        host = self.parentWidget()
        if host is None or not host.isVisible() or not host.window().isVisible():
            self._tries += 1
            if self._tries < 40:
                self._retry.start(250)
            return
        self._animation.stop()
        self.progress = 0.0
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        self._animation.start()
        self.bursts = [burst for burst in self.bursts if is_valid(burst)]
        for widget in self.rings:
            for delay in self.RING_DELAYS:
                self.bursts.append(RingBurst(host, self._ring_locator(widget), delay=delay * self.DURATION,
                                             duration=self.PULSE * self.DURATION, spread=10.0, width=2.5))

    def _ring_target(self, widget):
        """The widget to ring for a new button: the button, or the >> button of a crowded line it was pushed into."""
        host = self.parentWidget()
        if host is None or not is_valid(host):
            return None
        # isVisibleTo, not isVisible: 3ds Max 2022 reports a button the line pushed into >> as visible
        if is_valid(widget) and widget.isVisibleTo(host):
            return widget
        overflow = host.findChild(QtWidgets.QToolButton, "qt_toolbar_ext_button")
        return overflow if overflow is not None and overflow.isVisible() else None

    def _ring_locator(self, widget):
        def locate():
            target = self._ring_target(widget) if is_valid(self) else None
            return _global_rect(target) if target is not None and target.window().isVisible() else None
        return locate

    def lit_rect(self):
        """Where the light goes: around the maxpkg button, the buttons and dividers on screen and the >> button,
        measured now (a new button may be laid out while it plays); the whole toolbar when it has none of them."""
        host = self.parentWidget()
        whole = self.rect()
        if host is None or not is_valid(host):
            return whole
        box = QtCore.QRect()
        widgets = list(host.findChildren(ToolbarButton)) + list(host.findChildren(ToolbarDivider))
        overflow = host.findChild(QtWidgets.QToolButton, "qt_toolbar_ext_button")
        if overflow is not None and overflow.isVisible():
            widgets.append(overflow)
        for widget in widgets:
            # isVisibleTo, not isVisible: 3ds Max 2022 reports a button the line pushed into >> as visible
            if widget.isVisibleTo(host) and not widget.size().isEmpty():
                box = box.united(QtCore.QRect(widget.mapTo(host, QtCore.QPoint(0, 0)), widget.size()))
        if box.isNull():
            return whole
        return box.adjusted(-self.PAD, -self.PAD, self.PAD, self.PAD).intersected(whole)

    def _along_brush(self, rect, peak):
        """`peak` opacity of the accent along the toolbar, fading to nothing at both ends of `rect`."""
        if self.vertical:
            gradient = QtGui.QLinearGradient(0, rect.top(), 0, rect.bottom())
        else:
            gradient = QtGui.QLinearGradient(rect.left(), 0, rect.right(), 0)
        for stop, alpha in ((0.0, 0.0), (self.EDGE_FADE, peak), (1.0 - self.EDGE_FADE, peak), (1.0, 0.0)):
            color = QtGui.QColor(ACCENT)
            color.setAlphaF(max(0.0, min(1.0, alpha)))
            gradient.setColorAt(stop, color)
        return QtGui.QBrush(gradient)

    def _paint_light(self, painter, rect, progress):
        """The wash, the sweeping band and the two lines along the toolbar, within `rect`."""
        fade = 1.0 - progress
        if self.strength <= 0.0 or rect.isEmpty():
            return
        # The wash and the band share one layer that fades out toward both ends, so neither shows an edge there.
        ratio = self.devicePixelRatioF()
        layer = QtGui.QImage(max(1, int(rect.width() * ratio + 0.5)), max(1, int(rect.height() * ratio + 0.5)),
                             QtGui.QImage.Format_ARGB32_Premultiplied)
        layer.setDevicePixelRatio(ratio)
        layer.fill(Qt.transparent)
        local = QtCore.QRectF(0, 0, rect.width(), rect.height())
        light = QtGui.QPainter(layer)
        wash = QtGui.QColor(ACCENT)
        wash.setAlphaF(0.32 * self.strength * fade ** 1.6)
        light.fillRect(local, wash)
        along = local.height() if self.vertical else local.width()
        sweep = progress / 0.7
        if sweep < 1.0:
            band = max(60.0, along * 0.35)
            center = -band + (along + 2 * band) * _ease_in_out(sweep)
            if self.vertical:
                gradient = QtGui.QLinearGradient(0, center - band / 2, 0, center + band / 2)
            else:
                gradient = QtGui.QLinearGradient(center - band / 2, 0, center + band / 2, 0)
            for stop, alpha in ((0.0, 0.0), (0.5, 0.55 * self.strength * (1.0 - 0.5 * sweep)), (1.0, 0.0)):
                color = QtGui.QColor(ACCENT)
                color.setAlphaF(alpha)
                gradient.setColorAt(stop, color)
            light.fillRect(local, QtGui.QBrush(gradient))
        light.setCompositionMode(QtGui.QPainter.CompositionMode_DestinationIn)
        light.fillRect(local, self._along_brush(local, 1.0))
        light.end()
        painter.drawImage(rect.topLeft(), layer)
        half = self.LINE_WIDTH / 2.0
        if self.vertical:
            lines = ((rect.left() + half, rect.top(), rect.left() + half, rect.bottom()),
                     (rect.right() - half, rect.top(), rect.right() - half, rect.bottom()))
        else:
            lines = ((rect.left(), rect.top() + half, rect.right(), rect.top() + half),
                     (rect.left(), rect.bottom() - half, rect.right(), rect.bottom() - half))
        painter.setPen(QtGui.QPen(self._along_brush(rect, 0.9 * self.strength * fade ** 2), self.LINE_WIDTH))
        for x1, y1, x2, y2 in lines:
            painter.drawLine(QtCore.QPointF(x1, y1), QtCore.QPointF(x2, y2))

    def _step(self, value):
        self.progress = float(value)
        host = self.parentWidget()
        if host is not None and self.geometry() != host.rect():
            self.setGeometry(host.rect())
        self.update()

    def paintEvent(self, _event):
        x = self.progress
        fade = 1.0 - x
        accent = QtGui.QColor(ACCENT)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        self._paint_light(painter, QtCore.QRectF(self.lit_rect()), x)
        host = self.parentWidget()
        targets = []
        for widget in self.rings:
            target = self._ring_target(widget)
            if target is not None and target not in targets:
                targets.append(target)
        for widget in targets:
            # Only the light inside the button is drawn here; the rings that spread past it are RingBursts, each in a
            # window of its own, or the toolbar's edges would cut them off.
            ring = QtCore.QRectF(QtCore.QPointF(widget.mapTo(host, QtCore.QPoint(0, 0))), QtCore.QSizeF(widget.size()))
            glow = QtGui.QColor(accent)
            glow.setAlphaF(0.3 * fade)
            painter.setPen(Qt.NoPen)
            painter.setBrush(glow)
            painter.drawRoundedRect(ring, 4, 4)
        erase = min(1.0, x / self.ERASE)
        wiped = _ease_in_out(erase)
        for picture, place in self.ghosts:
            first, last = (place.top(), place.bottom()) if self.vertical else (place.left(), place.right())
            laser = last - (last - first) * wiped  # from the button's end to its start
            if laser > first:
                painter.save()
                kept = (QtCore.QRectF(place.left(), first, place.width(), laser - first) if self.vertical
                        else QtCore.QRectF(first, place.top(), laser - first, place.height()))
                painter.setClipRect(kept)  # what the laser passed is gone
                painter.setOpacity(1.0 - 0.7 * wiped)  # and the rest fades
                painter.drawPixmap(place, picture, QtCore.QRectF(picture.rect()))
                painter.restore()
            across = (place.left(), place.width()) if self.vertical else (place.top(), place.height())
            # It lights up as it starts and stays bright where it stops: the place closes then and the mark takes over
            # (it only fades here when the place could not close).
            after = (x - self.ERASE - 0.1) / 0.15
            self._laser(painter, laser, across[0], across[1], min(1.0, erase / 0.12) * max(0.0, 1.0 - max(0.0, after)))
        for offset, start, length in self.gaps:
            self._laser(painter, offset, start, length, fade ** 1.5)
        painter.end()

    def _laser(self, painter, offset, start, length, strength):
        """A glowing line across the toolbar at `offset` along it, `start`/`length` across it: the laser that erases a
        removed button and the mark it leaves where the button was."""
        if strength <= 0.0:
            return
        accent = QtGui.QColor(ACCENT)

        def area(along, along_size, across, across_size):
            return (QtCore.QRectF(across, along, across_size, along_size) if self.vertical
                    else QtCore.QRectF(along, across, along_size, across_size))

        half = self.LASER_GLOW / 2.0
        glow = (QtGui.QLinearGradient(0, offset - half, 0, offset + half) if self.vertical
                else QtGui.QLinearGradient(offset - half, 0, offset + half, 0))
        for stop, alpha in ((0.0, 0.0), (0.5, 0.5 * strength), (1.0, 0.0)):
            color = QtGui.QColor(accent)
            color.setAlphaF(alpha)
            glow.setColorAt(stop, color)
        painter.save()
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawRoundedRect(area(offset - half, 2 * half, start - 2, length + 4), half, half)
        core = QtGui.QColor(accent)
        core.setAlphaF(strength)
        painter.setBrush(core)
        painter.drawRoundedRect(area(offset - 1.5, 3, start, length), 1.5, 1.5)
        hot = QtGui.QColor(self.LASER_CORE)
        hot.setAlphaF(0.9 * strength)
        painter.setBrush(hot)
        painter.drawRoundedRect(area(offset - 0.5, 1, start + 2, max(0.0, length - 4)), 0.5, 0.5)
        painter.restore()


class DragStage(QtWidgets.QWidget):
    """Reordering by drag, animated over the toolbar. The dragged button lifts, grows a little and follows the cursor;
    the others step aside, so the gap shows where it will land; on release it glides in, bounces once and a ring
    spreads from it. Meanwhile the real buttons stay where they are, unpainted (`staged`): a docked QToolBar cannot
    move a QWidgetAction while its widget holds the mouse grab. They show again, in their new places, once all has
    settled. It covers the toolbar and never takes the mouse."""

    LIFT = 2.5  # px the dragged button rises off the line of buttons (a docked line has little room above it)
    GROW = 0.1  # how much bigger it gets while lifted
    FOLLOW = 0.35  # share of the way to its new place a stepping-aside button covers each frame
    LIFT_MS = 120
    LAND_MS = 180
    BOUNCE_MS = 260
    RING_MS = 600  # the ring spreading from a landed button (a RingBurst: it outlives the stage)
    FRAME_MS = 16

    def __init__(self, host):
        QtWidgets.QWidget.__init__(self, host)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)  # only what paintEvent draws: the toolbar shows through
        self.setAutoFillBackground(False)
        self.vertical = False
        self.items = []  # [widget, picture, home QRectF in this widget, offset along the toolbar now]
        self.dragged = None  # the entry of the dragged widget
        self.slots = {}  # id(widget) -> offset along the toolbar it is heading for
        self.gap = 0.0
        self.grip = None  # cursor offset into the dragged button along the toolbar, from the first move
        self.cursor_along = 0.0
        self.phase = ""  # "" | "drag" | "land"
        self.burst = None  # the RingBurst of the last landing
        self._landed_from = 0.0
        self._clock = QtCore.QElapsedTimer()
        self._timer = QtCore.QTimer(self)
        self._timer.setInterval(self.FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self.hide()

    @property
    def active(self):
        return bool(self.phase)

    def _along(self, rect):
        return rect.top() if self.vertical else rect.left()

    def _length(self, rect):
        return rect.height() if self.vertical else rect.width()

    def begin(self, widgets, dragged, vertical):
        """Take pictures of the `widgets` on screen and paint them from now on; False when `dragged` is not among them."""
        self.finish()
        host = self.parentWidget()
        if host is None:
            return False
        self.vertical = vertical
        for widget in widgets:
            if not is_valid(widget) or not widget.isVisibleTo(host):
                continue  # in the >> menu of a crowded toolbar line
            corner = widget.mapTo(host, QtCore.QPoint(0, 0))
            home = QtCore.QRectF(QtCore.QPointF(corner), QtCore.QSizeF(widget.size()))
            self.items.append([widget, widget.grab(), home, self._along(home)])
        self.dragged = next((item for item in self.items if item[0] is dragged), None)
        if self.dragged is None:
            self.items = []
            return False
        homes = sorted((item[2] for item in self.items), key=self._along)
        self.gap = max(0.0, self._along(homes[1]) - self._along(homes[0]) - self._length(homes[0])) if len(homes) > 1 else 0.0
        self.slots = {id(item[0]): item[3] for item in self.items}
        self.grip = None
        for item in self.items:
            item[0].staged = True
            item[0].update()
        self.phase = "drag"
        self._clock.start()
        self.setGeometry(host.rect())
        self.raise_()
        self.show()
        self._timer.start()
        return True

    def arrange(self, order):
        """Where each pictured widget goes when the widgets stand in `order` (which may hold widgets not pictured)."""
        pictured = {id(item[0]): item for item in self.items}
        position = min(self._along(item[2]) for item in self.items)
        slots = {}
        for widget in order:
            item = pictured.get(id(widget))
            if item is not None:
                slots[id(widget)] = position
                position += self._length(item[2]) + self.gap
        self.slots = slots

    def drag(self, global_point, order):
        local = self.mapFromGlobal(global_point)
        along = float(local.y() if self.vertical else local.x())
        if self.grip is None:
            self.grip = along - self._along(self.dragged[2])
        self.cursor_along = along
        self.arrange(order)

    def drop(self, order):
        """The mouse let go: the dragged button glides to its place in `order` (its old place when nothing moved)."""
        if not self.active:
            return
        self.arrange(order)
        self.phase = "land"
        self._landed_from = self.dragged[3]
        self._clock.restart()
        home = self.dragged[2]
        slot = self.slots.get(id(self.dragged[0]), self.dragged[3])
        place = home.translated(0, slot - home.top()) if self.vertical else home.translated(slot - home.left(), 0)
        host = self.parentWidget()
        if host is not None:
            # In a window of its own: drawn here, the ring would be cut off at the toolbar's edges.
            self.burst = RingBurst(host, self._place_locator(place), delay=self.LAND_MS, duration=self.RING_MS,
                                   spread=9.0, width=2.0)

    def _place_locator(self, place):
        def locate():
            if not is_valid(self) or not self.window().isVisible():
                return None
            return QtCore.QRectF(QtCore.QPointF(self.mapToGlobal(place.topLeft().toPoint())), place.size())
        return locate

    def finish(self):
        """All has landed: the real buttons, already in their new places, show again."""
        self._timer.stop()
        for item in self.items:
            if is_valid(item[0]):
                item[0].staged = False
                item[0].update()
        self.items = []
        self.dragged = None
        self.phase = ""
        self.hide()

    def _tick(self):
        elapsed = self._clock.elapsed()
        settled = True
        for item in self.items:
            if item is self.dragged:
                continue
            target = self.slots.get(id(item[0]), item[3])
            item[3] += (target - item[3]) * self.FOLLOW
            if abs(target - item[3]) < 0.3:
                item[3] = target
            else:
                settled = False
        if self.phase == "drag":
            if self.grip is not None:
                first = min(self.slots.values())
                last = max(self.slots.values())
                self.dragged[3] = max(first, min(last, self.cursor_along - self.grip))
        elif self.phase == "land":
            share = min(1.0, elapsed / float(self.LAND_MS))
            target = self.slots.get(id(self.dragged[0]), self.dragged[3])
            self.dragged[3] = self._landed_from + (target - self._landed_from) * (1.0 - (1.0 - share) ** 3)
            if settled and elapsed >= self.LAND_MS + self.BOUNCE_MS:
                self.finish()
                return
        self.update()

    def _placed(self, item):
        home = item[2]
        return home.translated(0, item[3] - home.top()) if self.vertical else home.translated(item[3] - home.left(), 0)

    def paintEvent(self, _event):
        if not self.items:
            return
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        for item in self.items:
            if item is not self.dragged:
                painter.drawPixmap(self._placed(item), item[1], QtCore.QRectF(item[1].rect()))
        elapsed = self._clock.elapsed()
        if self.phase == "drag":
            lift = min(1.0, elapsed / float(self.LIFT_MS))
            grow = 1.0 + self.GROW * lift
        else:
            landing = min(1.0, elapsed / float(self.LAND_MS))
            lift = 1.0 - landing
            bounce = (elapsed - self.LAND_MS) / float(self.BOUNCE_MS)
            grow = 1.0 + self.GROW * lift + (0.08 * math.sin(bounce * math.pi) if 0.0 <= bounce < 1.0 else 0.0)
        place = self._placed(self.dragged)
        across = -self.LIFT * lift
        # A soft shadow under a lifted button, offset away from the way it rises. A divider is two thin lines over the
        # toolbar: a shadow under it would read as a dark bar.
        if lift > 0.0 and not isinstance(self.dragged[0], ToolbarDivider):
            shadow = QtGui.QColor(0, 0, 0)
            shadow.setAlphaF(0.3 * lift)
            painter.setPen(Qt.NoPen)
            painter.setBrush(shadow)
            drop = 2.0 * lift
            painter.drawRoundedRect(place.translated(drop, 0) if self.vertical else place.translated(0, drop), 4, 4)
        painter.save()
        center = place.center()
        painter.translate(center.x() + (across if self.vertical else 0.0), center.y() + (0.0 if self.vertical else across))
        painter.scale(grow, grow)
        picture = self.dragged[1]
        painter.drawPixmap(QtCore.QRectF(-place.width() / 2, -place.height() / 2, place.width(), place.height()), picture,
                           QtCore.QRectF(picture.rect()))
        painter.restore()
        painter.end()


class DockedStrip:
    """Buttons of the docked QToolBar, one QWidgetAction each, so Qt's own overflow chevron
    can move individual buttons into its popup when the toolbar line is too short."""

    def __init__(self, toolbar):
        self.toolbar = toolbar
        self.brand = None
        self.buttons = []
        self.style_info = None
        self._actions = {}
        self._order = []

    def _action(self, widget):
        action = self._actions.get(id(widget))
        if action is None:
            action = QtWidgets.QWidgetAction(self.toolbar)
            action.setDefaultWidget(widget)
            self._actions[id(widget)] = action
        return action

    def forget(self, widget):
        action = self._actions.pop(id(widget), None)
        if action is not None:
            self.toolbar.removeAction(action)
            action.deleteLater()

    def relayout(self):
        wanted = ([self.brand] if self.brand is not None else []) + list(self.buttons)
        if [id(widget) for widget in wanted] == self._order:
            self.toolbar.adjustSize()
            return
        for widget in wanted:
            self.toolbar.removeAction(self._action(widget))
        for widget in wanted:
            self.toolbar.addAction(self._action(widget))
        self._order = [id(widget) for widget in wanted]
        self.toolbar.adjustSize()

    def index_at(self, global_point):
        local = self.toolbar.mapFromGlobal(global_point)
        vertical = self.toolbar.orientation() == Qt.Vertical
        coordinate = local.y() if vertical else local.x()
        for index, button in enumerate(self.buttons):
            geometry = button.geometry()
            middle = geometry.center().y() if vertical else geometry.center().x()
            if button.isVisible() and coordinate < middle:
                return index
        return len(self.buttons)


class FloatingHost(QtWidgets.QWidget):
    """Frameless tool window for the floating modes, with the dotted grip of the HTML toolbar."""

    moved = Signal(QtCore.QPoint)

    def __init__(self, parent=None):
        QtWidgets.QWidget.__init__(self, parent, Qt.Tool | Qt.FramelessWindowHint)
        self.setObjectName("MaxPkgFloatingToolbar")
        self.setWindowTitle("MaxPkg Toolbar")
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.vertical = False
        self.theme = None
        self._drag_offset = None
        self._hover_grip = False
        self.setMouseTracking(True)

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QWidget.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        if self.isWindow() and self.theme is not None:  # the Settings preview embeds it as a plain widget
            apply_native_frame(self, self.theme.color("toolbarBorder"))

    def grip_rect(self):
        return QtCore.QRect(0, 0, self.width(), GRIP) if self.vertical else QtCore.QRect(0, 0, GRIP, self.height())

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        theme = self.theme
        painter.fillRect(self.rect(), theme.color("toolbarBackground"))
        painter.setPen(theme.color("toolbarBorder"))
        painter.drawRect(self.rect().adjusted(0, 0, -1, -1))
        grip = self.grip_rect()
        if self._drag_offset is not None:
            painter.fillRect(grip.adjusted(1, 1, -1, -1), theme.color("buttonBackground"))
        elif self._hover_grip:
            painter.fillRect(grip.adjusted(1, 1, -1, -1), theme.color("buttonHoverBackground"))
        painter.setPen(Qt.NoPen)
        painter.setBrush(theme.color("buttonSecondaryText"))
        center = QtCore.QPointF(grip.center())
        dot = 2.2
        for column in (-1, 1):
            for row in (-1, 0, 1):
                dx, dy = (row * 4.5, column * 2.5) if self.vertical else (column * 2.5, row * 4.5)
                painter.drawEllipse(QtCore.QPointF(center.x() + dx, center.y() + dy), dot / 2, dot / 2)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.grip_rect().contains(event.pos()):
            self._drag_offset = event.pos()
            self.update()

    def mouseMoveEvent(self, event):
        hover = self.grip_rect().contains(event.pos())
        if hover != self._hover_grip:
            self._hover_grip = hover
            self.setCursor(Qt.SizeAllCursor if hover else Qt.ArrowCursor)
            self.update()
        if self._drag_offset is not None:
            target = event_global_pos(event) - self._drag_offset
            self.move(clamp_to_screen(target, self.size()))

    def mouseReleaseEvent(self, event):
        if self._drag_offset is not None:
            self._drag_offset = None
            self.update()
            self.moved.emit(self.pos())

    def leaveEvent(self, event):
        self._hover_grip = False
        self.update()
        QtWidgets.QWidget.leaveEvent(self, event)


def clamp_to_screen(point, size):
    area = screen_at(point + QtCore.QPoint(size.width() // 2, size.height() // 2)).availableGeometry()
    x = max(area.left(), min(point.x(), area.right() - size.width() + 1))
    y = max(area.top(), min(point.y(), area.bottom() - size.height() + 1))
    return QtCore.QPoint(x, y)


class ToolbarController(QtCore.QObject):
    """Owns the toolbar for one Runtime lifecycle. `stop()` removes it from the Max window."""

    def __init__(self, runtime, themes, images, open_manager, open_details, feedback=None, parent=None):
        """`feedback(text, kind, action)` reports what a toolbar action did (a toast)."""
        QtCore.QObject.__init__(self, parent)
        self.runtime = runtime
        self.themes = themes
        self.images = images
        self.open_manager = open_manager
        self.open_details = open_details
        self.feedback = feedback or (lambda text, kind="success", action=None: None)
        self.main_window = max_main_window()
        self.toolbar = None
        self.floating = None
        self.strip = None
        self._mode = ""
        self._area = None
        self._buttons = {}
        self._dividers = []
        self._drag_order = None
        self._glow = None
        self._stage = None  # DragStage: animates reordering by drag
        self._look = None  # what the buttons looked like at the last sync: a change lights the toolbar up
        self._departing = {}  # guid -> (removed button still holding its place, guid of the button before it)
        self._closing = []  # animations closing the places of removed buttons
        self._closing_guids = set()
        runtime.packages_changed.connect(self.sync)
        runtime.settings_changed.connect(self._on_settings)
        themes.toolbar_changed.connect(self.sync)

    # --- lifecycle ------------------------------------------------------------------
    def start(self):
        self.themes.set_toolbar(self.runtime.settings.toolbar_theme)
        self.sync()

    def stop(self):
        for signal, slot in ((self.runtime.packages_changed, self.sync), (self.runtime.settings_changed, self._on_settings),
                             (self.themes.toolbar_changed, self.sync)):
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self._destroy_hosts()

    def _destroy_hosts(self):
        if is_valid(self.toolbar):
            if is_valid(self.main_window):
                self.main_window.removeToolBar(self.toolbar)
            self.toolbar.hide()
            # Leave Max's window at once: deleteLater() waits until control returns to the outer event
            # loop, which never happens while a long script (or a restart loop) is still running.
            self.toolbar.removeEventFilter(self)
            self.toolbar.setParent(None)
            self.toolbar.deleteLater()
        if is_valid(self.floating):
            self.floating.hide()
            self.floating.deleteLater()
        for animation in self._closing:
            if is_valid(animation):
                animation.stop()
                animation.deleteLater()
        self._closing = []
        self._closing_guids = set()
        self.toolbar = self.floating = self.strip = None
        self._buttons = {}
        self._dividers = []
        self._glow = None  # a child of the host, gone with it
        self._stage = None  # the same
        self._departing = {}
        self._mode = ""

    def _on_settings(self, area):
        if area in ("toolbar", "theme", "general"):
            self.sync()

    # --- model -> view --------------------------------------------------------------
    def sync(self):
        settings = self.runtime.settings
        if not settings.toolbar_visible:
            self._destroy_hosts()
            return
        mode = settings.toolbar_dock_position
        floating = mode.startswith("floating")
        placed = True  # the toolbar appeared or moved: it lights up
        if floating and (self.floating is None or self._mode != mode):
            self._destroy_hosts()
            self._build_floating(mode)
        elif not floating and self.toolbar is None:
            self._destroy_hosts()
            self._build_docked(mode)
        elif not floating and AREAS[mode] != self._area:
            self._move_docked(mode)
        else:
            placed = False
        self._mode = mode
        self._sync_buttons(placed)

    def _style(self):
        vertical = None
        if self.toolbar is not None:
            vertical = self.toolbar.orientation() == Qt.Vertical
        return ToolbarStyle(self.runtime.settings, vertical)

    def _sync_buttons(self, placed=False):
        """`placed`: the toolbar has just appeared or moved, so it lights up as a whole; otherwise buttons that came
        or went light up."""
        style = self._style()
        theme = self.themes.toolbar
        settings = self.runtime.settings
        strip = self.strip
        strip.style_info = style
        parent = strip if isinstance(strip, QtWidgets.QWidget) else self.toolbar
        fresh = strip.brand is None  # a new host: every button is new, none of them is news
        look = (settings.toolbar_button_size, settings.toolbar_icon_size, settings.toolbar_density,
                settings.toolbar_title_mode, settings.toolbar_subtitle_mode, theme.id)
        restyled = not fresh and look != self._look
        self._look = look
        added = []
        ghosts = []
        hidden_removed = False
        previous = list(strip.buttons)
        if strip.brand is None:
            strip.brand = ToolbarButton(ToolbarItem("", "maxpkg", "", "Open MaxPkg Manager", "", "M", False), style,
                                        theme, None, brand=True, parent=parent)
            strip.brand.clicked.connect(lambda _checked=False: self.open_manager(""))
            strip.brand.setContextMenuPolicy(Qt.CustomContextMenu)
            strip.brand.customContextMenuRequested.connect(lambda _pos: self._brand_menu())
            strip.brand.show()  # the docked QWidgetAction shows it; the floating strip does not
        updates = self.runtime.update_count()
        brand_tip = ("{} package update{} available. Open MaxPkg Manager".format(updates, "" if updates == 1 else "s")
                     if updates else "Open MaxPkg Manager")
        strip.brand.apply(ToolbarItem("", "maxpkg", "", brand_tip, "", "M", False), style, theme)
        strip.brand.set_badge(updates)
        entries = self.runtime.toolbar_entries()
        wanted = [ToolbarItem.from_package(entry, settings) if entry != DIVIDER else None for entry in entries]
        wanted_guids = [item.guid for item in wanted if item is not None]
        for guid in list(self._buttons):
            if guid not in wanted_guids:
                button = self._buttons.pop(guid)
                ghost = self._picture_of(button)
                if ghost is None:  # it was in the >> menu: nothing to erase, the toolbar lights up softly instead
                    self._drop(button)
                    hidden_removed = True
                    continue
                # It stays in its place, unpainted, while the laser erases its picture; then the place closes smoothly.
                button.vanished = True
                button.setAttribute(Qt.WA_TransparentForMouseEvents)
                button.update()
                self._departing[guid] = (button, self._button_before(previous, button, wanted_guids))
                ghosts.append(ghost)
        if ghosts:
            QtCore.QTimer.singleShot(int(ToolbarGlow.DURATION * ToolbarGlow.ERASE) + 60, self._close_departed)
        # Dividers have no identity: the n-th divider widget is reused for the n-th divider entry.
        divider_count = sum(1 for item in wanted if item is None)
        while len(self._dividers) > divider_count:
            divider = self._dividers.pop()
            if isinstance(strip, DockedStrip):
                strip.forget(divider)
            divider.hide()
            divider.deleteLater()
        ordered = []
        dividers_used = 0
        for item in wanted:
            if item is None:
                if dividers_used < len(self._dividers):
                    divider = self._dividers[dividers_used]
                    divider.apply(style, theme)
                else:
                    divider = ToolbarDivider(style, theme, parent=parent)
                    divider.setContextMenuPolicy(Qt.CustomContextMenu)
                    divider.customContextMenuRequested.connect(
                        lambda _pos, widget=divider: self._divider_menu(widget))
                    divider.alt_drag.connect(self._on_alt_drag)
                    divider.show()
                    self._dividers.append(divider)
                dividers_used += 1
                ordered.append(divider)
                continue
            button = self._buttons.get(item.guid)
            if button is None:
                button = ToolbarButton(item, style, theme, self.images, parent=parent)
                button.clicked.connect(lambda _checked=False, guid=item.guid: self.runtime.run(guid))
                button.setContextMenuPolicy(Qt.CustomContextMenu)
                button.customContextMenuRequested.connect(lambda _pos, guid=item.guid: self._package_menu(guid))
                button.alt_drag.connect(self._on_alt_drag)
                button.show()
                self._buttons[item.guid] = button
                if not fresh:
                    added.append(button)
            else:
                button.apply(item, style, theme)
            ordered.append(button)
        for guid, (button, before) in self._departing.items():
            button.apply(button.item, style, theme)
            index = 0
            for position, widget in enumerate(ordered):
                if isinstance(widget, ToolbarButton) and widget.item.guid == before:
                    index = position + 1
                    break
            ordered.insert(index, button)
        for widget in ordered:
            widget.locked = settings.toolbar_locked
        strip.buttons = ordered
        strip.relayout()
        self._apply_host_theme(style)
        if placed or fresh or restyled:
            self._highlight(ToolbarGlow.STRONG)
        elif added or ghosts or hidden_removed:
            self._highlight(ToolbarGlow.SOFT if added or hidden_removed else ToolbarGlow.NONE, added, ghosts=ghosts)

    def _host(self):
        return self.toolbar if self.toolbar is not None else self.floating

    def _drop(self, button):
        if isinstance(self.strip, DockedStrip):
            self.strip.forget(button)
        button.hide()
        button.deleteLater()

    @staticmethod
    def _button_before(previous, button, wanted_guids):
        """The guid of the nearest button before `button` that stays, or None: a departing button keeps its place
        after it."""
        index = previous.index(button) if button in previous else 0
        for widget in reversed(previous[:index]):
            if isinstance(widget, ToolbarButton) and not widget.vanished and widget.item.guid in wanted_guids:
                return widget.item.guid
        return None

    def _picture_of(self, button):
        """A picture of a button about to go and its place in the host, or None when it is not on screen (isVisibleTo:
        3ds Max 2022 reports a button in the >> menu as visible)."""
        host = self._host()
        if host is None or not is_valid(button) or not button.isVisibleTo(host):
            return None
        corner = button.mapTo(host, QtCore.QPoint(0, 0))
        return button.grab(), QtCore.QRectF(QtCore.QPointF(corner), QtCore.QSizeF(button.size()))

    CLOSE_MS = 420  # a freed place closes smoothly, not at once

    def _close_departed(self):
        """The laser has erased the removed buttons: their places close smoothly and a mark stays a moment where each
        was. The mark sits where the laser stopped, at the place's start, which does not move while the place closes."""
        if not self._departing or self.strip is None:
            self._departing = {}
            return
        vertical = self.strip.style_info.vertical if self.strip.style_info else False
        host = self._host()
        gaps = []
        guids = []
        for guid, (button, _before) in self._departing.items():
            if guid in self._closing_guids:
                continue  # removed earlier: its place is already closing
            guids.append(guid)
            if host is not None and is_valid(button):
                corner = button.mapTo(host, QtCore.QPoint(0, 0))
                gaps.append((corner.y(), corner.x(), button.width()) if vertical else (corner.x(), corner.y(), button.height()))
        if gaps:
            self._highlight(ToolbarGlow.NONE, gaps=gaps)
        if not guids:
            return
        self._closing_guids.update(guids)
        animation = QtCore.QVariantAnimation(self)
        animation.setStartValue(1.0)
        animation.setEndValue(0.0)
        animation.setDuration(self.CLOSE_MS)
        animation.setEasingCurve(QtCore.QEasingCurve.InOutCubic)
        animation.valueChanged.connect(lambda value, closing=guids: self._narrow(closing, float(value)))
        animation.finished.connect(lambda closing=guids, done=animation: self._drop_departed(closing, done))
        self._closing.append(animation)
        animation.start()

    def _narrow(self, guids, share):
        """One step of closing places: the buttons take `share` of their length, the rest of the line follows."""
        if self.strip is None:
            return
        for guid in guids:
            button = self._departing.get(guid, (None, None))[0]
            if is_valid(button):
                button.closing = share
                button.setFixedSize(button._size())
        self.strip.relayout()
        if self.floating is not None and isinstance(self.strip, ButtonStrip):
            self._fit_floating(self.strip.style_info)

    def _drop_departed(self, guids, animation=None):
        """The places of these removed buttons have closed: the buttons go for good."""
        if animation in self._closing:
            self._closing.remove(animation)
            animation.deleteLater()
        for guid in guids:
            self._closing_guids.discard(guid)
            button = self._departing.pop(guid, (None, None))[0]
            if is_valid(button):
                self._drop(button)
        if self.strip is not None:
            self._sync_buttons()

    def _highlight(self, strength, rings=(), gaps=(), ghosts=()):
        host = self._host()
        if not is_valid(host):
            return
        if self._glow is None or not is_valid(self._glow):
            self._glow = ToolbarGlow(host)
        vertical = self.strip.style_info.vertical if self.strip is not None and self.strip.style_info else False
        self._glow.play(vertical, strength, rings, gaps, ghosts)

    def _apply_host_theme(self, style):
        theme = self.themes.toolbar
        if self.toolbar is not None:
            background = theme.color("toolbarBackground").name()
            border = theme.color("toolbarBorder").name()
            self.toolbar.setStyleSheet(
                "QToolBar#MaxPkgToolbar { background: %s; border: none; spacing: %dpx; padding: %dpx; }"
                "QToolBar#MaxPkgToolbar::separator { background: %s; }" % (background, style.gap, style.padding,
                                                                            border))
            self.toolbar.adjustSize()
        if self.floating is not None and isinstance(self.strip, ButtonStrip):
            self.floating.theme = theme
            self.floating.vertical = style.vertical
            self._fit_floating(style)

    def _fit_floating(self, style):
        """The floating window around its buttons (also every step while a removed button's place closes)."""
        pad = style.padding
        strip_size = self.strip.size()
        if style.vertical:
            self.strip.move(pad, GRIP + pad)
            size = QtCore.QSize(strip_size.width() + 2 * pad, GRIP + strip_size.height() + 2 * pad)
        else:
            self.strip.move(GRIP + pad, pad)
            size = QtCore.QSize(GRIP + strip_size.width() + 2 * pad, strip_size.height() + 2 * pad)
        self.floating.setFixedSize(size)
        self.floating.move(clamp_to_screen(self.floating.pos(), size))
        self.floating.update()

    # --- docked -----------------------------------------------------------------------
    def _build_docked(self, mode):
        if not is_valid(self.main_window):
            self.runtime.settings.toolbar_dock_position = "floatinghorizontal"
            self._build_floating("floatinghorizontal")
            return
        toolbar = QtWidgets.QToolBar("MaxPkg", self.main_window)
        toolbar.setObjectName("MaxPkgToolbar")
        toolbar.setMovable(True)
        toolbar.setFloatable(False)  # floating is our own window, so it can be restored exactly
        toolbar.setAllowedAreas(Qt.AllToolBarAreas)
        toolbar.setContextMenuPolicy(Qt.CustomContextMenu)
        toolbar.customContextMenuRequested.connect(lambda _pos: self._brand_menu())
        self.strip = DockedStrip(toolbar)
        toolbar.orientationChanged.connect(lambda _orientation: QtCore.QTimer.singleShot(0, self._after_dock_change))
        toolbar.installEventFilter(self)
        self._hook_overflow(toolbar)
        self.main_window.addToolBar(AREAS[mode], toolbar)
        self._area = AREAS[mode]
        self.toolbar = toolbar
        toolbar.show()

    def _move_docked(self, mode):
        self.main_window.removeToolBar(self.toolbar)
        self.main_window.addToolBar(AREAS[mode], self.toolbar)
        self.toolbar.show()
        self._area = AREAS[mode]

    def _hook_overflow(self, toolbar):
        """Qt's chevron expands the toolbar over its neighbours, but the 3ds Max main window keeps a docked
        toolbar at its line height, so nothing appeared. Unchecked, the chevron's click only collapses (Qt's own
        slot), and it opens a menu of the buttons that did not fit instead."""
        extension = toolbar.findChild(QtWidgets.QToolButton, "qt_toolbar_ext_button")
        if extension is None:
            return
        extension.setCheckable(False)
        extension.setToolTip("More buttons")
        extension.clicked.connect(lambda _checked=False: self._overflow_menu(extension))

    def _overflow_menu(self, extension):
        if self.strip is None or not is_valid(extension):
            return
        menu = themed_menu(None)
        menu.setStyleSheet(self.themes.qss())
        # isVisibleTo, not isVisible: a button the toolbar line pushed out can still report isVisible() == True
        # (3ds Max 2022 after its window got narrower) while the toolbar has hidden it.
        toolbar = self.toolbar
        if self.strip.brand is not None and not self.strip.brand.isVisibleTo(toolbar):
            add_action(menu, "Open Manager", lambda: self.open_manager(""), self.themes, "package")
        for button in self.strip.buttons:
            if not isinstance(button, ToolbarButton) or button.isVisibleTo(toolbar):
                continue
            guid = button.item.guid
            package = self.runtime.package(guid)
            name = package.display_name if package is not None else button.item.title
            action = add_action(menu, name, lambda _checked=False, guid=guid: self.runtime.run(guid), self.themes,
                                "package")
            pixmap = self.images.get(button.item.icon_source) if self.images is not None else None
            if pixmap is not None and not pixmap.isNull():
                action.setIcon(QtGui.QIcon(pixmap))
            action.setToolTip(button.item.tooltip.replace("\nDrag to reorder", ""))
        if not menu.actions():
            menu.deleteLater()
            return
        menu.setToolTipsVisible(True)
        rect = extension.rect()
        area = self.main_window.toolBarArea(self.toolbar) if is_valid(self.main_window) else Qt.TopToolBarArea
        corner = {Qt.LeftToolBarArea: rect.topRight(), Qt.BottomToolBarArea: rect.topLeft(),
                  Qt.RightToolBarArea: rect.topLeft()}.get(area, rect.bottomLeft())
        point = extension.mapToGlobal(corner)
        size = menu.sizeHint()
        if area == Qt.RightToolBarArea:
            point.setX(point.x() - size.width())
        elif area == Qt.BottomToolBarArea:
            point.setY(point.y() - size.height())
        exec_menu(menu, point)
        menu.deleteLater()

    def eventFilter(self, watched, event):
        if watched is self.toolbar and event.type() in (QtCore.QEvent.Move, QtCore.QEvent.Show):
            QtCore.QTimer.singleShot(0, self._after_dock_change)
        return False

    def _after_dock_change(self):
        """The user dragged the toolbar to another edge: remember it and refresh the button style."""
        if not is_valid(self.toolbar) or not is_valid(self.main_window):
            return
        area = self.main_window.toolBarArea(self.toolbar)
        names = {value: key for key, value in AREAS.items()}
        if area in names and area != self._area:
            self._area = area
            self.runtime.settings.toolbar_dock_position = names[area]
            self._mode = names[area]
            self.runtime.save_settings("toolbar-position")
            self._sync_buttons(placed=True)
        elif self.strip is not None and self.strip.style_info is not None:
            vertical = self.toolbar.orientation() == Qt.Vertical
            if vertical != self.strip.style_info.vertical:
                self._sync_buttons()

    # --- floating -------------------------------------------------------------------
    def _build_floating(self, mode):
        host = FloatingHost(self.main_window)
        host.theme = self.themes.toolbar
        host.vertical = mode == "floatingvertical"
        self.strip = ButtonStrip(host)
        host.moved.connect(self._remember_floating)
        host.setContextMenuPolicy(Qt.CustomContextMenu)
        host.customContextMenuRequested.connect(lambda _pos: self._brand_menu())
        self.floating = host
        self._area = None
        self._sync_floating_position(mode)
        host.show()

    def _sync_floating_position(self, mode):
        settings = self.runtime.settings
        vertical = mode == "floatingvertical"
        x = settings.floating_vertical_x if vertical else settings.floating_horizontal_x
        y = settings.floating_vertical_y if vertical else settings.floating_horizontal_y
        if x < 0 or y < 0:
            anchor = self.main_window.geometry().center() if is_valid(self.main_window) else QtCore.QPoint(400, 300)
            x, y = anchor.x() - 150, anchor.y() - 20
        self.floating.move(QtCore.QPoint(x, y))

    def _remember_floating(self, point):
        settings = self.runtime.settings
        if settings.toolbar_dock_position == "floatingvertical":
            settings.floating_vertical_x, settings.floating_vertical_y = point.x(), point.y()
        else:
            settings.floating_horizontal_x, settings.floating_horizontal_y = point.x(), point.y()
        self.runtime.save_settings("toolbar-position")

    def reset_floating_position(self):
        settings = self.runtime.settings
        if settings.toolbar_dock_position == "floatingvertical":
            settings.floating_vertical_x = settings.floating_vertical_y = -1
        else:
            settings.floating_horizontal_x = settings.floating_horizontal_y = -1
        if self.floating is not None:
            self._sync_floating_position(settings.toolbar_dock_position)
            self._apply_host_theme(self._style())
            self._remember_floating(self.floating.pos())
            self._highlight(ToolbarGlow.STRONG)

    # --- reorder ----------------------------------------------------------------------
    def _on_alt_drag(self, button, global_point):
        """The dragged button lifts and follows the cursor while the others step aside (DragStage paints it over the
        toolbar); the new order is applied on release, while it lands. Moving a docked QWidgetAction while its widget
        holds the mouse grab would cancel the drag, so the real buttons stay put until then, on both kinds of toolbar."""
        strip = self.strip
        stage = self._drag_stage()
        if global_point is None:
            order = self._order_with(button, self._drag_order)
            self._drag_order = None
            if stage is not None:
                stage.drop(order or list(strip.buttons))
            if order is not None:
                undo = self._undo_order()  # the saved order changes only now
                if self.runtime.set_toolbar_order([widget.item.guid for widget in order]):
                    self.feedback("Moved {}.".format(self._entry_name(button.item.guid)), action=undo)
            return
        if stage is not None and not stage.active:
            stage.begin(list(strip.buttons), button, strip.style_info.vertical if strip.style_info else False)
        target = strip.index_at(global_point)
        current = strip.buttons.index(button)
        self._drag_order = target if target not in (current, current + 1) else None
        if stage is not None and stage.active:
            stage.drag(global_point, self._order_with(button, self._drag_order) or list(strip.buttons))

    def _order_with(self, button, target):
        """The strip's widgets with `button` moved before index `target` (as index_at counts), or None for no move."""
        if target is None or self.strip is None or button not in self.strip.buttons:
            return None
        order = list(self.strip.buttons)
        current = order.index(button)
        order.pop(current)
        order.insert(target - 1 if target > current else target, button)
        return order

    def _drag_stage(self):
        host = self._host()
        if not is_valid(host):
            return None
        if self._stage is None or not is_valid(self._stage):
            self._stage = DragStage(host)
        return self._stage

    # --- menus ------------------------------------------------------------------------
    def _package_menu(self, guid):
        package = self.runtime.package(guid)
        if package is None:
            return
        menu = themed_menu(None)
        menu.setStyleSheet(self.themes.qss())
        byline = "v" + package.version + (" · " + package.developer if package.developer else "")
        link = None
        purchase = package.purchase_label() if package.purchase_url else ""
        if package.purchase_url:  # the header opens the author's Donate (or purchase) page
            link = lambda: self._open_purchase(guid)  # noqa: E731
        heart = purchase.lower() in ("donate", "support", "sponsor")
        add_menu_title(menu, package.display_name, self.themes,
                       pixmap=self.images.get(package.icon_file or package.icon_url), icon_name="package",
                       subtitle=byline, on_click=link, link_icon="heart" if heart else "shopping-cart",
                       link_tip="{}: opens the author's page in your browser".format(purchase or "Donate"))
        add_action(menu, "Run", lambda: self.runtime.run(guid), self.themes, "play")
        add_action(menu, "Details", lambda: self.open_details(guid), self.themes, "info")
        if package.update_available:
            add_action(menu, "Update to " + package.latest_version, lambda: self.runtime.update(guid), self.themes,
                       "download", "iconSuccess")
        menu.addSeparator()
        add_action(menu, "Browse More Scripts", lambda: self.open_manager("discover"), self.themes, "search")
        menu.addSeparator()
        unlocked = not self.runtime.settings.toolbar_locked
        index = [button.item.guid for button in self.strip.buttons].index(guid)
        move_back = add_action(menu, "Move Up" if self.strip.style_info.vertical else "Move Left",
                               lambda: self._move(guid, -1), self.themes, "arrow-left")
        move_back.setEnabled(unlocked and index > 0)
        move_next = add_action(menu, "Move Down" if self.strip.style_info.vertical else "Move Right",
                               lambda: self._move(guid, 1), self.themes, "arrow-right")
        move_next.setEnabled(unlocked and index < len(self.strip.buttons) - 1)
        add_action(menu, "Add Divider", lambda: self._add_divider(guid), self.themes,
                   "separator-vertical" if not self.strip.style_info.vertical else "separator-horizontal"
                   ).setEnabled(unlocked)
        add_action(menu, "Hide from Toolbar", lambda: self._hide_package(guid), self.themes,
                   "eye-off").setEnabled(unlocked)
        menu.addSeparator()
        self._add_lock_action(menu)
        add_action(menu, "Toolbar settings...", lambda: self.open_manager("settings:toolbar"), self.themes, "settings")
        menu.addSeparator()
        add_danger_action(menu, "Uninstall", lambda: self._uninstall(guid), self.themes)
        exec_menu(menu, QtGui.QCursor.pos())
        menu.deleteLater()

    def _uninstall(self, guid):
        """Same question and wording as the Manager's Uninstall."""
        package = self.runtime.package(guid)
        if package is None:
            return
        if confirm(max_main_window(), self.themes, "Uninstall {}?".format(package.display_name),
                   "The package files, its 3ds Max buttons and menu entries will be removed. Your scenes are not "
                   "changed.", "Uninstall", "trash-2", danger=True, icon_name="trash-2"):
            self.runtime.uninstall(guid)

    def _brand_menu(self):
        menu = self.build_brand_menu()
        exec_menu(menu, QtGui.QCursor.pos())
        menu.deleteLater()

    def build_brand_menu(self):
        """The `maxpkg` button's menu (built anew for every right click; tests look at it without opening it)."""
        menu = themed_menu(None)
        menu.setStyleSheet(self.themes.qss())
        add_menu_title(menu, "MaxPkg Toolbar", self.themes, icon_name="maxpkg-logo",
                       subtitle="Package Manager " + self.runtime.version, on_click=self._open_catalog,
                       link_icon="external-link", link_tip="Opens the maxpkg.dev catalog in your browser")
        add_action(menu, "Open Manager", lambda: self.open_manager(""), self.themes, "package")
        add_action(menu, "Check Updates", lambda: self.runtime.check_all_updates(), self.themes, "refresh-cw")
        self._add_manager_update_action(menu)
        add_action(menu, "Toolbar settings...", lambda: self.open_manager("settings:toolbar"), self.themes, "settings")
        settings = self.runtime.settings
        menu.addSeparator()  # the toolbar's look: where it sits and how its buttons appear
        dock = themed_submenu(menu, "Position", self.themes, "panel-top")
        current = settings.toolbar_dock_position
        for key, text in (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"),
                          ("floatinghorizontal", "Floating Horizontal"), ("floatingvertical", "Floating Vertical")):
            add_choice_action(dock, text, current == key, lambda _checked=False, value=key: self.set_position(value),
                              self.themes)
        # The same choices as Settings > Toolbar, in the same order.
        style = self.strip.style_info
        forced_icons = style is not None and style.icon_only and settings.toolbar_button_size != "icon"
        for attribute, title, icon_name, choices in LOOK_CHOICES:
            submenu = themed_submenu(menu, title, self.themes, icon_name)
            current = getattr(settings, attribute)
            for key, text in choices:
                add_choice_action(submenu, text, current == key,
                                  lambda _checked=False, name=attribute, value=key: self._set_look(name, value),
                                  self.themes)
            # Icon-only buttons (side and floating toolbars, or Icons only) have no width or second line.
            unused = ((attribute == "toolbar_button_size" and forced_icons) or
                      (attribute == "toolbar_subtitle_mode" and style is not None and style.icon_only))
            if unused:
                submenu.menuAction().setEnabled(False)
                submenu.menuAction().setText(title + (" (top or bottom only)" if forced_icons else " (text buttons only)"))
        menu.addSeparator()
        self._add_lock_action(menu)
        add_action(menu, "Hide toolbar", self._hide_toolbar, self.themes, "eye-off")
        return menu

    def _add_manager_update_action(self, menu):
        """Check Manager Updates: the Package Manager alone; a newer version installs itself. While a check or an
        update of the Package Manager runs, the item says so and waits."""
        state = self.runtime.self_update.state
        if state == "idle":
            add_action(menu, "Check Manager Updates", lambda: self.runtime.check_manager_update(), self.themes,
                       "circle-arrow-up")
            return
        busy = add_action(menu, "Updating Package Manager..." if state in ("downloading", "installing")
                          else "Checking Manager updates...", lambda: None, self.themes, "circle-arrow-up")
        busy.setEnabled(False)

    def _add_lock_action(self, menu):
        """Lock Toolbar / Unlock Toolbar: a locked toolbar keeps every button and divider in its place."""
        locked = self.runtime.settings.toolbar_locked
        add_action(menu, "Unlock Toolbar" if locked else "Lock Toolbar", lambda: self._set_locked(not locked),
                   self.themes, "lock-open" if locked else "lock")

    POSITION_NAMES = {"top": "the top", "bottom": "the bottom", "left": "the left side", "right": "the right side",
                      "floatinghorizontal": "a floating horizontal bar",
                      "floatingvertical": "a floating vertical bar"}

    def set_position(self, position, undo=True):
        previous = self.runtime.settings.toolbar_dock_position
        if position == previous:
            return
        self.runtime.settings.toolbar_dock_position = position
        if self.runtime.save_settings("toolbar"):
            action = ("Undo", "undo-2", lambda: self.set_position(previous, undo=False)) if undo else None
            self.feedback("The toolbar is now {}.".format(self.POSITION_NAMES.get(position, position)), action=action)

    def _set_look(self, attribute, value, undo=True):
        """A Spacing / Icon size / Button style / Second line choice from the toolbar menu; saved at once like
        Settings > Toolbar, with Undo."""
        settings = self.runtime.settings
        previous = getattr(settings, attribute)
        if value == previous:
            return
        setattr(settings, attribute, value)
        if self.runtime.save_settings("toolbar"):
            title, names = [(title, dict(choices)) for name, title, _icon, choices in LOOK_CHOICES if name == attribute][0]
            action = ("Undo", "undo-2", lambda: self._set_look(attribute, previous, undo=False)) if undo else None
            self.feedback("{}: {}.".format(title, names.get(value, value).lower()), action=action)

    def _hide_toolbar(self):
        self.runtime.settings.toolbar_visible = False
        self.runtime.save_settings("toolbar")
        self.feedback("The toolbar is hidden.\nTurn it on again in Settings > Toolbar.", "info",
                      action=("Show Toolbar", "eye", self._show_toolbar))

    def _show_toolbar(self):
        self.runtime.settings.toolbar_visible = True
        if self.runtime.save_settings("toolbar"):
            self.feedback("The toolbar is shown again.")

    def _move(self, guid, delta):
        self._move_index([button.item.guid for button in self.strip.buttons].index(guid), delta)

    def _move_index(self, index, delta):
        """Move the entry at `index` of the toolbar line (a button or a divider) by one place."""
        order = [widget.item.guid for widget in self.strip.buttons]
        target = max(0, min(len(order) - 1, index + delta))
        entry = order.pop(index)
        order.insert(target, entry)
        undo = self._undo_order()
        if self.runtime.set_toolbar_order(order):
            vertical = self.strip.style_info.vertical
            direction = ("up" if vertical else "left") if delta < 0 else ("down" if vertical else "right")
            self.feedback("Moved {} {}.".format(self._entry_name(entry), direction), action=undo)

    def _undo_order(self):
        """An Undo button that puts the saved toolbar order (buttons and dividers) back as it is right now."""
        snapshot = list(self.runtime.settings.toolbar_order)
        return ("Undo", "undo-2", lambda: self._restore_order(snapshot))

    def _restore_order(self, snapshot):
        if self.runtime.set_full_order(snapshot):
            self.feedback("Undone. The toolbar is back as it was.")

    def _entry_name(self, entry):
        """How a toolbar entry is called in messages: the script's name, or "the divider"."""
        if is_divider(entry):
            return "the divider"
        package = self.runtime.package(entry)
        return package.display_name if package is not None else "the button"

    def _open_catalog(self):
        if self.runtime.open_catalog():
            self.feedback("Opened the maxpkg.dev catalog in your browser.")

    def _open_purchase(self, guid):
        package = self.runtime.package(guid)
        if package is not None and self.runtime.open_link(package, "purchase"):
            self.feedback("Opened the {} page of {} in your browser.\nThank you for supporting the author.".format(
                package.purchase_label(), package.display_name))

    def _add_divider(self, guid):
        undo = self._undo_order()
        if self.runtime.add_toolbar_divider(guid):
            self.feedback("Added a divider after {}.\nDrag it, or right-click it to move or remove it.".format(
                self._entry_name(guid)), action=undo)

    def _remove_divider(self, ordinal):
        undo = self._undo_order()
        if self.runtime.remove_toolbar_divider(ordinal):
            self.feedback("Removed the divider.", action=undo)

    def _hide_package(self, guid):
        name = self._entry_name(guid)
        if self.runtime.set_toolbar_visible(guid, False):
            self.feedback("{} is hidden from the toolbar.\nIt stays installed; show it again any time.".format(name),
                          "info", action=("Show", "eye", lambda: self._show_package(guid)))

    def _show_package(self, guid):
        if self.runtime.set_toolbar_visible(guid, True):
            self.feedback("{} is back on the toolbar.".format(self._entry_name(guid)))

    def _set_locked(self, locked):
        if self.runtime.set_toolbar_locked(locked):
            if locked:
                self.feedback("The toolbar is locked.\nButtons and dividers keep their places.", "info",
                              action=("Unlock", "lock-open", lambda: self._set_locked(False)))
            else:
                self.feedback("The toolbar is unlocked.\nDrag its buttons to arrange them.",
                              action=("Lock Again", "lock", lambda: self._set_locked(True)))

    def _divider_menu(self, divider):
        if divider not in self.strip.buttons:
            return
        index = self.strip.buttons.index(divider)
        ordinal = sum(1 for widget in self.strip.buttons[:index] if is_divider(widget.item.guid))
        vertical = self.strip.style_info.vertical
        unlocked = not self.runtime.settings.toolbar_locked
        menu = themed_menu(None)
        menu.setStyleSheet(self.themes.qss())
        add_menu_title(menu, "Divider", self.themes,
                       icon_name="separator-horizontal" if vertical else "separator-vertical",
                       subtitle="Toolbar divider")
        move_back = add_action(menu, "Move Up" if vertical else "Move Left", lambda: self._move_index(index, -1),
                               self.themes, "arrow-left")
        move_back.setEnabled(unlocked and index > 0)
        move_next = add_action(menu, "Move Down" if vertical else "Move Right", lambda: self._move_index(index, 1),
                               self.themes, "arrow-right")
        move_next.setEnabled(unlocked and index < len(self.strip.buttons) - 1)
        menu.addSeparator()
        self._add_lock_action(menu)
        add_action(menu, "Toolbar settings...", lambda: self.open_manager("settings:toolbar"), self.themes, "settings")
        menu.addSeparator()
        add_danger_action(menu, "Remove Divider", lambda: self._remove_divider(ordinal), self.themes, "x",
                          enabled=unlocked)
        exec_menu(menu, QtGui.QCursor.pos())
        menu.deleteLater()


class ToolbarPreview(QtWidgets.QFrame):
    """Live preview in Settings > Toolbar, built from the same ToolbarButton widgets."""

    SAMPLES = (("prune", "Prune Scene", "v3.7", "3DGROUND", "PS"), ("scale", "2 Point Scale", "v1.0", "KLScripts", "2P"))

    def __init__(self, runtime, themes, parent=None):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("PreviewStage")
        self.setMinimumHeight(108)
        self.runtime = runtime
        self.themes = themes
        self.bar = FloatingHost(self)
        self.bar.setWindowFlags(Qt.Widget)
        self.bar.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.strip = ButtonStrip(self.bar)
        self.refresh()

    def refresh(self):
        settings = self.runtime.settings
        style = ToolbarStyle(settings)
        theme = self.themes.toolbar
        strip = self.strip
        strip.style_info = style
        for widget in ([strip.brand] if strip.brand else []) + strip.buttons:
            widget.hide()
            widget.deleteLater()
        strip.brand = ToolbarButton(ToolbarItem("", "maxpkg", "", "", "", "M", False), style, theme, None, brand=True,
                                    parent=strip)
        strip.brand.set_badge(0)
        strip.buttons = []
        for guid, name, version, developer, initials in self.SAMPLES:
            subtitle = {"none": "", "developer": developer}.get(settings.toolbar_subtitle_mode, version)
            item = ToolbarItem(guid, name, subtitle, "", "", initials, False)
            button = ToolbarButton(item, style, theme, None, parent=strip)
            strip.buttons.append(button)
        for widget in [strip.brand] + strip.buttons:
            widget.show()
        strip.relayout()
        pad = style.padding
        self.bar.theme = theme
        self.bar.vertical = style.vertical
        grip = GRIP if style.floating else 0
        if style.vertical:
            strip.move(pad, grip + pad)
            self.bar.setFixedSize(strip.width() + 2 * pad, grip + strip.height() + 2 * pad)
        else:
            strip.move(grip + pad, pad)
            self.bar.setFixedSize(grip + strip.width() + 2 * pad, strip.height() + 2 * pad)
        self.bar.paintEvent = self._paint_bar if not style.floating else FloatingHost.paintEvent.__get__(self.bar)
        self.setMinimumHeight(max(108, self.bar.height() + 24))
        self._place()
        self.bar.update()

    def _paint_bar(self, _event):
        painter = QtGui.QPainter(self.bar)
        theme = self.themes.toolbar
        painter.fillRect(self.bar.rect(), theme.color("toolbarBackground"))
        painter.setPen(theme.color("toolbarBorder"))
        painter.drawRect(self.bar.rect().adjusted(0, 0, -1, -1))
        painter.end()

    def _place(self):
        position = self.runtime.settings.toolbar_dock_position
        bar = self.bar
        margin = 8
        if position == "bottom":
            bar.move(margin, self.height() - bar.height() - margin)
        elif position == "right":
            bar.move(self.width() - bar.width() - margin, margin)
        elif position.startswith("floating"):
            bar.move((self.width() - bar.width()) // 2, (self.height() - bar.height()) // 2)
        else:
            bar.move(margin, margin)

    def resizeEvent(self, event):
        QtWidgets.QFrame.resizeEvent(self, event)
        self._place()


__all__ = ["ToolbarController", "ToolbarPreview", "ToolbarStyle", "QAction"]
