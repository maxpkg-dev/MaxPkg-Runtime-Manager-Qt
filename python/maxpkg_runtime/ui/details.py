"""Package Details page: hero, purchase notice, Description/Screenshots/Videos/Changelog tabs, information table."""

import math
import re
from html import unescape

from ..domain import markdown
from ..domain.packages import Screenshot, changelog_versions, compact_number, supported_versions
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, event_pos
from ..services.images import rounded
from . import icons
from .cards import PackageIcon
from .pages import ScrollPage
from .widgets import (Badge, Button, CopyButton, DragScroll, FlowRow, IconLabel, Shimmer, SlideView, hbox, label,
                      vbox)

SINGLE_COLUMN = 900

# (title, text, free) for the purchase notice. Free packages: free for everyone, and support keeps it going.
PURCHASE_COPY = {
    "donate": ("Free for everyone", "Every feature is free. Your donation keeps the author working on it: without "
                                    "support from users like you, new updates and tools can't happen.", True),
    "support": ("Free for everyone", "Every feature is free. Your support keeps the author working on it: without "
                                     "help from users like you, new updates and tools can't happen.", True),
    "sponsor": ("Free for everyone", "Every feature is free. Sponsoring keeps the author working on it: without "
                                     "help from users like you, new updates and tools can't happen.", True),
    "purchase": ("Sold by the author", "The button opens the author's page, where you can see the price and details "
                                       "before you decide.", False),
    "buy": ("Sold by the author", "The button opens the author's page, where you can see the price and details "
                                  "before you decide.", False),
}
LICENSE_COPY = ("License from the author", "The button opens the author's page with the license options and terms.",
                False)
DEFAULT_PURCHASE_COPY = ("Support the author", "Your support keeps new updates and tools coming.", True)
CHANGE_TYPES = ("added", "fixed", "improved", "changed", "removed")


def section(title):
    frame = QtWidgets.QFrame()
    frame.setObjectName("DetailsSection")
    layout = vbox(spacing=8, margins=(12, 12, 12, 12))
    layout.addWidget(label(title.upper(), "SectionTitle"))
    frame.setLayout(layout)
    return frame, layout


class AutoHeightBrowser(QtWidgets.QTextBrowser):
    """Rich text that grows with its content (the page scrolls, not the text box)."""

    def __init__(self, parent=None):
        QtWidgets.QTextBrowser.__init__(self, parent)
        self.setObjectName("Description")
        self.setOpenExternalLinks(True)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.document().setDocumentMargin(0)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self.document().contentsChanged.connect(self._fit)

    def _fit(self):
        self.document().setTextWidth(self.viewport().width())
        self.setFixedHeight(int(self.document().size().height()) + 4)

    def resizeEvent(self, event):
        QtWidgets.QTextBrowser.resizeEvent(self, event)
        self._fit()



