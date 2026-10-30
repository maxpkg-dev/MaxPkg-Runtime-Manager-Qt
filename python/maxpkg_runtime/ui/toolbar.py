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
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self._dragging = False
        self._press_point = None  # global point of a plain press that may still become a drag
        self._cancelled = False  # the current press was dragged on a locked toolbar
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
            return QtCore.QSize(style.button)
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
        theme = self.theme
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
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
                else:
                    self._start_drag()
                event.accept()
                return
            self._press_point = event_global_pos(event)
        QtWidgets.QAbstractButton.mousePressEvent(self, event)

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


class InsertionLine(QtWidgets.QWidget):
    """Where a dragged button will land on the docked toolbar: a glowing accent bar across the line of buttons
    with a round dot at each end, the same marker the Manager shows between Installed cards."""

    ACCENT = "#3af1c5"
    WIDTH = 12  # the glow; the bar itself is 2.5 px in the middle
    DOT = 3.5  # radius of the end dots

    def __init__(self, parent):
        QtWidgets.QWidget.__init__(self, parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.vertical_toolbar = False  # the bar runs across the toolbar: horizontal on a vertical toolbar
        self.ring = QtGui.QColor("#444444")
        self.hide()

    def show_at(self, position, start, length, vertical_toolbar, ring):
        """`position`: the gap along the toolbar; `start`/`length`: the span of the buttons across it."""
        self.vertical_toolbar = vertical_toolbar
        self.ring = ring
        half = self.WIDTH // 2
        if vertical_toolbar:
            self.setGeometry(start, position - half, length, self.WIDTH)
        else:
            self.setGeometry(position - half, start, self.WIDTH, length)
        self.raise_()
        self.show()
        self.update()

    def paintEvent(self, _event):
        accent = QtGui.QColor(self.ACCENT)
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        if self.vertical_toolbar:  # paint as for a horizontal toolbar, rotated a quarter turn
            painter.translate(self.width(), 0)
            painter.rotate(90)
        across, along = (self.height(), self.width()) if self.vertical_toolbar else (self.width(), self.height())
        middle = across / 2.0
        glow = QtGui.QLinearGradient(0, 0, across, 0)
        for stop, alpha in ((0.0, 0.0), (0.5, 0.3), (1.0, 0.0)):
            color = QtGui.QColor(accent)
            color.setAlphaF(alpha)
            glow.setColorAt(stop, color)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QBrush(glow))
        painter.drawRoundedRect(QtCore.QRectF(0, self.DOT, across, along - 2 * self.DOT), middle, middle)
        top, bottom = self.DOT + 1.0, along - self.DOT - 1.0
        painter.setBrush(accent)
        painter.drawRoundedRect(QtCore.QRectF(middle - 1.25, top, 2.5, bottom - top), 1.25, 1.25)
        # Round ends: an accent dot with a ring of the toolbar color, so they read on buttons and gaps alike.
        painter.setPen(QtGui.QPen(self.ring, 1.25))
        for y in (top, bottom):
            painter.drawEllipse(QtCore.QPointF(middle, y), self.DOT, self.DOT)
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
        self.indicator = InsertionLine(toolbar)

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

    def show_indicator(self, index):
        visible = [button for button in self.buttons if button.isVisible()]
        if not visible:
            return
        vertical = self.toolbar.orientation() == Qt.Vertical
        if index < len(self.buttons):
            reference = self.buttons[index].geometry()
            offset = reference.top() - 1 if vertical else reference.left() - 1
        else:
            reference = visible[-1].geometry()
            offset = reference.bottom() + 2 if vertical else reference.right() + 2
        ring = QtGui.QColor(visible[0].theme.color("toolbarBackground"))
        if vertical:
            self.indicator.show_at(offset, reference.left(), reference.width(), True, ring)
        else:
            self.indicator.show_at(offset, reference.top(), reference.height(), False, ring)

    def hide_indicator(self):
        self.indicator.hide()


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
        self.toolbar = self.floating = self.strip = None
        self._buttons = {}
        self._dividers = []
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
        if floating and (self.floating is None or self._mode != mode):
            self._destroy_hosts()
            self._build_floating(mode)
        elif not floating and self.toolbar is None:
            self._destroy_hosts()
            self._build_docked(mode)
        elif not floating and AREAS[mode] != self._area:
            self._move_docked(mode)
        self._mode = mode
        self._sync_buttons()

    def _style(self):
        vertical = None
        if self.toolbar is not None:
            vertical = self.toolbar.orientation() == Qt.Vertical
        return ToolbarStyle(self.runtime.settings, vertical)

    def _sync_buttons(self):
        style = self._style()
        theme = self.themes.toolbar
        settings = self.runtime.settings
        strip = self.strip
        strip.style_info = style
        parent = strip if isinstance(strip, QtWidgets.QWidget) else self.toolbar
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
                if isinstance(strip, DockedStrip):
                    strip.forget(button)
                button.hide()
                button.deleteLater()
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
            else:
                button.apply(item, style, theme)
            ordered.append(button)
        for widget in ordered:
            widget.locked = settings.toolbar_locked
        strip.buttons = ordered
        strip.relayout()
        self._apply_host_theme(style)

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
            self._sync_buttons()
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

    # --- reorder ----------------------------------------------------------------------
    def _on_alt_drag(self, button, global_point):
        """Floating strip: buttons move live. Docked toolbar: an insertion line, applied on release
        (moving a QWidgetAction while its widget holds the mouse grab would cancel the drag)."""
        strip = self.strip
        docked = isinstance(strip, DockedStrip)
        if global_point is None:
            target = self._drag_order
            self._drag_order = None
            if docked:
                strip.hide_indicator()
                if target is not None:
                    order = list(strip.buttons)
                    current = order.index(button)
                    order.pop(current)
                    order.insert(target - 1 if target > current else target, button)
                    undo = self._undo_order()  # the saved order changes only now
                    if self.runtime.set_toolbar_order([widget.item.guid for widget in order]):
                        self.feedback("Moved {}.".format(self._entry_name(button.item.guid)), action=undo)
            elif target:
                undo = self._undo_order()
                if self.runtime.set_toolbar_order([widget.item.guid for widget in strip.buttons]):
                    self.feedback("Moved {}.".format(self._entry_name(button.item.guid)), action=undo)
            return
        target = strip.index_at(global_point)
        current = strip.buttons.index(button)
        if docked:
            moves = target not in (current, current + 1)
            self._drag_order = target if moves else None
            if moves:
                strip.show_indicator(target)
            else:
                strip.hide_indicator()
            return
        if target > current:
            target -= 1
        if target != current:
            strip.buttons.pop(current)
            strip.buttons.insert(target, button)
            strip.relayout()
            self._drag_order = True

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
        menu = themed_menu(None)
        menu.setStyleSheet(self.themes.qss())
        add_menu_title(menu, "MaxPkg Toolbar", self.themes, icon_name="maxpkg-logo",
                       subtitle="Package Manager " + self.runtime.version, on_click=self._open_catalog,
                       link_icon="external-link", link_tip="Opens the maxpkg.dev catalog in your browser")
        add_action(menu, "Open Manager", lambda: self.open_manager(""), self.themes, "package")
        add_action(menu, "Check Updates", lambda: self.runtime.check_updates(True), self.themes, "refresh-cw")
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
        exec_menu(menu, QtGui.QCursor.pos())
        menu.deleteLater()

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
