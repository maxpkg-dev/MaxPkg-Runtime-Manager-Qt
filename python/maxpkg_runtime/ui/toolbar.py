"""MaxPkg toolbar: a native QToolBar in the 3ds Max main window (top/bottom/left/right) or a small
frameless floating window with a dotted grip (floating horizontal/vertical).

One model, targeted updates: buttons are created/removed/reordered individually; the toolbar
itself is never destroyed while the Runtime runs. Package buttons look like the HTML toolbar
(icon, name, version/developer line, update badge on the maxpkg button) but are painted by Qt.
"""

from ..qt_compat import (QAction, QtCore, QtGui, QtWidgets, Qt, Signal, event_global_pos, exec_menu, is_valid,
                         max_main_window, screen_at)
from . import icons
from .dialogs import confirm
from .frame import apply_native_frame, native_event
from .widgets import add_action, add_danger_action, themed_menu

AREAS = {"top": Qt.TopToolBarArea, "bottom": Qt.BottomToolBarArea, "left": Qt.LeftToolBarArea,
         "right": Qt.RightToolBarArea}
TEXT_WIDTHS = {"large": 150, "medium": 116, "small": 88}
TEXT_HEIGHTS = {"small": 30, "medium": 34, "large": 38}
ICON_LENGTHS = {("small", "regular"): 22, ("medium", "regular"): 26, ("large", "regular"): 30,
                ("small", "compact"): 18, ("medium", "compact"): 22, ("large", "compact"): 26}
