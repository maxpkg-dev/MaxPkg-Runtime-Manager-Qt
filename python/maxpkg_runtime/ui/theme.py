"""Themes: the same INI files as the MaxScript Runtime, rendered into QSS and icon colors.

Manager and toolbar themes are independent. `ThemeService` keeps every bound icon in sync and
emits `changed` so open windows restyle immediately.
"""

import configparser
import re

from ..qt_compat import QtCore, QtGui, QtWidgets, Signal, is_valid
from . import icons

DEFAULT_THEME = "default"
NATIVE_TOOLBAR_THEME = "max-native"
ICON_TEXT_GAP = 4  # extra space between a button icon and its text, on top of Qt's own gap
ICON_NUDGE = 1  # px a button icon moves down to line up with the optical center of its text
_RGBA = re.compile(r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)")
_TOKEN = re.compile(r"@([A-Za-z][A-Za-z0-9]*)")


def parse_color(text):
    """Hex or css rgba() (alpha 0..1) to QColor."""
    text = text.strip()
    match = _RGBA.fullmatch(text)
    if match:
        red, green, blue = (int(float(match.group(index))) for index in (1, 2, 3))
        alpha = float(match.group(4)) if match.group(4) is not None else 1.0
        return QtGui.QColor(red, green, blue, int(round(alpha * 255)))
    color = QtGui.QColor(text)
    if not color.isValid():
        raise ValueError("Bad color: " + text)
    return color


def css_color(color):
    """QSS color; Qt wants alpha as 0..255."""
    return "rgba({}, {}, {}, {})".format(color.red(), color.green(), color.blue(), color.alpha())


def with_alpha(color, alpha):
    result = QtGui.QColor(color)
    result.setAlphaF(alpha)
    return result


class Theme:
    def __init__(self, theme_id, name, colors):
        self.id = theme_id
        self.name = name
        self.colors = colors

    def color(self, token):
        return QtGui.QColor(self.colors[token])

    def render(self, source):
        def replace(match):
            color = self.colors.get(match.group(1))
            return css_color(color) if color is not None else match.group(0)

        return _TOKEN.sub(replace, source)

    @property
    def is_light(self):
        return self.colors["backgroundWindow"].lightness() > 150


def _parse(path, fallback):
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    raw = path.read_bytes()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8-sig")
    parser.read_string(text)
    colors = dict(fallback)
    for token, value in parser["Colors"].items():
        colors[token] = parse_color(value)
    return Theme(parser["Theme"].get("Id", path.stem), parser["Theme"].get("Name", path.stem), colors)


def load_folder(folder):
    """Default first; extra or user INI files fall back to Default for missing tokens; broken ones are skipped."""
    themes = {}
    base = _parse(folder / (DEFAULT_THEME + ".ini"), {})
    themes[base.id] = base
    for path in sorted(folder.glob("*.ini")):
        if path.stem == DEFAULT_THEME:
            continue
        try:
            theme = _parse(path, base.colors)
        except (ValueError, KeyError, UnicodeDecodeError, configparser.Error):
            continue
        themes[theme.id] = theme
    return themes


def native_toolbar_theme(base):
    """Toolbar colors taken from 3ds Max's own palette, so the toolbar matches light and dark Max UI."""
    palette = QtWidgets.QApplication.palette()
    window = palette.color(QtGui.QPalette.Window)
    button = palette.color(QtGui.QPalette.Button)
    text = palette.color(QtGui.QPalette.ButtonText)
    highlight = palette.color(QtGui.QPalette.Highlight)
    dark = window.lightness() < 128
    border = window.lighter(140) if dark else window.darker(125)
    colors = dict(base.colors)
    colors.update({
        "toolbarBackground": window, "toolbarBorder": border, "buttonBackground": button,
        "buttonBorder": border, "buttonText": text, "buttonSecondaryText": with_alpha(text, 0.68),
        "buttonHoverBackground": button.lighter(125) if dark else button.darker(108),
        "buttonHoverBorder": highlight, "buttonHoverText": text, "fallbackBackground": highlight,
        "brandIcon": text,
    })
    return Theme(NATIVE_TOOLBAR_THEME, "3ds Max (native)", colors)


