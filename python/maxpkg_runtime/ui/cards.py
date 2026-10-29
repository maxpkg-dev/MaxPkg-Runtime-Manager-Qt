"""Package cards: compact/full installed cards and full Discover cards (HTML Manager layout)."""

from ..domain.packages import compact_number
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, is_valid
from ..services.images import rounded
from .widgets import Badge, Button, ElidedLabel, ElidedText, FlowRow, IconButton, IconLabel, Shimmer, hbox, label, vbox

FULL_CARD_HEIGHT = 248
COMPACT_CARD_HEIGHT = 128
DRAG_MIME = "application/x-maxpkg-package-guid"


class PackageIcon(QtWidgets.QLabel):
    """Package image in a rounded frame, or the package initials until/unless an image exists."""

    def __init__(self, package, images, size=44, large=False, parent=None):
        QtWidgets.QLabel.__init__(self, parent)
        self.setObjectName("PackageIcon")
        if large:
            self.setProperty("large", "true")
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self._images = images
        self._size = size
        self._inner = size - (10 if large else 8)
        self._radius = 7 if not large else 8
        self._source = package.icon_file or package.icon_url
        self.setText(package.initials)
        font = self.font()
        font.setBold(True)
        font.setPixelSize(max(11, size // 3))
        self.setFont(font)
        images.ready.connect(self._on_ready)
        self._show()

    def _show(self):
        pixmap = self._images.get(self._source)
        if pixmap is not None:
            self.setPixmap(rounded(pixmap, self._inner, self._radius, self.devicePixelRatioF()))

    def _on_ready(self, source):
        if source == self._source:
            self._show()


class _CardBase(QtWidgets.QFrame):
    def __init__(self, package, host, parent=None):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("Card")
        self.setAttribute(Qt.WA_Hover)
        self.setAttribute(Qt.WA_StyledBackground)
        self.package = package
        self.host = host
        self.setCursor(Qt.PointingHandCursor)

    def _shine(self, button):
        """The card's main action shimmers once the pointer has rested on the card for a moment."""
        button.shimmer = Shimmer(button, radius=10, hover_area=self, hover_delay=CARD_SHINE_DELAY_MS)

    def _heading(self, show_hidden=False):
        """Icon + title + 'v1.2 · developer' as one clickable area that opens Details."""
        package = self.package
        icon = PackageIcon(package, self.host.images, 44)
        title = ElidedLabel(package.display_name, "CardTitle")
        meta_text = "v{} · {}".format(package.version, package.developer or "Unknown developer")
        meta = ElidedLabel(meta_text, "CardMeta")
        meta_row = hbox(spacing=4)
        if show_hidden:
            hidden = IconLabel("eye-off", self.host.themes, "iconMuted", 12)
            hidden.setToolTip("Hidden from Toolbar")
            meta_row.addWidget(hidden)
        meta_row.addWidget(meta, 1)
        text_column = vbox(title, meta_row, spacing=2, margins=(0, 1, 0, 0))
        row = hbox(icon, text_column, spacing=10)
        row.setStretch(1, 1)
        return row

    def mousePressEvent(self, event):
        self._pressed = event.button() == Qt.LeftButton
        QtWidgets.QFrame.mousePressEvent(self, event)

    def mouseReleaseEvent(self, event):
        # The whole card opens Details (the HTML card only reacted on its heading); buttons keep their own clicks.
        if event.button() == Qt.LeftButton and getattr(self, "_pressed", False) and self.rect().contains(event.pos()):
            self.host.open_details(self.package.guid)
        self._pressed = False
        QtWidgets.QFrame.mouseReleaseEvent(self, event)

    def contextMenuEvent(self, event):
        """Right-click: the package's menu at the pointer (the ... menu for installed packages, Install and links
        for Discover cards of packages that are not installed)."""
        event.accept()
        self.host.package_menu(self.package.guid, self, event.globalPos(), remote=self.package)


class InstalledCard(_CardBase):
    """Installed/Updates card. Compact by default; full cards add description and badges."""

    def __init__(self, package, host, full=False, sortable=False, updates_view=False, parent=None):
        _CardBase.__init__(self, package, host, parent)
        themes = host.themes
        on_toolbar = host.runtime.is_on_toolbar(package)
        self.setToolTip("" if not sortable else "Click to open details, drag to change the toolbar order")
        layout = vbox(spacing=0, margins=(14, 14, 12, 12))
        layout.addLayout(self._heading(show_hidden=not on_toolbar))
        if full:
            layout.addSpacing(10)
            layout.addWidget(ElidedText(package.description or "No description provided.", 3))
            badges = FlowRow(spacing=6)
            badges.add(Badge(package.runtime))
            if on_toolbar:
                badges.add(Badge("Toolbar"))
            if package.update_available:
                badges.add(Badge("v{} available".format(package.latest_version), "warning"))
            layout.addSpacing(6)
            layout.addWidget(badges)
        layout.addStretch(1)
        actions = hbox(spacing=12, margins=(0, 10, 0, 0))
        if updates_view and package.update_available:
            update = Button("Update to " + package.latest_version, "download", "success", themes, compact=True)
            update.clicked.connect(lambda: host.update_package(package.guid))
            self._shine(update)
            actions.addWidget(update)
        else:
            run = Button("Run", "play", "primary", themes, compact=True)
            run.clicked.connect(lambda: host.run(package.guid))
            self._shine(run)
            actions.addWidget(run)
        actions.addStretch(1)
        more = IconButton("ellipsis", "More actions", themes)
        more.clicked.connect(lambda: host.package_menu(package.guid, more))
        actions.addWidget(more)
        layout.addLayout(actions)
        self.setLayout(layout)
        self.setMinimumHeight(FULL_CARD_HEIGHT - 70 if full else COMPACT_CARD_HEIGHT)
        self.sortable = sortable
        self._press_point = None
        self.handle = None
        if sortable:
            self.handle = DragHandle(self, themes)

    def resizeEvent(self, event):
        _CardBase.resizeEvent(self, event)
        if self.handle is not None:
            self.handle.move(self.width() - 32, 8)

    # The whole card drags when the list is in toolbar order; a click without moving still opens Details.
    def mousePressEvent(self, event):
        self._press_point = event.pos() if self.sortable and event.button() == Qt.LeftButton else None
        _CardBase.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        point = self._press_point
        if point is not None and (event.pos() - point).manhattanLength() >= CARD_DRAG_DISTANCE:
            self._press_point = None
            self._pressed = False  # the release after a drag must not open Details
            start_card_drag(self, point)
            return
        _CardBase.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self._press_point = None
        _CardBase.mouseReleaseEvent(self, event)


class DragHandle(QtWidgets.QLabel):
    """Grip in the card corner; dragging it reorders the toolbar (Installed sorted by Toolbar order)."""

    def __init__(self, card, themes):
        QtWidgets.QLabel.__init__(self, card)
        self.card = card
        self.setFixedSize(24, 28)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.SizeAllCursor)
        self.setToolTip("Drag to change Toolbar order")
        themes.bind_icon(self, "grip-vertical", "iconMuted", 16)
        self._press = None

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._press = event.pos()

    def mouseMoveEvent(self, event):
        if self._press is None or (event.pos() - self._press).manhattanLength() < 4:
            return
        press, self._press = self._press, None
        start_card_drag(self.card, self.mapTo(self.card, press))

    def mouseReleaseEvent(self, event):
        self._press = None


CARD_DRAG_DISTANCE = 6  # px a press on the card moves before it becomes a drag instead of a click
CARD_SHINE_DELAY_MS = 1500  # the pointer rests this long on a card before its main button shimmers


def start_card_drag(card, grab_point):
    """Drag `card` to change the toolbar order; `grab_point` (card coordinates) stays under the pointer."""
    host = card.host
    if host.runtime.settings.toolbar_locked:  # a locked toolbar keeps its order: say so instead
        if hasattr(host, "notify_toolbar_locked"):
            host.notify_toolbar_locked()
        return
    drag = QtGui.QDrag(card)
    data = QtCore.QMimeData()
    data.setData(DRAG_MIME, card.package.guid.encode("utf-8"))
    drag.setMimeData(data)
    snapshot = card.grab()
    dpr = card.devicePixelRatioF()
    scaled = snapshot.scaledToWidth(int(min(snapshot.width(), 260 * dpr)), Qt.SmoothTransformation)
    scale = scaled.width() / float(snapshot.width()) if snapshot.width() else 1.0
    drag.setPixmap(scaled)
    drag.setHotSpot(QtCore.QPoint(int(grab_point.x() * scale), int(grab_point.y() * scale)))
    card.setProperty("dragging", "true")
    drag.exec_(Qt.MoveAction) if hasattr(drag, "exec_") else drag.exec(Qt.MoveAction)
    if is_valid(card):
        card.setProperty("dragging", "false")


class RemoteCard(_CardBase):
    """Discover card: description, download/rating stats, purchase pill and Install."""

    def __init__(self, package, host, parent=None):
        _CardBase.__init__(self, package, host, parent)
        themes = host.themes
        installed = host.runtime.package(package.guid)
        layout = vbox(spacing=0, margins=(14, 14, 12, 12))
        layout.addLayout(self._heading(show_hidden=installed is not None and not host.runtime.is_on_toolbar(installed)))
        layout.addSpacing(10)
        layout.addWidget(ElidedText(package.description or "No description provided.", 5))
        layout.addStretch(1)
        stats = hbox(spacing=12)
        stats.addLayout(_stat(themes, "download", compact_number(package.download_count),
                              "{} downloads".format(package.download_count)))
        stats.addLayout(_stat(themes, "star", "{:.1f}".format(package.rating),
                              "Rating {:.1f} from {} review(s)".format(package.rating, package.review_count),
                              "({})".format(compact_number(package.review_count))))
        stats.addStretch(1)
        purchase = purchase_pill(package, host)
        if purchase is not None:
            stats.addWidget(purchase)
        layout.addLayout(stats)
        layout.addSpacing(12)
        actions = hbox(spacing=12)
        if installed is not None:
            button = Button("Installed", "check", "default", themes, compact=True)
            button.setEnabled(False)
        else:
            button = Button("Install", "download", "primary", themes, compact=True)
            button.clicked.connect(lambda: host.install(package.guid))
            self._shine(button)
        actions.addWidget(button)
        actions.addStretch(1)
        layout.addLayout(actions)
        self.setLayout(layout)
        self.setFixedHeight(FULL_CARD_HEIGHT)


def _stat(themes, icon_name, text, tooltip, secondary=""):
    glyph = IconLabel(icon_name, themes, "iconMuted", 13)
    value = label(text + (" " + secondary if secondary else ""), "CardStats")
    row = hbox(glyph, value, spacing=4)
    glyph.setToolTip(tooltip)
    value.setToolTip(tooltip)
    return row


def purchase_pill(package, host):
    """'Donate' / price pill that opens the purchase link, or None when the package has none."""
    if not package.purchase_url:
        return None
    text = package.purchase_label()
    icon_name = "shopping-cart"
    pill = QtWidgets.QPushButton(text)
    pill.setObjectName("PurchasePill")
    pill.setCursor(Qt.PointingHandCursor)
    pill.setToolTip("Open the purchase page")
    host.themes.bind_icon(pill, icon_name, "iconSuccess", 12)
    pill.clicked.connect(lambda: host.runtime.open_link(package, "purchase"))
    return pill


class CardGridHost(QtCore.QObject):
    """Interface the cards call back into (implemented by the Manager window)."""

    def open_details(self, guid):
        raise NotImplementedError

    def run(self, guid):
        raise NotImplementedError


__all__ = ["InstalledCard", "RemoteCard", "PackageIcon", "purchase_pill", "DRAG_MIME", "Signal"]