BRAND_WIDTH = 96
GRIP = 17


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
            self.length = ICON_LENGTHS[(self.icon_size_key, self.density)]
            self.button = QtCore.QSize(self.length, self.length)
            self.icon = self.length - 4  # flat Max-style button: the icon fills it, 2 px air on each side
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
        tooltip += "\nHold Alt and drag to reorder"
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
        self.setFocusPolicy(Qt.NoFocus)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self._dragging = False
        if images is not None and not brand:
            images.ready.connect(self._on_image)
        self.apply(item, style, toolbar_theme)

    def apply(self, item, style, toolbar_theme):
        self.item = item
        self.style_info = style
        self.theme = toolbar_theme
        size = style.brand_size() if self.brand else style.button
        self.setFixedSize(size)
        self.setToolTip(item.tooltip)
        self.update()

    def set_badge(self, count):
        if count != self.badge_count:
            self.badge_count = count
            self.update()

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
            self._paint_badge(painter, str(self.badge_count))
        elif not self.brand and self.item.update_available:
            painter.setPen(QtGui.QPen(theme.color("updateBadgeBorder"), 1))
            painter.setBrush(theme.color("updateBadgeBackground"))
            painter.drawEllipse(QtCore.QRectF(self.width() - 9, 2, 7, 7))
        painter.end()

    def _icon_rect(self):
        style = self.style_info
        size = style.icon if not self.brand or style.icon_only else 20
        if style.icon_only:
            return QtCore.QRect((self.width() - size) // 2, (self.height() - size) // 2, size, size)
        return QtCore.QRect(7, (self.height() - size) // 2, size, size)

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
        compact = self.height() <= 30
        name_font = QtGui.QFont(self.font())
        name_font.setPixelSize(10 if compact else 11)
        name_font.setBold(True)
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

    def _paint_badge(self, painter, text):
        font = QtGui.QFont(self.font())
        font.setPixelSize(10)
        font.setBold(True)
        metrics = QtGui.QFontMetrics(font)
        width = max(16, metrics.horizontalAdvance(text) + 8)
        rect = QtCore.QRectF(self.width() - width - 1, 1, width, 16)
        painter.setPen(QtGui.QPen(self.theme.color("updateBadgeBorder"), 1))
        painter.setBrush(self.theme.color("updateBadgeBackground"))
        painter.drawRoundedRect(rect, 8, 8)
        painter.setFont(font)
        painter.setPen(self.theme.color("updateBadgeText"))
        painter.drawText(rect, Qt.AlignCenter, text)

    # --- Alt + drag reorder -------------------------------------------------------
    def mousePressEvent(self, event):
        if not self.brand and event.button() == Qt.LeftButton and event.modifiers() & Qt.AltModifier:
            self._dragging = True
            self.setCursor(Qt.ClosedHandCursor)
            self.update()
            event.accept()
            return
        QtWidgets.QAbstractButton.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if self._dragging:
            self.alt_drag.emit(self, event_global_pos(event))
            return
        QtWidgets.QAbstractButton.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self.setCursor(Qt.PointingHandCursor)
            self.update()
            self.alt_drag.emit(self, None)
            event.accept()
            return
        QtWidgets.QAbstractButton.mouseReleaseEvent(self, event)


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
        self.indicator = QtWidgets.QFrame(toolbar)
        self.indicator.setStyleSheet("background: #3af1c5;")
        self.indicator.hide()

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
            offset = reference.top() - 2 if vertical else reference.left() - 2
        else:
            reference = visible[-1].geometry()
            offset = reference.bottom() + 1 if vertical else reference.right() + 1
        if vertical:
            self.indicator.setGeometry(reference.left(), offset, reference.width(), 2)
        else:
            self.indicator.setGeometry(offset, reference.top(), 2, reference.height())
        self.indicator.raise_()
        self.indicator.show()

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

    def __init__(self, runtime, themes, images, open_manager, open_details, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.runtime = runtime
        self.themes = themes
        self.images = images
        self.open_manager = open_manager
        self.open_details = open_details
        self.main_window = max_main_window()
        self.toolbar = None
        self.floating = None
        self.strip = None
        self._mode = ""
        self._area = None
        self._buttons = {}
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
        brand_tip = "{} package update(s) available. Open MaxPkg Manager".format(updates) if updates else "Open MaxPkg Manager"
        strip.brand.apply(ToolbarItem("", "maxpkg", "", brand_tip, "", "M", False), style, theme)
        strip.brand.set_badge(updates)
        wanted = [ToolbarItem.from_package(package, settings) for package in self.runtime.toolbar_packages()]
        wanted_guids = [item.guid for item in wanted]
        for guid in list(self._buttons):
            if guid not in wanted_guids:
                button = self._buttons.pop(guid)
                if isinstance(strip, DockedStrip):
                    strip.forget(button)
                button.hide()
                button.deleteLater()
        ordered = []
        for item in wanted:
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
        self.main_window.addToolBar(AREAS[mode], toolbar)
        self._area = AREAS[mode]
        self.toolbar = toolbar
        toolbar.show()

    def _move_docked(self, mode):
        self.main_window.removeToolBar(self.toolbar)
        self.main_window.addToolBar(AREAS[mode], self.toolbar)
        self.toolbar.show()
        self._area = AREAS[mode]

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
                    self.runtime.set_toolbar_order([widget.item.guid for widget in order])
            elif target:
                self.runtime.set_toolbar_order([widget.item.guid for widget in strip.buttons])
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
        add_action(menu, "Run", lambda: self.runtime.run(guid), self.themes, "play")
        add_action(menu, "Details", lambda: self.open_details(guid), self.themes, "info")
        if package.update_available:
            add_action(menu, "Update to " + package.latest_version, lambda: self.runtime.update(guid), self.themes,
                       "download", "iconSuccess")
        menu.addSeparator()
        index = [button.item.guid for button in self.strip.buttons].index(guid)
        move_back = add_action(menu, "Move Up" if self.strip.style_info.vertical else "Move Left",
                               lambda: self._move(guid, -1), self.themes, "arrow-left")
        move_back.setEnabled(index > 0)
        move_next = add_action(menu, "Move Down" if self.strip.style_info.vertical else "Move Right",
                               lambda: self._move(guid, 1), self.themes, "arrow-right")
        move_next.setEnabled(index < len(self.strip.buttons) - 1)
        add_action(menu, "Hide from Toolbar", lambda: self.runtime.set_toolbar_visible(guid, False), self.themes,
                   "eye-off")
        menu.addSeparator()
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
        add_action(menu, "Open Manager", lambda: self.open_manager(""), self.themes, "package")
        add_action(menu, "Check Updates", lambda: self.runtime.check_updates(True), self.themes, "refresh-cw")
        add_action(menu, "Toolbar settings...", lambda: self.open_manager("settings:toolbar"), self.themes, "settings")
        dock = menu.addMenu("Position")
        dock.setObjectName("ContextMenu")
        for key, text in (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"),
                          ("floatinghorizontal", "Floating Horizontal"), ("floatingvertical", "Floating Vertical")):
            action = add_action(dock, text, lambda _checked=False, value=key: self.set_position(value))
            action.setCheckable(True)
            action.setChecked(self.runtime.settings.toolbar_dock_position == key)
        menu.addSeparator()
        add_action(menu, "Hide toolbar", self._hide_toolbar, self.themes, "eye-off")
        exec_menu(menu, QtGui.QCursor.pos())
        menu.deleteLater()

    def set_position(self, position):
        self.runtime.settings.toolbar_dock_position = position
        self.runtime.save_settings("toolbar")

    def _hide_toolbar(self):
        self.runtime.settings.toolbar_visible = False
        self.runtime.save_settings("toolbar")
        self.runtime.notify.emit("The toolbar is hidden. Turn it on again in Settings > Toolbar.", "info")

    def _move(self, guid, delta):
        order = [button.item.guid for button in self.strip.buttons]
        index = order.index(guid)
        target = max(0, min(len(order) - 1, index + delta))
        order.insert(target, order.pop(index))
        self.runtime.set_toolbar_order(order)


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