class ThemeService(QtCore.QObject):
    manager_changed = Signal()
    toolbar_changed = Signal()

    def __init__(self, root, parent=None):
        QtCore.QObject.__init__(self, parent)
        icons.set_root(root / "assets" / "icons")
        self._manager_themes = load_folder(root / "assets" / "themes" / "manager")
        self._toolbar_themes = load_folder(root / "assets" / "themes" / "toolbar")
        self._toolbar_themes[NATIVE_TOOLBAR_THEME] = native_toolbar_theme(self._toolbar_themes[DEFAULT_THEME])
        self.manager = self._manager_themes[DEFAULT_THEME]
        self.toolbar = self._toolbar_themes[DEFAULT_THEME]
        self._qss_source = (root / "assets" / "manager.qss").read_text(encoding="utf-8")
        self._bindings = []

    def manager_choices(self):
        return [(theme.id, theme.name) for theme in self._manager_themes.values()]

    def toolbar_choices(self):
        return [(theme.id, theme.name) for theme in self._toolbar_themes.values()]

    def set_manager(self, theme_id):
        self.manager = self._manager_themes.get(theme_id) or self._manager_themes[DEFAULT_THEME]
        self._refresh_bindings()
        self.manager_changed.emit()
        return self.manager.id

    def set_toolbar(self, theme_id):
        if theme_id == NATIVE_TOOLBAR_THEME:
            self._toolbar_themes[NATIVE_TOOLBAR_THEME] = native_toolbar_theme(self._toolbar_themes[DEFAULT_THEME])
        self.toolbar = self._toolbar_themes.get(theme_id) or self._toolbar_themes[DEFAULT_THEME]
        self.toolbar_changed.emit()
        return self.toolbar.id

    def color(self, token):
        return self.manager.color(token)

    def qss(self):
        return self.manager.render(self._qss_source)

    def bind_icon(self, widget, name, token="iconPrimary", size=16):
        """Keep `widget` (button or label) showing `name` in the current Manager theme's `token`."""
        for index, binding in enumerate(self._bindings):
            if binding[0] is widget:
                self._bindings[index] = (widget, name, token, size)
                break
        else:
            self._bindings.append((widget, name, token, size))
        self._apply(widget, name, token, size)

    def reapply(self, widget):
        """Redraw a bound icon after the button's text or layout direction changed (the gap side moves)."""
        for binding in self._bindings:
            if binding[0] is widget:
                self._apply(*binding)
                return

    def unbind_all(self):
        self._bindings = []

    def _apply(self, widget, name, token, size):
        dpr = widget.devicePixelRatioF() if hasattr(widget, "devicePixelRatioF") else 1.0
        color = self.manager.color(token)
        if isinstance(widget, QtWidgets.QAbstractButton):
            if widget.text():
                # Qt's own icon-text gap is a fixed ~4 px: pad the icon on the text side so they never touch.
                # Next to text the glyph also sits ICON_NUDGE px lower: text looks centered below its line box.
                glyph = icons.pixmap(name, color, size, dpr)
                nudge = int(round(ICON_NUDGE * dpr))
                padded = QtGui.QPixmap(int(round((size + ICON_TEXT_GAP) * dpr)), glyph.height() + 2 * nudge)
                padded.fill(QtCore.Qt.transparent)
                painter = QtGui.QPainter(padded)
                icon_on_right = widget.layoutDirection() == QtCore.Qt.RightToLeft
                painter.drawPixmap(padded.width() - glyph.width() if icon_on_right else 0, 2 * nudge, glyph)
                painter.end()
                padded.setDevicePixelRatio(dpr)
                widget.setIcon(QtGui.QIcon(padded))
                widget.setIconSize(QtCore.QSize(size + ICON_TEXT_GAP, size + 2 * ICON_NUDGE))
            else:
                widget.setIcon(icons.icon(name, color, size, dpr))
                widget.setIconSize(QtCore.QSize(size, size))
        else:
            widget.setPixmap(icons.pixmap(name, color, size, dpr))

    def _refresh_bindings(self):
        alive = []
        for binding in self._bindings:
            if is_valid(binding[0]):
                self._apply(*binding)
                alive.append(binding)
        self._bindings = alive
