"""Installed / Updates and Discover pages of the Manager."""

from ..domain.packages import merge_visible_order, version_key
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt
from . import icons
from .cards import DRAG_MIME, InstalledCard, RemoteCard
from .theme import css_color, with_alpha
from .widgets import Button, FlowRow, ResponsiveGrid, StatePanel, hbox, label, repolish, vbox

WIDE_DISCOVER = 1200


class ScrollPage(QtWidgets.QScrollArea):
    """Transparent scroll area with a padded canvas (16 px like .page-host)."""

    def __init__(self, parent=None):
        QtWidgets.QScrollArea.__init__(self, parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.canvas = QtWidgets.QWidget()
        self.canvas.setObjectName("PageCanvas")
        self.canvas_layout = vbox(spacing=12, margins=(16, 16, 16, 24))
        self.canvas.setLayout(self.canvas_layout)
        self.setWidget(self.canvas)
        self.viewport().setAutoFillBackground(False)
        self.canvas.setAutoFillBackground(False)


class InstalledPage(ScrollPage):
    def __init__(self, window, parent=None):
        ScrollPage.__init__(self, parent)
        self.manager_window = window
        self.runtime = window.runtime
        self.view = "installed"   # or "updates"
        self.search = ""
        self.grid = ResponsiveGrid(min_width=270, spacing=14, max_columns=4)
        self.state = None
        self.state_host = QtWidgets.QWidget()
        self.state_host.setLayout(vbox(margins=(0, 54, 0, 0)))
        self.canvas_layout.addWidget(self.grid)
        self.canvas_layout.addWidget(self.state_host)
        self.canvas_layout.addStretch(1)
        self.canvas.setAcceptDrops(True)
        self.canvas.installEventFilter(self)
        self._drop_guid = None

    @property
    def settings(self):
        return self.runtime.settings

    def sortable(self):
        return self.view == "installed" and self.settings.manager_sort == "toolbar"

    def visible_packages(self):
        search = self.search.lower()
        found = []
        for package in self.runtime.packages:
            haystack = " ".join((package.name, package.developer, package.description, package.guid)).lower()
            if search and search not in haystack:
                continue
            if self.view == "updates" and not package.update_available:
                continue
            on_toolbar = self.runtime.is_on_toolbar(package)
            if self.settings.manager_filter == "toolbar" and not on_toolbar:
                continue
            if self.settings.manager_filter == "hidden" and on_toolbar:
                continue
            found.append(package)
        sort = self.settings.manager_sort
        if sort == "toolbar":
            order = {guid.lower(): index for index, guid in enumerate(self.settings.toolbar_order)}
            found.sort(key=lambda package: (order.get(package.guid.lower(), 10 ** 6), package.name.lower()))
        elif sort == "version":
            found.sort(key=lambda package: version_key(package.version), reverse=True)
        elif sort == "developer":
            found.sort(key=lambda package: (package.developer.lower(), package.name.lower()))
        else:
            found.sort(key=lambda package: package.name.lower())
        return found

    def refresh(self):
        packages = self.visible_packages()
        full = self.settings.manager_full_cards
        cards = [InstalledCard(package, self.manager_window, full=full, sortable=self.sortable(),
                               updates_view=self.view == "updates") for package in packages]
        self.grid.set_items(cards)
        if self.state is not None:
            self.state.hide()
            self.state.deleteLater()
            self.state = None
        if not packages:
            if self.runtime.packages:
                title, text = "No packages match", "Try a different search or filter."
            else:
                title = "No packages installed"
                text = "Installed packages will appear here as soon as Runtime discovers their manifests."
            if self.view == "updates" and self.runtime.packages and not self.search:
                title, text = "Everything is up to date", "Use Check Updates to look for new versions."
            self.state = StatePanel(self.manager_window.themes, "package", title, text, "Refresh", "refresh-cw")
            self.state.action.clicked.connect(self.runtime.scan)
            self.state_host.layout().addWidget(self.state, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.state_host.setVisible(self.state is not None)

    # --- toolbar order drag & drop -------------------------------------------------
    def eventFilter(self, watched, event):
        if getattr(self, "view", None) is not None and watched is self.canvas and self.sortable():
            kind = event.type()
            if kind in (QtCore.QEvent.DragEnter, QtCore.QEvent.DragMove) and event.mimeData().hasFormat(DRAG_MIME):
                event.acceptProposedAction()
                self._mark_target(self._target(event))
                return True
            if kind == QtCore.QEvent.DragLeave:
                self._mark_target(None)
                return True
            if kind == QtCore.QEvent.Drop and event.mimeData().hasFormat(DRAG_MIME):
                guid = bytes(event.mimeData().data(DRAG_MIME)).decode("utf-8")
                target = self._target(event)
                self._mark_target(None)
                event.acceptProposedAction()
                QtCore.QTimer.singleShot(0, lambda: self._reorder(guid, target))
                return True
        return ScrollPage.eventFilter(self, watched, event)

    def _target(self, event):
        position = self.grid.mapFrom(self.canvas, _event_point(event))
        card = self.grid.item_at(position)
        if card is None:
            return None
        after = position.x() > card.geometry().center().x()
        return card.package.guid, after

    def _mark_target(self, target):
        for card in self.grid.items():
            marked = target is not None and card.package.guid == target[0]
            if (card.property("dropTarget") == "true") != marked:
                card.setProperty("dropTarget", "true" if marked else "false")
                repolish(card)

    def _reorder(self, guid, target):
        shown = [card.package.guid for card in self.grid.items()]
        if guid not in shown or target is None or target[0] == guid:
            return
        shown.remove(guid)
        index = shown.index(target[0]) + (1 if target[1] else 0)
        shown.insert(index, guid)
        merged = merge_visible_order(self.settings.toolbar_order, shown, [package.guid for package in
                                                                          self.visible_packages()])
        self.runtime.set_full_order(merged)


def _event_point(event):
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


class CollectionPill(QtWidgets.QAbstractButton):
    """Collection chip: accent-tinted pill with Lucide icon, name and count (accent color comes from the API).

    Painted directly so the count bubble can never overlap the name. Like the HTML Manager, all chips
    are tinted while nothing is selected; once a selection exists only the active chip keeps its color.
    """

    def __init__(self, text, icon_name, accent, count, themes, active, dimmed, parent=None):
        QtWidgets.QAbstractButton.__init__(self, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setCheckable(True)
        self.setChecked(active)
        self.setText(text)
        self._icon_name = icon_name
        self._count = count
        self._themes = themes
        self._accent = QtGui.QColor(accent) if QtGui.QColor(accent).isValid() else QtGui.QColor("#3280dd")
        self._dimmed = dimmed
        font = QtGui.QFont(self.font())
        font.setPixelSize(12)
        self.setFont(font)
        self._small = QtGui.QFont(font)
        self._small.setPixelSize(10)
        self.setAttribute(Qt.WA_Hover)

    def _count_width(self):
        if self._count is None:
            return 0
        return max(18, QtGui.QFontMetrics(self._small).horizontalAdvance(str(self._count)) + 10)

    def sizeHint(self):
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        count = self._count_width()
        return QtCore.QSize(10 + 14 + 5 + text_width + (6 + count if count else 0) + 10, 32)

    def paintEvent(self, _event):
        theme = self._themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._dimmed:
            border = theme.color("textDisabled" if self.underMouse() else "borderStrong")
            fill = theme.color("surfaceRaised")
        else:
            border = self._accent
            fill = with_alpha(self._accent, 0.42 if self.underMouse() else 0.30)
        if self.isChecked() and not self._dimmed:
            glow = with_alpha(self._accent, 0.25)
            painter.setPen(QtGui.QPen(glow, 4))
            painter.setBrush(Qt.NoBrush)
            painter.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 15, 15)
        painter.setPen(QtGui.QPen(border, 1))
        painter.setBrush(fill)
        painter.drawRoundedRect(rect, 15.5, 15.5)
        text_color = QtGui.QColor("#ffffff") if not (self._dimmed and theme.is_light) else theme.color("textPrimary")
        if self._dimmed and not theme.is_light:
            text_color = theme.color("textSecondary")
        icon = icons.pixmap(self._icon_name, text_color, 14, self.devicePixelRatioF())
        painter.drawPixmap(10, (self.height() - 14) // 2, icon)
        painter.setPen(text_color)
        painter.setFont(self.font())
        text_width = self.fontMetrics().horizontalAdvance(self.text())
        painter.drawText(QtCore.QRect(29, 0, text_width + 2, self.height()), Qt.AlignVCenter | Qt.AlignLeft, self.text())
        count = self._count_width()
        if count:
            bubble = QtCore.QRectF(29 + text_width + 6, (self.height() - 16) / 2.0, count, 16)
            painter.setPen(QtGui.QPen(QtGui.QColor(255, 255, 255, 46), 1))
            painter.setBrush(QtGui.QColor(255, 255, 255, 31))
            painter.drawRoundedRect(bubble, 8, 8)
            painter.setFont(self._small)
            painter.setPen(text_color)
            painter.drawText(bubble, Qt.AlignCenter, str(self._count))
        painter.end()


class DiscoverPage(ScrollPage):
    def __init__(self, window, parent=None):
        ScrollPage.__init__(self, parent)
        self.manager_window = window
        self.runtime = window.runtime
        themes = window.themes
        self.pills = FlowRow(spacing=4, row_spacing=6)
        self.sidebar = QtWidgets.QFrame()
        self.sidebar.setObjectName("SidebarPanel")
        self.sidebar.setFixedWidth(314)
        self.sidebar_layout = vbox(spacing=4, margins=(10, 14, 10, 12))
        self.sidebar.setLayout(self.sidebar_layout)
        self.summary = label("", "Summary")
        self.grid = ResponsiveGrid(min_width=250, spacing=14, max_columns=4)
        self.previous = Button("Previous", "arrow-left", "default", themes)
        self.next = Button("Next", "arrow-right", "default", themes)
        self.page_label = label("", "Summary")
        self.pagination = QtWidgets.QWidget()
        self.pagination.setLayout(hbox(None, self.previous, self.page_label, self.next, None, spacing=14))
        self.previous.clicked.connect(lambda: self._go(-1))
        self.next.clicked.connect(lambda: self._go(1))
        self.state_host = QtWidgets.QWidget()
        self.state_host.setLayout(vbox(margins=(0, 40, 0, 0)))
        results = QtWidgets.QWidget()
        results.setLayout(vbox(self.summary, self.grid, self.pagination, self.state_host, None, spacing=12))
        body = hbox(spacing=16)
        body.addWidget(self.sidebar, 0, Qt.AlignTop)
        body.addWidget(results, 1)
        self.canvas_layout.addWidget(self.pills)
        self.canvas_layout.addLayout(body, 1)
        self.wide = True
        self._state = None
        self._shown = None

    def set_wide(self, wide):
        self.wide = wide
        self.sidebar.setVisible(wide and bool(self.runtime.catalog.categories))

    def refresh(self):
        catalog = self.runtime.catalog
        query = self.runtime.query
        self._build_pills()
        self._build_categories()
        self.set_wide(self.wide)
        if self._state is not None:
            self._state.hide()
            self._state.deleteLater()
            self._state = None
        page = catalog.page
        if not catalog.available and not catalog.loading:
            self._show_state("cloud-off", "Catalog unavailable", catalog.message or "Load the catalog to browse packages.",
                             "Retry", self.runtime.browse)
            self.grid.set_items([])
            self.summary.hide()
            self.pagination.hide()
            return
        if page is None:
            self._show_state("search", "Loading Discover...", "Preparing the package catalog.")
            self.summary.hide()
            self.pagination.hide()
            return
        installed = tuple(sorted(package.guid.lower() for package in self.runtime.packages))
        if self._shown != (id(page), installed):  # rebuild cards only for a new page or install state
            self._shown = (id(page), installed)
            self.grid.set_items([RemoteCard(package, self.manager_window) for package in page.packages])
        cards = self.grid.items()
        self.grid.setEnabled(not catalog.loading)
        selection = self._selection_name()
        if catalog.loading:
            self.summary.setText("Loading package catalog...")
            self.summary.show()
        elif cards:
            self.summary.setText("{} packages{}".format(page.total, " in " + selection if selection else ""))
            self.summary.show()
        else:
            self.summary.hide()
            self._show_state("search", "No packages found",
                             "This filter has no compatible packages." if selection else "Try a different search phrase.")
        multiple = page.total_pages > 1
        self.pagination.setVisible(multiple and bool(cards))
        self.previous.setEnabled(page.page > 1)
        self.next.setEnabled(page.page < page.total_pages)
        self.page_label.setText("Page {} of {}".format(page.page, page.total_pages))
        if query.page == 1:
            self.verticalScrollBar().setValue(0)

    def _show_state(self, icon_name, title, text, action="", callback=None):
        self._state = StatePanel(self.manager_window.themes, icon_name, title, text, action, "refresh-cw" if action else "")
        if callback is not None and self._state.action is not None:
            self._state.action.clicked.connect(lambda: callback())
        self.state_host.layout().addWidget(self._state, 0, Qt.AlignHCenter)

    def _selection_name(self):
        query = self.runtime.query
        if query.featured:
            return "Featured"
        for collection in self.runtime.catalog.collections:
            if collection.slug == query.collection:
                return collection.name
        for category in self.runtime.catalog.categories:
            if category.slug == query.category:
                return category.name
        return ""

    def _build_pills(self):
        catalog = self.runtime.catalog
        query = self.runtime.query
        self.pills.clear()
        if not catalog.collections_loaded:
            self.pills.hide()
            return
        self.pills.show()
        any_selected = query.featured or bool(query.collection)
        themes = self.manager_window.themes
        all_pill = CollectionPill("All packages", "package", "#3280dd", None, themes, not any_selected, any_selected)
        all_pill.clicked.connect(lambda: self.manager_window.select_collection("all"))
        self.pills.add(all_pill)
        featured = CollectionPill("Featured", "crown", "#eb8ccd", catalog.featured_count, themes, query.featured,
                                  any_selected and not query.featured)
        featured.clicked.connect(lambda: self.manager_window.select_collection("featured"))
        self.pills.add(featured)
        for collection in catalog.collections:
            active = query.collection == collection.slug
            pill = CollectionPill(collection.name, _safe_icon(collection.icon), collection.accent_color,
                                  collection.count, themes, active, any_selected and not active)
            pill.setToolTip(collection.description or collection.name)
            pill.clicked.connect(lambda _checked=False, slug=collection.slug: self.manager_window.select_collection(slug))
            self.pills.add(pill)

    def _build_categories(self):
        layout = self.sidebar_layout
        while layout.count():
            item = layout.takeAt(0)
            if item.widget() is not None:
                item.widget().hide()  # deleteLater alone leaves a ghost until the next event loop turn
                item.widget().deleteLater()
        layout.addWidget(label("CATEGORIES", "SidebarTitle"))
        layout.addSpacing(6)
        current = self.runtime.query.category if not (self.runtime.query.featured or self.runtime.query.collection) else None
        entries = [("", "All Categories", None)] + [(category.slug, category.name, category.count)
                                                    for category in self.runtime.catalog.categories]
        for slug, name, count in entries:
            button = CategoryButton(name, count, slug == current, self.manager_window.themes)
            button.clicked.connect(lambda _checked=False, value=slug: self.manager_window.select_category(value))
            layout.addWidget(button)

    def _go(self, delta):
        query = self.runtime.query.copy()
        query.page = max(1, query.page + delta)
        self.runtime.browse(query)


class CategoryButton(QtWidgets.QPushButton):
    """Sidebar category row: checkbox glyph, name and package count."""

    def __init__(self, name, count, checked, themes, parent=None):
        QtWidgets.QPushButton.__init__(self, parent)
        self.setObjectName("CategoryItem")
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self._themes = themes
        self._name = name
        self._count = count
        self.setMinimumHeight(36)

    def sizeHint(self):
        return QtCore.QSize(200, 36)

    def paintEvent(self, event):
        QtWidgets.QPushButton.paintEvent(self, event)
        theme = self._themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        box = QtCore.QRectF(10.5, (self.height() - 14) / 2.0, 14, 14)
        if self.isChecked():
            painter.setPen(Qt.NoPen)
            painter.setBrush(theme.color("selectionBlue"))
            painter.drawRoundedRect(box, 3, 3)
            pen = QtGui.QPen(theme.color("selectionBlueText"), 1.8)
            painter.setPen(pen)
            painter.drawPolyline(QtGui.QPolygonF([QtCore.QPointF(box.left() + 3, box.center().y()),
                                                  QtCore.QPointF(box.left() + 6, box.bottom() - 3.5),
                                                  QtCore.QPointF(box.right() - 3, box.top() + 3.5)]))
        else:
            painter.setPen(QtGui.QPen(theme.color("borderStrong"), 1))
            painter.setBrush(theme.color("surfaceDisabled"))
            painter.drawRoundedRect(box, 3, 3)
        painter.setPen(theme.color("textStrong" if self.isChecked() else "textSecondary"))
        text_rect = QtCore.QRect(34, 0, self.width() - 70, self.height())
        painter.drawText(text_rect, Qt.AlignVCenter | Qt.AlignLeft,
                         self.fontMetrics().elidedText(self._name, Qt.ElideRight, text_rect.width()))
        if self._count is not None:
            painter.setPen(theme.color("textMuted"))
            small = QtGui.QFont(self.font())
            small.setPixelSize(10)
            painter.setFont(small)
            painter.drawText(QtCore.QRect(0, 0, self.width() - 10, self.height()), Qt.AlignVCenter | Qt.AlignRight,
                             str(self._count))
        painter.end()


def _safe_icon(name):
    allowed = ("crown", "sparkles", "heart", "rocket", "medal", "tag", "package")
    lowered = (name or "").strip().lower()
    return lowered if lowered in allowed else "package"
