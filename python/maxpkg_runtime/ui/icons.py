"""Lucide SVG icons from assets/icons, recolored per theme and rendered at the device pixel ratio."""

import re

from ..qt_compat import QtCore, QtGui, QtSvg, Qt

_PLACEHOLDER = re.compile(r"\{\{[A-Za-z]+\}\}")
_sources = {}
_cache = {}
_root = None


def set_root(folder):
    global _root
    _root = folder
    _sources.clear()
    _cache.clear()


def _source(name):
    text = _sources.get(name)
    if text is None:
        path = _root / (name + ".svg")
        if not path.is_file():
            path = _root / "package.svg"
        text = path.read_text(encoding="utf-8")
        _sources[name] = text
    return text


def pixmap(name, color, size, dpr=1.0):
    """Icon `name` in `color` as a QPixmap of `size` logical pixels."""
    hex_color = color.name()
    key = (name, hex_color, color.alpha(), size, round(dpr, 2))
    cached = _cache.get(key)
    if cached is not None:
        return cached
    svg = _PLACEHOLDER.sub(hex_color, _source(name)).replace("currentColor", hex_color)
    renderer = QtSvg.QSvgRenderer(QtCore.QByteArray(svg.encode("utf-8")))
    pixels = max(1, int(round(size * dpr)))
    result = QtGui.QPixmap(pixels, pixels)
    result.fill(Qt.transparent)
    painter = QtGui.QPainter(result)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    if color.alpha() < 255:
        painter.setOpacity(color.alphaF())
    renderer.render(painter)
    painter.end()
    result.setDevicePixelRatio(dpr)
    if len(_cache) > 800:
        _cache.clear()
    _cache[key] = result
    return result


def icon(name, color, size=16, dpr=1.0):
    return QtGui.QIcon(pixmap(name, color, size, dpr))
