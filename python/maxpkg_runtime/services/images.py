"""Package icons and screenshots: remote URLs cached on disk, local files read directly.

Workers decode into QImage (allowed off the GUI thread). The main thread converts to QPixmap,
keeps a bounded memory cache and notifies listeners with `ready(key)`.
"""

import hashlib
import os
import time

from ..domain import storage
from ..qt_compat import QtCore, QtGui, QtSvg, Qt, Signal
from . import log, network

MAX_DISK_FILES = 400
MAX_MEMORY_ITEMS = 300
MAX_IMAGE_BYTES = 12 * 1024 * 1024
SVG_RENDER_SIZE = 256


def _decode(path):
    """QImage from a file; SVG is rendered at a fixed size so it stays sharp when scaled down.

    Call it for SVG on the main thread only: several QSvgRenderer instances rendering at the same time in
    pool threads made some icons fail at startup (seen in 3ds Max 2027 / Qt 6.8).
    """
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


def _remove_quietly(file_path):
    try:
        os.remove(file_path)
    except OSError:
        pass


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
        remote = source.lower().startswith(("http://", "https://"))
        target = self._cache_path(source) if remote else source
        if not remote or os.path.isfile(target):
            # Local icon or cached download: decode now (small files; SVG must render on the main thread).
            if remote:
                os.utime(target, None)  # most recently used survives pruning
            self._loaded(source, target, None)
            return self._memory.get(source)
        self._pending.add(source)
        self._network.download(source, target, lambda path, error: self._loaded(source, path, error),
                               MAX_IMAGE_BYTES)
        return None

    def _cache_path(self, url):
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()
        return os.path.join(self._folder, digest + _extension(url))

    def _loaded(self, source, image, error):
        self._pending.discard(source)
        if error is None and isinstance(image, str):
            image = _decode(image)  # file path: decoded on the main thread
        if error is not None or image is None:
            self._failed.add(source)
            if error is None and source.lower().startswith(("http://", "https://")):
                _remove_quietly(self._cache_path(source))  # unreadable download: fetch it again on a retry
            # A warning, not debug: a picture that never shows must be explainable from a user's log.
            log.warning("images", source + ": " + (network.describe(error) if error is not None
                                                   else "the file is not an image Qt can read"))
            return
        if len(self._memory) >= MAX_MEMORY_ITEMS:
            self._memory.pop(next(iter(self._memory)))
        self._memory[source] = QtGui.QPixmap.fromImage(image)
        self.ready.emit(source)

    def retry_failed(self):
        self._failed.clear()

    def failed(self, source):
        """True when `source` could not be downloaded or read in this session (get() does not try it again)."""
        return source in self._failed

    def retry(self, sources):
        """Let get() try these sources again, e.g. when the screenshot viewer opens."""
        self._failed.difference_update(sources)

    @property
    def folder(self):
        return self._folder

    def usage(self):
        """(files, bytes) of the disk cache."""
        return storage.folder_usage(self._folder)

    def clear_disk(self):
        """Empty the disk cache; pictures on screen stay and the rest is downloaded again when shown.
        Returns (removed, bytes freed)."""
        self._failed.clear()
        removed, freed = storage.clear_folder(self._folder)
        log.info("images", "Image cache cleared: {} files, {} bytes".format(removed, freed))
        return removed, freed

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