def zoom_cursor():
    """A magnifier with a plus, white on a dark disc so it shows on light and dark pictures."""
    size = 28
    result = QtGui.QPixmap(size, size)
    result.fill(Qt.transparent)
    painter = QtGui.QPainter(result)
    painter.setRenderHint(QtGui.QPainter.Antialiasing)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QtGui.QColor(0, 0, 0, 150))
    painter.drawEllipse(QtCore.QRectF(1, 1, size - 2, size - 2))
    painter.drawPixmap(5, 5, icons.pixmap("zoom-in", QtGui.QColor("#ffffff"), size - 10))
    painter.end()
    return QtGui.QCursor(result, size // 2, size // 2)


class DescriptionBrowser(AutoHeightBrowser):
    """Description text whose pictures sit inside it (a list item, a table cell, beside words). Each picture is a
    maxpkg-picture:<position> link around an <img>: the picture comes from the image cache (a grey box until it
    arrives, at most INLINE_WIDTH wide, never enlarged) and a click asks for the full size in the lightbox. Other
    links open in the browser."""

    picture_clicked = Signal(int)
    INLINE_WIDTH = 360
    OBJECT_CHARACTER = "\ufffc"  # what a picture is in the document's text

    def __init__(self, images, themes, parent=None):
        AutoHeightBrowser.__init__(self, parent)
        self.images = images
        self.themes = themes
        self._urls = []
        self._width = 0
        self.setOpenLinks(False)  # links are handled in _on_anchor
        self.anchorClicked.connect(self._on_anchor)
        images.ready.connect(self._on_ready)

    def set_description(self, html):
        self._urls = list(dict.fromkeys(unescape(url) for url in re.findall(r'<img src="([^"]+)"', html)))
        self._add_pictures()
        self.setHtml(html)
        self._single_height_picture_lines()

    def _single_height_picture_lines(self):
        """Description lines are 150 % high; on a line with a picture that would add half the picture as a gap."""
        block = self.document().begin()
        while block.isValid():
            if self.OBJECT_CHARACTER in block.text():
                cursor = QtGui.QTextCursor(block)
                block_format = block.blockFormat()
                block_format.setLineHeight(100, 1)  # 1 = ProportionalHeight, an int in both Qt bindings
                cursor.setBlockFormat(block_format)
            block = block.next()

    def _picture(self, url, width):
        picture = self.images.get(url)
        if picture is None or picture.isNull():
            box = QtGui.QPixmap(min(width, 160), 90)
            box.fill(self.themes.manager.color("surfaceSecondary"))
            return box
        return picture.scaledToWidth(width, Qt.SmoothTransformation) if picture.width() > width else picture

    def _add_pictures(self):
        self._width = max(40, min(self.INLINE_WIDTH, self.viewport().width() - 4))
        for url in self._urls:
            self.document().addResource(QtGui.QTextDocument.ImageResource, QtCore.QUrl(url),
                                        self._picture(url, self._width))

    def _refresh(self):
        self._add_pictures()
        self.document().markContentsDirty(0, self.document().characterCount())
        self._fit()

    def _on_ready(self, source):
        if source in self._urls:
            self._refresh()

    def resizeEvent(self, event):
        AutoHeightBrowser.resizeEvent(self, event)
        if self._urls and max(40, min(self.INLINE_WIDTH, self.viewport().width() - 4)) != self._width:
            self._refresh()

    def _on_anchor(self, url):
        target = url.toString()
        if target.startswith(markdown.PICTURE_LINK):
            self.picture_clicked.emit(int(target[len(markdown.PICTURE_LINK):]))
        else:
            QtGui.QDesktopServices.openUrl(url)  # what openExternalLinks did


class ScreenshotViewer(QtWidgets.QWidget):
    """Screenshot gallery: main image with round previous/next buttons and a 'n / N' counter, title and caption,
    and a thumbnail strip. A click on the image opens the full-window lightbox.

    compact=True is the side gallery of wide Details windows (above Package information): smaller image, one
    horizontally scrollable row of thumbnails, caption under the title. titles=False leaves out the title and caption
    (pictures in a description, whose alt text is often a file name); loop=False stops at the first and last image;
    heights=(minimum, maximum) bounds the image area, which follows the width.
    """

    preview_requested = Signal(int)

    def __init__(self, shots, images, themes, compact=False, titles=True, loop=True, heights=(260, 460), parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.shots = shots
        self.titles = titles
        self.heights = heights
        self.images = images
        self.compact = compact
        self.index = 0
        self.main = SlideView(len(shots), lambda position: images.get(shots[position].url), themes, radius=7,
                              failed_for=lambda position: images.failed(shots[position].url), loop=loop)
        self.main.setObjectName("ScreenshotMain")
        self.main.setMinimumHeight(150 if compact else 260)
        self.main.setCursor(Qt.PointingHandCursor)
        self.main.setToolTip("Click to open, drag sideways for the next screenshot")
        self.main.clicked.connect(lambda: self.preview_requested.emit(self.index))
        self.main.index_changed.connect(self._show_index)
        self.left = QtWidgets.QPushButton(self.main)
        self.right = QtWidgets.QPushButton(self.main)
        for button, icon_name, step in ((self.left, "gallery-chevron-left", -1), (self.right, "gallery-chevron-right", 1)):
            button.setObjectName("GalleryNav")
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(32, 32)
            themes.bind_icon(button, icon_name, "textStrong", 16)
            button.clicked.connect(lambda _checked=False, delta=step: self.main.slide(delta))
            button.setVisible(len(shots) > 1)
        self.counter = label("", "GalleryCounter", parent=self.main)
        self.counter.setVisible(len(shots) > 1)
        self.title = label("", "ChangelogVersion", wrap=True)
        self.caption = label("", "Muted", wrap=True)
        self.title.setVisible(titles)
        self._thumb_buttons = []
        thumb_size = QtCore.QSize(88, 54) if compact else QtCore.QSize(120, 72)
        self._thumb_icon = QtCore.QSize(thumb_size.width() - 6, thumb_size.height() - 6)
        if compact:
            strip = QtWidgets.QWidget()
            strip.setObjectName("ThumbStripContent")
            strip_layout = hbox(spacing=8)
            strip.setLayout(strip_layout)
            self.thumbs = QtWidgets.QScrollArea()
            self.thumbs.setObjectName("ThumbStrip")
            self.thumbs.setWidget(strip)
            self.thumbs.setWidgetResizable(True)
            self.thumbs.setFrameShape(QtWidgets.QFrame.NoFrame)
            self.thumbs.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            self.thumbs.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
            self.thumbs.setFixedHeight(thumb_size.height() + 14)
            self._drag = DragScroll(self.thumbs)  # the strip scrolls by dragging, thumbnails included
            self._drag.watch(strip)
        else:
            self.thumbs = FlowRow(spacing=8)
            self._drag = None
        for position, shot in enumerate(shots):
            button = QtWidgets.QPushButton()
            button.setObjectName("Thumb")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setFixedSize(thumb_size)
            button.setIconSize(self._thumb_icon)
            button.setToolTip(shot.title)
            button.clicked.connect(lambda _checked=False, value=position: self.select(value))
            self._thumb_buttons.append(button)
            if compact:
                self._drag.watch(button)
                strip_layout.addWidget(button)
            else:
                self.thumbs.add(button)
        if compact:
            strip_layout.addStretch(1)
        self.setLayout(vbox(self.main, self.title, self.caption, self.thumbs, spacing=6 if compact else 8))
        images.ready.connect(self._on_ready)
        self.select(0)

    def select(self, index):
        """Jump straight to a screenshot (thumbnails); arrows and drags slide through SlideView instead."""
        if self.shots:
            self.main.set_index(index)

    def _show_index(self, index):
        self.index = index
        shot = self.shots[self.index]
        self.title.setText(shot.title)
        self.caption.setText(shot.caption)
        self.caption.setVisible(self.titles and bool(shot.caption))
        self.counter.setText("{} / {}".format(self.index + 1, len(self.shots)))
        self.counter.adjustSize()
        for position, button in enumerate(self._thumb_buttons):
            button.setChecked(position == self.index)
        if self.compact and self._thumb_buttons:
            self.thumbs.ensureWidgetVisible(self._thumb_buttons[self.index], 24, 0)
        self._paint()

    def _paint(self):
        self.main.refresh()
        dpr = self.devicePixelRatioF()
        icon = self._thumb_icon
        for position, button in enumerate(self._thumb_buttons):
            thumb = self.images.get(self.shots[position].thumbnail_url)
            if thumb is not None:
                button.setIcon(QtGui.QIcon(rounded(thumb, icon.width(), 4, dpr).scaled(
                    int(icon.width() * dpr), int(icon.height() * dpr), Qt.KeepAspectRatioByExpanding,
                    Qt.SmoothTransformation)))

    def _on_ready(self, _source):
        self._paint()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        if self.compact:
            height = max(150, int(self.width() * 0.62))
        else:
            height = max(self.heights[0], min(self.heights[1], int(self.width() * 0.56)))
        self.main.setFixedHeight(height)
        self.left.move(10, height // 2 - 16)
        self.right.move(self.width() - 42, height // 2 - 16)
        self.counter.adjustSize()  # the first select() runs before the stylesheet padding is known
        self.counter.move(self.width() - self.counter.width() - 10, height - self.counter.height() - 10)
        self._paint()


class DescriptionImage(QtWidgets.QWidget):
    """A picture of a package description, as on maxpkg.dev: its own size, or the description width when it is
    wider, centred with rounded corners; a click opens the lightbox."""

    clicked = Signal()
    RADIUS = 8
    LOADING_RATIO = 9 / 16.0  # height for width until the picture has arrived

    def __init__(self, shot, images, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.shot = shot
        self.images = images
        self.themes = themes
        self.setCursor(zoom_cursor())
        self.setToolTip("Click to enlarge")
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        images.ready.connect(self._on_ready)

    def _picture(self):
        picture = self.images.get(self.shot.url)
        return picture if picture is not None and not picture.isNull() else None

    def _target(self, width):
        """Where the picture goes in a widget `width` wide (logical pixels)."""
        picture = self._picture()
        if picture is None:
            return QtCore.QRectF(0, 0, width, width * self.LOADING_RATIO)
        natural = picture.size() / max(1.0, picture.devicePixelRatioF())
        shown = natural.scaled(min(width, natural.width()), 100000, Qt.KeepAspectRatio)
        return QtCore.QRectF((width - shown.width()) / 2.0, 0, shown.width(), shown.height())

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(round(self._target(width).height()))

    def sizeHint(self):
        return QtCore.QSize(400, self.heightForWidth(400))

    def _on_ready(self, source):
        if source == self.shot.url:
            self.updateGeometry()
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event_pos(event)):
            self.clicked.emit()

    def paintEvent(self, _event):
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        target = self._target(self.width())
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(target, self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)
        picture = self._picture()
        if picture is None:
            painter.fillRect(target, self.themes.manager.color("surfaceSecondary"))
            if self.images.failed(self.shot.url):
                painter.setClipping(False)
                painter.setPen(self.themes.manager.color("textMuted"))
                painter.drawText(target, Qt.AlignCenter, "This picture could not be loaded.")
        else:
            painter.drawPixmap(target, picture, QtCore.QRectF(picture.rect()))
        painter.end()


class VideoThumbnail(QtWidgets.QWidget):
    """16:9 thumbnail of a package video with a round play button and the duration; a click opens the video."""

    clicked = Signal()
    RADIUS = 8

    def __init__(self, video, images, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.video = video
        self.images = images
        self.themes = themes
        self._hover = False
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Watch on YouTube" if video.provider.startswith("youtube") else "Watch in your browser")
        policy = QtWidgets.QSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        images.ready.connect(self._on_ready)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return int(width * 9 / 16)

    def sizeHint(self):
        return QtCore.QSize(320, 180)

    def _on_ready(self, source):
        if source == self.video.thumbnail_url:
            self.update()

    def enterEvent(self, event):
        self._hover = True
        self.update()
        QtWidgets.QWidget.enterEvent(self, event)

    def leaveEvent(self, event):
        self._hover = False
        self.update()
        QtWidgets.QWidget.leaveEvent(self, event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event_pos(event)):
            self.clicked.emit()

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        painter.setRenderHint(QtGui.QPainter.SmoothPixmapTransform)
        area = QtCore.QRectF(self.rect())
        clip = QtGui.QPainterPath()
        clip.addRoundedRect(area, self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)
        painter.fillRect(area, theme.color("surfaceSecondary"))
        picture = self.images.get(self.video.thumbnail_url) if self.video.thumbnail_url else None
        if picture is not None and not picture.isNull():
            # Fill the frame (YouTube thumbnails carry black bars at 4:3), centred.
            size = picture.size().scaled(self.size(), Qt.KeepAspectRatioByExpanding)
            target = QtCore.QRectF((self.width() - size.width()) / 2.0, (self.height() - size.height()) / 2.0,
                                   size.width(), size.height())
            painter.drawPixmap(target, picture, QtCore.QRectF(picture.rect()))
        shade = QtGui.QColor(0, 0, 0, 40 if self._hover else 70)
        painter.fillRect(area, shade)
        painter.setClipping(False)
        # Play button: a dark disc with a white triangle, accent on hover.
        radius = max(18.0, min(30.0, self.width() / 12.0))
        center = area.center()
        disc = QtGui.QColor(theme.color("accent")) if self._hover else QtGui.QColor(0, 0, 0, 165)
        painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 210), 1.5))
        painter.setBrush(disc)
        painter.drawEllipse(center, radius, radius)
        side = radius * 0.8
        triangle = QtGui.QPolygonF([QtCore.QPointF(center.x() - side * 0.38, center.y() - side * 0.5),
                                    QtCore.QPointF(center.x() - side * 0.38, center.y() + side * 0.5),
                                    QtCore.QPointF(center.x() + side * 0.55, center.y())])
        painter.setPen(Qt.NoPen)
        painter.setBrush(QtGui.QColor("#ffffff"))
        painter.drawPolygon(triangle)
        duration = self.video.duration_text
        if duration:
            font = QtGui.QFont(self.font())
            font.setPixelSize(11)
            font.setBold(True)
            painter.setFont(font)
            metrics = QtGui.QFontMetrics(font)
            pill = QtCore.QRectF(0, 0, metrics.horizontalAdvance(duration) + 12, metrics.height() + 4)
            pill.moveBottomRight(area.bottomRight() - QtCore.QPointF(8, 8))
            painter.setBrush(QtGui.QColor(0, 0, 0, 190))
            painter.drawRoundedRect(pill, 4, 4)
            painter.setPen(QtGui.QColor("#ffffff"))
            painter.drawText(pill, Qt.AlignCenter, duration)
        painter.end()


class VideoCard(QtWidgets.QWidget):
    """Thumbnail and title of one package video."""

    def __init__(self, video, images, themes, on_open, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.thumbnail = VideoThumbnail(video, images, themes)
        self.thumbnail.clicked.connect(lambda: on_open(video))
        title = label(video.title or "Video", "VideoTitle", wrap=True)
        title.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.setLayout(vbox(self.thumbnail, title, spacing=8))


class DetailsPage(ScrollPage):
    def __init__(self, window, parent=None):
        ScrollPage.__init__(self, parent)
        self.manager_window = window
        self.runtime = window.runtime
        self.guid = ""
        self.tab = "description"
        self.single_column = False
        self._content = None
        self.canvas_layout.addStretch(1)
        window.runtime.details_changed.connect(self._on_details)

    def show_package(self, guid):
        if guid != self.guid:
            self.tab = "description"
        self.guid = guid
        package = self.runtime.package(guid) or self._remote(guid)
        if package is not None:
            self.runtime.load_details(package)
        self.refresh()
        self.verticalScrollBar().setValue(0)

    def _remote(self, guid):
        page = self.runtime.catalog.page
        if page is not None:
            for package in page.packages:
                if package.guid.lower() == guid.lower():
                    return package
        return self.runtime.details.get(guid.lower())

    def package(self):
        merged = self.runtime.merged_details(self.guid)
        if merged is None:
            merged = self._remote(self.guid)
        return merged

    def set_single_column(self, single):
        if single != self.single_column:
            self.single_column = single
            if self.guid:
                self.refresh()

    def _on_details(self, guid):
        if guid.lower() == self.guid.lower() and self.isVisible():
            position = self.verticalScrollBar().value()
            self.refresh()
            self.verticalScrollBar().setValue(position)

    def refresh(self):
        package = self.package()
        if self._content is not None:
            self._content.hide()
            self._content.deleteLater()
        self._content = QtWidgets.QWidget()
        if package is None:
            self._content.setLayout(vbox(label("The package could not be found.", "StateText")))
            self.canvas_layout.insertWidget(0, self._content)
            return
        self.manager_window.set_details_path(package)
        main = QtWidgets.QWidget()
        main.setLayout(vbox(self._hero(package), spacing=12))
        notice = self._purchase_notice(package)
        if notice is not None:
            main.layout().addWidget(notice)
        main.layout().addLayout(self._tabs(package))
        main.layout().addWidget(self._tab_panel(package))
        main.layout().addStretch(1)
        sidebar = self._information(package)
        if self.single_column:
            layout = vbox(main, sidebar, spacing=12)
        else:
            # Wide window: the gallery lives above Package information instead of in a tab.
            column = QtWidgets.QWidget()
            column_layout = vbox(spacing=12)
            if package.screenshots:
                column_layout.addWidget(self._side_gallery(package))
            column_layout.addWidget(sidebar)
            links = self._links(package)
            if links is not None:
                column_layout.addWidget(links)
            column.setLayout(column_layout)
            layout = hbox(spacing=16)
            layout.addWidget(main, 62)
            layout.addWidget(column, 38, Qt.AlignTop)
        self._content.setLayout(layout)
        self.canvas_layout.insertWidget(0, self._content)

    # --- blocks -----------------------------------------------------------------------
    def _hero(self, package):
        themes = self.manager_window.themes
        frame = QtWidgets.QFrame()
        frame.setObjectName("DetailsHero")
        icon = PackageIcon(package, self.manager_window.images, 48, large=True)
        name = label(package.display_name, "DetailsName", wrap=True)
        by = label("Version {} by {}".format(package.version, package.developer or "Unknown developer"), "Muted")
        badges = FlowRow(spacing=6)
        installed = self.runtime.package(package.guid)
        for text, kind in self._badges(package, installed):
            badges.add(Badge(text, kind))
        # Actions sit at the top right, next to the name (as in the maxpkg.dev mock-up).
        actions = hbox(spacing=8)
        if installed is None:
            install = Button("Install", "download", "primary", themes)
            install.clicked.connect(lambda: self.manager_window.install(package.guid))
            actions.addWidget(install)
        else:
            run = Button("Run", "play", "primary", themes)
            run.clicked.connect(lambda: self.manager_window.run(package.guid))
            actions.addWidget(run)
            if installed.update_available:
                update = Button("Update to " + installed.latest_version, "download", "success", themes)
                update.clicked.connect(lambda: self.manager_window.update_package(package.guid))
                actions.addWidget(update)
            remove = Button("Uninstall", "trash-2", "danger", themes)
            remove.clicked.connect(lambda: self.manager_window.uninstall(package.guid))
            actions.addWidget(remove)
        top = hbox(icon, vbox(name, by, badges, spacing=4), spacing=12)
        top.addLayout(actions)
        top.setStretch(1, 1)
        top.setAlignment(actions, Qt.AlignTop)
        top.setAlignment(icon, Qt.AlignTop)
        frame.setLayout(vbox(top, margins=(12, 12, 12, 12)))
        return frame

    def _badges(self, package, installed):
        found = []
        if package.runtime:
            found.append((package.runtime, "default"))
        if package.release_channel:
            found.append((package.release_channel, "default"))
        if package.license_type:
            found.append((package.license_type, "warning"))
        if installed is not None and self.runtime.is_on_toolbar(installed):
            found.append(("Toolbar", "default"))
        if package.details_loaded:
            found.append(("Online info", "default"))
        elif installed is not None:
            found.append(("Offline info", "warning"))
        return found

    def _purchase_notice(self, package):
        if not package.purchase_url:
            return None
        themes = self.manager_window.themes
        action_label = package.purchase_label()
        lowered = action_label.lower()
        title, copy, free = PURCHASE_COPY.get(lowered) or (LICENSE_COPY if "license" in lowered else DEFAULT_PURCHASE_COPY)
        frame = QtWidgets.QFrame()
        frame.setObjectName("PurchaseNotice")
        frame.setProperty("kind", "free" if free else "paid")
        badge = QtWidgets.QLabel()
        badge.setObjectName("NoticeBadge")
        badge.setProperty("kind", frame.property("kind"))
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignCenter)
        themes.bind_icon(badge, "heart" if free else "shopping-cart", "iconSuccess" if free else "iconAccent", 18)
        text = vbox(label(title, "NoticeTitle"), label(copy, "NoticeText", wrap=True), spacing=2)
        button = Button(action_label, "heart-success" if free else "external-link", "installed" if free else "primary",
                        themes)
        button.setToolTip("Opens the author's page in your browser")
        button.clicked.connect(lambda: self.runtime.open_link(package, "purchase"))
        button.shimmer = Shimmer(button, radius=10)  # only this big button in Details shimmers, never the card pills
        row = hbox(spacing=14, margins=(14, 12, 14, 12))
        row.addWidget(badge, 0, Qt.AlignVCenter)
        row.addLayout(text, 1)
        row.addWidget(button, 0, Qt.AlignVCenter)
        frame.setLayout(row)
        return frame

    def _tabs(self, package):
        row = hbox(spacing=0)
        shots = len(package.screenshots) if self.single_column else 0
        if (self.tab == "screenshots" and not shots) or (self.tab == "videos" and not package.videos):
            self.tab = "description"
        tabs = [("description", "Description", None)]
        if shots:
            tabs.append(("screenshots", "Screenshots", shots))
        if package.videos:
            tabs.append(("videos", "Videos", len(package.videos)))
        tabs.append(("changelog", "Changelog", len(changelog_versions(package))))  # releases, not single changes
        for key, text, count in tabs:
            button = DetailsTab(text, count)
            button.setChecked(key == self.tab)
            button.clicked.connect(lambda _checked=False, value=key: self._select_tab(value))
            row.addWidget(button)
        row.addStretch(1)
        return row

    def _select_tab(self, key):
        self.tab = key
        self.refresh()

    def show_tab(self, key):
        """Open the shown package on a tab ("changelog"); kept when its online details arrive."""
        self._select_tab(key)

    def _tab_panel(self, package):
        if self.tab == "screenshots":
            frame, layout = section("Screenshots")
            viewer = ScreenshotViewer(package.screenshots, self.manager_window.images, self.manager_window.themes)
            viewer.preview_requested.connect(lambda index: self.manager_window.preview_screenshots(package.screenshots, index))
            layout.addWidget(viewer)
            return frame
        if self.tab == "changelog":
            return self._changelog(package)
        if self.tab == "videos":
            return self._videos(package)
        holder = QtWidgets.QWidget()
        frame, layout = section("Description")
        # Pictures load only from the service's content CDN or its own site (maxpkg.dev rules), numbered in reading
        # order: a click outside a gallery walks all of them in the lightbox, a gallery click only its own.
        pictures = markdown.Pictures(self.runtime.site_url())
        everything = []  # Screenshot per picture position, filled once the whole description is laid out
        parts = []
        for kind, content in (markdown.split_media(package.full_description, pictures)
                              if package.full_description else []):
            if kind == "images":
                positions = [pictures.add(alt, url) for alt, url in content]
                parts.append(self._description_pictures(positions, pictures, everything))
                continue
            html = markdown.to_html(content, pictures)
            if html:
                parts.append(self._description_text(html, everything))
        everything.extend(Screenshot(url, url, "") for _alt, url in pictures.items)  # alt is no caption
        if not parts:
            parts.append(self._description_text(
                "<p>" + markdown.inline(package.description or "No description provided.") + "</p>", everything))
        for part in parts:
            layout.addWidget(part)
        column = vbox(frame, spacing=12)
        links = self._links(package) if self.single_column else None  # wide windows show Links in the side column
        if links is not None:
            column.addWidget(links)
        holder.setLayout(column)
        return holder

    def _description_text(self, html, everything):
        browser = DescriptionBrowser(self.manager_window.images, self.manager_window.themes)
        browser.picture_clicked.connect(lambda position: self.manager_window.preview_screenshots(everything, position))
        theme = self.manager_window.themes.manager
        colors = {name: theme.color(name).name() for name in (
            "textSecondary", "textStrong", "textPrimary", "textMuted", "accentHover", "borderStrong",
            "surfaceTertiary", "surfaceSecondary")}
        browser.document().setDefaultStyleSheet(
            "p, li {{ line-height: 150%; color: {textSecondary}; }} h3, h4, h5, h6 {{ color: {textStrong}; }}"
            " a {{ color: {accentHover}; }} code, pre {{ font-family: Consolas; color: {textPrimary}; }}"
            " pre {{ background-color: {surfaceSecondary}; }}"
            " blockquote {{ color: {textMuted}; margin-left: 12px; }}"
            " table.md {{ border-collapse: collapse; border: 1px solid {borderStrong}; margin-top: 6px;"
            " margin-bottom: 6px; }}"
            " th {{ background-color: {surfaceTertiary}; color: {textStrong}; font-weight: bold;"
            " border: 1px solid {borderStrong}; }}"
            " td {{ color: {textSecondary}; border: 1px solid {borderStrong}; }}".format(**colors))
        browser.set_description(html)
        return browser

    def _description_pictures(self, positions, pictures, everything):
        """Pictures on lines of their own: one at the description width, several as a carousel in a bordered block
        with 'N images' at the top right (one slide at a time, no looping, thumbnails below)."""
        images, themes = self.manager_window.images, self.manager_window.themes
        shots = [Screenshot(pictures.items[position][1], pictures.items[position][1], "") for position in positions]
        if len(shots) == 1:
            picture = DescriptionImage(shots[0], images, themes)
            picture.clicked.connect(lambda: self.manager_window.preview_screenshots(everything, positions[0]))
            return picture
        gallery = QtWidgets.QFrame()
        gallery.setObjectName("DescriptionGallery")
        viewer = ScreenshotViewer(shots, images, themes, titles=False, loop=False, heights=(200, 600))
        viewer.preview_requested.connect(lambda index: self.manager_window.preview_screenshots(shots, index))
        count = label("{} images".format(len(shots)), "Muted")
        gallery.setLayout(vbox(hbox(None, count), viewer, spacing=6, margins=(12, 10, 12, 12)))
        return gallery

    def _links(self, package):
        themes = self.manager_window.themes
        row = FlowRow(spacing=12, row_spacing=10)
        for kind, text in (("maxpkg", "MaxPkg page"), ("homepage", "Homepage"), ("documentation", "Documentation"),
                           ("support", "Support"), ("license", "License")):
            if kind == "maxpkg" and not package.slug:
                continue
            if kind != "maxpkg" and not self.runtime.link_url(package, kind):
                continue
            button = Button(text, "external-link", "default", themes)
            button.clicked.connect(lambda _checked=False, value=kind: self.runtime.open_link(package, value))
            row.add(button)
        if self.runtime.package(package.guid) is not None:
            folder = Button("Open Folder", "folder-open", "default", themes)
            folder.clicked.connect(lambda: self.runtime.open_folder(package.guid))
            row.add(folder)
        frame, layout = section("Links")
        if package.slug:  # the small copy icon sits at the end of the section title, outside the button rows
            title = layout.takeAt(0).widget()
            header = InfoRow(name="SectionHeader")
            header.setMinimumHeight(CopyButton.SIZE)  # room for the hover frame (children are clipped)
            header.setLayout(hbox(title, None, CopyButton.SIZE))
            copy = CopyButton("Copy MaxPkg link", themes)
            copy.clicked.connect(lambda: self.manager_window.copy_text(self.runtime.link_url(package, "maxpkg"), "Link copied."))
            header.overlay(copy)
            layout.insertWidget(0, header)
        layout.addWidget(row)
        return frame

    def _changelog(self, package):
        frame, layout = section("Full changelog")
        if not package.changelog:
            layout.addWidget(label("No changelog entries were provided with this package.", "Muted"))
            return frame
        for (version, date), entries in changelog_versions(package):
            header = hbox(label(version, "ChangelogVersion"), label(date, "ChangelogDate"), None, spacing=10)
            layout.addSpacing(6)
            layout.addLayout(header)
            for entry in entries:
                kind = entry.change_type.lower() if entry.change_type.lower() in CHANGE_TYPES else "default"
                badge = Badge(entry.change_type, kind)
                badge.setFixedWidth(72)
                badge.setAlignment(Qt.AlignCenter)
                text = label(entry.text, "", wrap=True)
                text.setTextInteractionFlags(Qt.TextSelectableByMouse)
                row = hbox(spacing=10)
                row.addWidget(badge, 0, Qt.AlignTop)
                row.addWidget(text, 1)
                layout.addLayout(row)
        return frame

    def _videos(self, package):
        """Video cards, two per row (one video takes the whole width); a click opens it in the browser."""
        frame, layout = section("Videos")
        grid = QtWidgets.QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(16)
        columns = 1 if len(package.videos) == 1 else 2
        for position, video in enumerate(package.videos):
            card = VideoCard(video, self.manager_window.images, self.manager_window.themes,
                             lambda chosen: self.runtime.open_video(chosen.url))
            grid.addWidget(card, position // columns, position % columns, Qt.AlignTop)
        for column in range(columns):
            grid.setColumnStretch(column, 1)
        layout.addLayout(grid)
        return frame

    def _side_gallery(self, package):
        frame, layout = section("Screenshots")
        viewer = ScreenshotViewer(package.screenshots, self.manager_window.images, self.manager_window.themes,
                                  compact=True)
        viewer.preview_requested.connect(lambda index: self.manager_window.preview_screenshots(package.screenshots, index))
        layout.addWidget(viewer)
        return frame

    def _information(self, package):
        frame = QtWidgets.QFrame()
        frame.setObjectName("DetailsSection")
        layout = vbox(spacing=0, margins=(12, 12, 12, 8))
        title = label("PACKAGE INFORMATION", "SectionTitle")
        if package.slug:  # the package's page on maxpkg.dev, at the end of the section title
            website = QtWidgets.QPushButton("Package page")
            website.setObjectName("SectionLink")
            website.setCursor(Qt.PointingHandCursor)
            website.setToolTip("Open " + self.runtime.link_url(package, "maxpkg"))
            website.setLayoutDirection(Qt.RightToLeft)  # the icon after the text, like the status bar link
            self.manager_window.themes.bind_icon(website, "external-link", "successText", 11)
            website.clicked.connect(lambda: self.runtime.open_link(package, "maxpkg"))
            layout.addLayout(hbox(title, None, website, spacing=6))
        else:
            layout.addWidget(title)
        layout.addSpacing(8)
        installed = self.runtime.package(package.guid)
        integration = "Toolbar" if installed is not None and self.runtime.is_on_toolbar(installed) else (
            "Package" if installed is None else "Hidden")
        packager = (package.packager_name + (" " + package.packager_version if package.packager_version else "")).strip()
        compatibility = supported_versions(package) or "Any version"
        rows = [("Version", package.version), ("Release date", package.release_date), ("3ds Max", compatibility),
                ("Author", package.developer), ("Type", package.runtime), ("Channel", package.release_channel),
                ("License", package.license_type), ("Integration", integration), ("Packager", packager)]
        if package.is_remote or package.details_loaded:  # catalog stats; a package only known locally has none
            layout.addWidget(self._rating_row(package))
            downloads = self._info_row("Downloads", compact_number(package.download_count), icon="download")
            downloads.findChild(QtWidgets.QLabel, "InfoValue").setToolTip("{:,} downloads".format(package.download_count))
            layout.addWidget(downloads)
        identifier = package.slug or package.guid
        if identifier:
            layout.addWidget(self._info_row("Package ID", identifier, copy=True))
        for key, value in rows:
            if value:
                layout.addWidget(self._info_row(key, value))
        frame.setLayout(layout)
        return frame

    def _rating_row(self, package):
        """'★★★★☆ 4.2 (12)' as on maxpkg.dev: stars and score in the warning colour, the review count muted."""
        theme = self.manager_window.themes.manager
        filled = max(0, min(5, int(package.rating + 0.5)))
        score = "{} {:.1f}".format("★" * filled + "☆" * (5 - filled), package.rating)
        reviews = "({})".format(package.review_count)
        row = self._info_row("Rating", score + " " + reviews)
        value_label = row.findChild(QtWidgets.QLabel, "InfoValue")
        value_label.setTextFormat(Qt.RichText)
        value_label.setText('<span style="color:{};">{}</span> <span style="color:{};">{}</span>'.format(
            theme.color("warning").name(), score, theme.color("textMuted").name(), reviews))
        value_label.setToolTip("Rating {:.1f} from {} review(s)".format(package.rating, package.review_count))
        return row

    def _info_row(self, key, value, copy=False, icon=""):
        row = InfoRow()
        value_label = label(value, "InfoValue")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setToolTip(value)
        layout = hbox(label(key, "InfoKey"), None, spacing=6, margins=(0, 8, 0, 8))
        if icon:
            layout.addWidget(IconLabel(icon, self.manager_window.themes, "iconMuted", 13))
        layout.addWidget(value_label)
        if copy:
            button = CopyButton("Copy Package ID", self.manager_window.themes)
            button.clicked.connect(lambda: self.manager_window.copy_text(value, "Package ID copied."))
            layout.addSpacing(CopyButton.SIZE + 2)
            row.overlay(button)
        row.setLayout(layout)
        return row


class DetailsTab(QtWidgets.QPushButton):
    """Description / Screenshots / Changelog tab. The count sits inside the tab, right after its title, so the
    underline runs under both (like the Discover / Installed / Updates tabs)."""

    GAP = 6  # px between the title and the count

    def __init__(self, text, count=None, parent=None):
        QtWidgets.QPushButton.__init__(self, text, parent)
        self.setObjectName("DetailsTab")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._text = text
        self.counter = None
        if count is not None:
            self.counter = label(str(count), "DetailsTabCount", parent=self)
            self.counter.setFixedHeight(16)
            self.counter.setAlignment(Qt.AlignCenter)
            self.counter.setAttribute(Qt.WA_TransparentForMouseEvents)

    def showEvent(self, event):
        QtWidgets.QPushButton.showEvent(self, event)
        self._reserve()

    def _reserve(self):
        """Trailing spaces make room for the count, so the stylesheet still draws the title (and its hover and
        checked colours) and the tab, with its underline, is as wide as title and count together."""
        if self.counter is None:
            return
        self.counter.ensurePolished()
        width = self.counter.sizeHint().width()
        space = max(1, self.fontMetrics().horizontalAdvance(" "))
        text = self._text + " " * int(math.ceil((self.GAP + width) / float(space)))
        if text != self.text():
            self.setText(text)
        self._place()

    def _place(self):
        if self.counter is None:
            return
        width = self.counter.sizeHint().width()
        option = QtWidgets.QStyleOptionButton()
        self.initStyleOption(option)
        # The button centres its text in the contents rect (inside the stylesheet's margin and padding).
        content = self.style().subElementRect(QtWidgets.QStyle.SE_PushButtonContents, option, self)
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        left = content.left() + (content.width() - text_width) // 2
        self.counter.setGeometry(left + self.fontMetrics().horizontalAdvance(self._text) + self.GAP,
                                 (self.height() - 16) // 2, width, 16)

    def resizeEvent(self, event):
        QtWidgets.QPushButton.resizeEvent(self, event)
        self._place()


class InfoRow(QtWidgets.QFrame):
    """One 'key  value' line of Package information. A trailing button floats over the row's right end, so it
    keeps the same height as the plain text rows."""

    def __init__(self, parent=None, name="InfoRow"):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName(name)
        self._button = None

    def overlay(self, button):
        button.setParent(self)
        self._button = button

    def resizeEvent(self, event):
        QtWidgets.QFrame.resizeEvent(self, event)
        if self._button is not None:
            button = self._button
            button.move(self.width() - button.width(), (self.height() - button.height()) // 2)
            button.raise_()


__all__ = ["DetailsPage", "SINGLE_COLUMN", "IconLabel"]
