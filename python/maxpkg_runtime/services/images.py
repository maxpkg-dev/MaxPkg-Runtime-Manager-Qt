"""Package icons and screenshots: remote URLs cached on disk, local files read directly.

Workers decode into QImage (allowed off the GUI thread). The main thread converts to QPixmap,
keeps a bounded memory cache and notifies listeners with `ready(key)`.
"""

import hashlib
import os
import time

from ..qt_compat import QtCore, QtGui, QtSvg, Qt, Signal
from . import log, network

MAX_DISK_FILES = 400
MAX_MEMORY_ITEMS = 300
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SVG_RENDER_SIZE = 256


def _decode(path):
    """QImage from a file; SVG is rendered at a fixed size so it stays sharp when scaled down."""
    if path.lower().endswith(".svg"):
        renderer = QtSvg.QSvgRenderer(path)
        if not renderer.isValid():
            return None
        size = renderer.defaultSize()
        if size.isEmpty():
            size = QtCore.QSize(SVG_RENDER_SIZE, SVG_RENDER_SIZE)
        size.scale(SVG_RENDER_SIZE, SVG_RENDER_SIZE, Qt.KeepAspectRatio)
        image = QtGui.QImage(size, QtGui.QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QtGui.QPainter(image)
        renderer.render(painter)
        painter.end()
        return image
    image = QtGui.QImage(path)
    return None if image.isNull() else image


def _extension(url):
    tail = url.split("?", 1)[0].lower()
    for extension in (".svg", ".png", ".jpg", ".jpeg", ".webp", ".gif"):
        if tail.endswith(extension):
            return extension
    return ".img"


class ImageService(QtCore.QObject):
    ready = Signal(str)

    def __init__(self, network_service, cache_folder, parent=None):
        QtCore.QObject.__init__(self, parent)
        self._network = network_service
        self._folder = cache_folder
        self._memory = {}
        self._pending = set()
        self._failed = set()

    def get(self, source):
        """Cached QPixmap for a URL or local path, or None (loading starts on the first miss)."""
        if not source:
            return None
        pixmap = self._memory.get(source)
        if pixmap is not None or source in self._pending or source in self._failed:
            return pixmap
        self._pending.add(source)
        remote = source.lower().startswith(("http://", "https://"))
        target = self._cache_path(source) if remote else source

        def work(cancelled):
            if remote and not os.path.isfile(target):
                network.http_download(source, target, cancelled, MAX_IMAGE_BYTES)
            if remote:
                os.utime(target, None)  # most recently used survives pruning
            return _decode(target)

        self._network.submit(work, lambda image, error: self._loaded(source, image, error))
        return None

    def _cache_path(self, url):
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(self._folder, digest + _extension(url))

    def _loaded(self, source, image, error):
        self._pending.discard(source)
        if error is not None or image is None:
            self._failed.add(source)
            if error is not None:
                log.debug("images", source + ": " + network.describe(error))
            return
        if len(self._memory) >= MAX_MEMORY_ITEMS:
            self._memory.pop(next(iter(self._memory)))
        self._memory[source] = QtGui.QPixmap.fromImage(image)
        self.ready.emit(source)

    def retry_failed(self):
        self._failed.clear()

    def prune_disk(self):
        """Keep the newest MAX_DISK_FILES files in the cache folder."""
        try:
            entries = [os.path.join(self._folder, name) for name in os.listdir(self._folder)]
        except OSError:
            return
        entries = [path for path in entries if os.path.isfile(path)]
        if len(entries) <= MAX_DISK_FILES:
            return
        entries.sort(key=lambda path: os.path.getmtime(path), reverse=True)
        for path in entries[MAX_DISK_FILES:]:
            try:
                os.remove(path)
            except OSError:
                pass

    def stop(self):
        self._memory.clear()
        self._pending.clear()


def rounded(pixmap, size, radius, dpr):
    """`pixmap` scaled into a size x size rounded square (logical pixels)."""
    pixels = max(1, int(round(size * dpr)))
    result = QtGui.QPixmap(pixels, pixels)
    result.fill(Qt.transparent)
    painter = QtGui.QPainter(result)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
    path = QtGui.QPainterPath()
    path.addRoundedRect(QtCore.QRectF(0, 0, pixels, pixels), radius * dpr, radius * dpr)
    painter.setClipPath(path)
    scaled = pixmap.scaled(pixels, pixels, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    painter.drawPixmap((pixels - scaled.width()) // 2, (pixels - scaled.height()) // 2, scaled)
    painter.end()
    result.setDevicePixelRatio(dpr)
    return result


__all__ = ["ImageService", "rounded", "time"]
