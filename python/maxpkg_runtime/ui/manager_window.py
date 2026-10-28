"""MaxPkg Manager window: header, tabs, filters, Discover/Installed/Details pages, status bar, overlays.

Layout, texts and responsive breakpoints follow the HTML Manager 1.2.0 (docs/ORIGINAL-SPEC.md).
"""

from ..qt_compat import QShortcut, QtCore, QtGui, QtWidgets, Qt, Signal, exec_menu, is_valid
from . import icons
from .details import SINGLE_COLUMN, DetailsPage
from .frame import EDGE, WindowChrome, bounded_position
from .pages import WIDE_DISCOVER, DiscoverPage, InstalledPage
from .settings_panel import SettingsPanel
from .widgets import (Button, ClearableDropdown, IconButton, IconLabel, SearchBox, add_action, hbox, label,
                      themed_menu, vbox)

MIN_WIDTH = 680
WINDOW_RADIUS = 10.0
HEADER_ICON_ONLY = 800  # 720 in the HTML Manager; the header now also holds the window buttons
DISCOVER_SORTS = (("popular", "Popular"), ("newest", "Newest"), ("rating", "Rating"), ("downloads", "Downloads"),
                  ("name", "Name"))
INSTALLED_SORTS = (("toolbar", "Toolbar order"), ("name", "Name"), ("developer", "Developer"), ("version", "Version"))
INSTALLED_FILTERS = (("all", "All"), ("toolbar", "In toolbar"), ("hidden", "Hidden"))


class TabButton(QtWidgets.QPushButton):
    def __init__(self, text, parent=None):
        QtWidgets.QPushButton.__init__(self, text, parent)
        self.setObjectName("TabButton")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.count = label("0", "TabCount", parent=self)
        self.count.setAlignment(Qt.AlignCenter)
        self._text = text

    def set_count(self, value):
        self.count.setVisible(value is not None)
        if value is not None:
            self.count.setText(str(value))
            self.count.adjustSize()
        self.setText(self._text + ("     " + " " * len(str(value)) if value is not None else ""))
        self._place()

    def _place(self):
        metrics = self.fontMetrics()
        x = 18 + metrics.horizontalAdvance(self._text) + 6
        self.count.move(x, (self.height() - self.count.height()) // 2)

    def resizeEvent(self, event):
        QtWidgets.QPushButton.resizeEvent(self, event)
        self._place()


class Toast(QtWidgets.QFrame):
    def __init__(self, text, kind, themes, parent):
        QtWidgets.QFrame.__init__(self, parent)
        self.setObjectName("Toast")
        self.setProperty("kind", kind)
        icon_name = {"success": "circle-check", "error": "circle-x", "warning": "info"}.get(kind, "info")
        token = {"success": "iconSuccess", "error": "iconDanger", "warning": "iconWarning"}.get(kind, "iconAccent")
        glyph = IconLabel(icon_name, themes, token, 20)
        message = label(text, "ToastText", wrap=True)
        self.setLayout(hbox(glyph, message, spacing=12, margins=(14, 12, 14, 12)))
        self.layout().setStretch(1, 1)
        self.setFixedWidth(330)
        QtCore.QTimer.singleShot(5200 if kind != "error" else 8000, self._expire)

    def _expire(self):
        if is_valid(self):
            parent = self.parentWidget()
            self.hide()
            self.deleteLater()
            if parent is not None and hasattr(parent, "place_toasts"):
                QtCore.QTimer.singleShot(0, parent.place_toasts)

    def mousePressEvent(self, event):
        self._expire()


class ScreenshotPreview(QtWidgets.QWidget):
    """Full-window screenshot viewer with previous/next and close (Esc)."""

    def __init__(self, window, shots, index):
        QtWidgets.QWidget.__init__(self, window)
        self.setObjectName("BusyShade")
        self.setAttribute(Qt.WA_StyledBackground)
        self.manager_window = window
        self.shots = shots
        self.index = index
        self.image = QtWidgets.QLabel(self)
        self.image.setAlignment(Qt.AlignCenter)
        self.caption = label("", "ToastText", parent=self)
        self.caption.setAlignment(Qt.AlignCenter)
        self.buttons = []
        for icon_name, step in (("gallery-chevron-left", -1), ("gallery-chevron-right", 1), ("x", 0)):
            button = QtWidgets.QPushButton(self)
            button.setObjectName("GalleryNav")
            button.setCursor(Qt.PointingHandCursor)
            window.themes.bind_icon(button, icon_name, "textStrong", 20)
            button.clicked.connect(lambda _checked=False, delta=step: self._step(delta))
            self.buttons.append(button)
        window.images.ready.connect(lambda _source: self._paint())
        self.setFocusPolicy(Qt.StrongFocus)
        self.setGeometry(window.content_rect())
        self.show()
        self.raise_()
        self.setFocus()
        self._paint()

    def _step(self, delta):
        if delta == 0:
            self.hide()
            self.deleteLater()
            return
        self.index = (self.index + delta) % len(self.shots)
        self._paint()

    def keyPressEvent(self, event):
        key = event.key()
        if key == Qt.Key_Escape:
            self._step(0)
        elif key == Qt.Key_Left:
            self._step(-1)
        elif key == Qt.Key_Right:
            self._step(1)

    def _paint(self):
        if not is_valid(self):
            return
        shot = self.shots[self.index]
        pixmap = self.manager_window.images.get(shot.url)
        area = self.rect().adjusted(70, 40, -70, -80)
        self.image.setGeometry(area)
        if pixmap is not None:
            dpr = self.devicePixelRatioF()
            scaled = pixmap.scaled(int(area.width() * dpr), int(area.height() * dpr), Qt.KeepAspectRatio,
                                   Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self.image.setPixmap(scaled)
        self.caption.setText("<b>{}</b><br>{}".format(shot.title, shot.caption))
        self.caption.setGeometry(70, self.height() - 74, self.width() - 140, 60)
        middle = self.height() // 2 - 18
        self.buttons[0].move(18, middle)
        self.buttons[1].move(self.width() - 54, middle)
        self.buttons[2].move(self.width() - 54, 14)

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._paint()


class ManagerWindow(QtWidgets.QWidget):
    closed = Signal()

    def __init__(self, runtime, themes, images, toolbar, parent=None):
        QtWidgets.QWidget.__init__(self, parent, Qt.Window | Qt.FramelessWindowHint)
        self.setObjectName("ManagerRoot")
        self.setWindowTitle("MaxPkg Manager")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_TranslucentBackground)  # rounded corners are painted in paintEvent
        self.runtime = runtime
        self.themes = themes
        self.images = images
        self.toolbar = toolbar
        self.tab = "discover"
        self._before_details = "discover"
        self._toasts = []
        self._search_timer = QtCore.QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(350)
        self._search_timer.timeout.connect(self._run_discover_search)
        self._geometry_timer = QtCore.QTimer(self)  # moves/resizes are saved shortly after they stop
        self._geometry_timer.setSingleShot(True)
        self._geometry_timer.setInterval(600)
        self._geometry_timer.timeout.connect(self.save_geometry)
        self._restoring = True
        self.setMinimumSize(MIN_WIDTH, 480)
        settings = runtime.settings
        self.chrome = WindowChrome(self, "MaxPkg Manager " + runtime.version, themes,
                                   QtCore.QPoint(settings.manager_mini_x, settings.manager_mini_y),
                                   self._remember_mini_position)
        self._build()
        self._connect()
        self.apply_theme()
        self._restore_geometry()
        self._restoring = False

    # --- construction ---------------------------------------------------------------
    def _build(self):
        themes = self.themes
        header = QtWidgets.QFrame()
        header.setObjectName("Header")
        header.setFixedHeight(68)
        brand = QtWidgets.QLabel()
        brand.setObjectName("BrandMark")
        brand.setAlignment(Qt.AlignCenter)
        themes.bind_icon(brand, "maxpkg-logo", "brandIcon", 24)
        self.version_label = label("Runtime " + self.runtime.version, "BrandSubtitle")
        brand_text = vbox(label("maxpkg", "BrandTitle"), self.version_label, spacing=0, margins=(0, 2, 0, 2))
        self.configurator_button = Button("Toolbar Configurator", "panel-top", "default", themes)
        self.check_button = Button("Check Updates", "refresh-cw", "default", themes)
        self.update_all_button = Button("Update All", "download", "primary", themes)
        self.settings_button = IconButton("settings", "Settings", themes)
        self._header_buttons = (self.configurator_button, self.check_button, self.update_all_button)
        brand_block = QtWidgets.QWidget()
        brand_block.setAttribute(Qt.WA_TransparentForMouseEvents)  # drags on the brand move the window
        brand_block.setLayout(hbox(brand, brand_text, spacing=9))
        # The original header is also the window's title bar (own chrome): drag to move, double-click to
        # maximise, collapse and close at the right end after a thin divider.
        divider = QtWidgets.QFrame()
        divider.setObjectName("HeaderDivider")
        divider.setFixedSize(1, 24)
        chrome_buttons = self.chrome.window_buttons("Close MaxPkg Manager")
        header.setLayout(hbox(brand_block, None, self.configurator_button, self.check_button,
                              self.update_all_button, self.settings_button, 4, divider, 4, *chrome_buttons,
                              spacing=12, margins=(15, 13, 10, 13)))
        self.chrome.attach_title_bar(header)

        tabs = QtWidgets.QFrame()
        tabs.setObjectName("TabBar")
        tabs.setFixedHeight(43)
        self.tab_buttons = {"discover": TabButton("Discover"), "installed": TabButton("Installed"),
                            "updates": TabButton("Updates")}
        tabs.setLayout(hbox(self.tab_buttons["discover"], self.tab_buttons["installed"], self.tab_buttons["updates"],
                            None, spacing=0, margins=(15, 0, 15, 0)))

        self.page_toolbar = QtWidgets.QFrame()
        self.page_toolbar.setObjectName("PageToolbar")
        self.page_toolbar.setFixedHeight(48)
        self.search = SearchBox(themes, "Search Discover")
        self.category = ClearableDropdown(themes, [("", "All Categories")], "", "Filter Discover by category")
        self.discover_sort = ClearableDropdown(themes, DISCOVER_SORTS, "popular", "Sort Discover packages")
        self.installed_filter = ClearableDropdown(themes, INSTALLED_FILTERS, "all", "Filter installed packages")
        self.installed_sort = ClearableDropdown(themes, INSTALLED_SORTS, "toolbar", "Sort installed packages")
        for control in (self.category, self.discover_sort, self.installed_filter, self.installed_sort):
            control.dropdown.setMinimumWidth(150)
        self.category.dropdown.setMinimumWidth(190)
        self.page_toolbar.setLayout(hbox(self.search, self.category, self.discover_sort, self.installed_filter,
                                         self.installed_sort, spacing=10, margins=(16, 7, 16, 7)))
        self.page_toolbar.layout().setStretch(0, 1)

        self.details_nav = QtWidgets.QFrame()
        self.details_nav.setObjectName("DetailsNavigation")
        self.details_nav.setFixedHeight(48)
        back = QtWidgets.QPushButton("Back")
        back.setObjectName("TextLink")
        back.setCursor(Qt.PointingHandCursor)
        themes.bind_icon(back, "breadcrumb-arrow-left", "iconMuted", 14)
        back.clicked.connect(self.details_back)
        self.path_root = label("Installed", "Breadcrumb")
        self.path_name = label("Package", "BreadcrumbCurrent")
        self.details_nav.setLayout(hbox(back, label("/", "Breadcrumb"), self.path_root, label("/", "Breadcrumb"),
                                        self.path_name, None, spacing=8, margins=(16, 0, 16, 0)))

        self.stack = QtWidgets.QStackedWidget()
        self.discover_page = DiscoverPage(self)
        self.installed_page = InstalledPage(self)
        self.details_page = DetailsPage(self)
        for page in (self.discover_page, self.installed_page, self.details_page):
            self.stack.addWidget(page)

        status = QtWidgets.QFrame()
        status.setObjectName("StatusBar")
        status.setFixedHeight(28)
        self.package_status = label("0 packages")
        self.update_status = label("0 updates")
        self.website = QtWidgets.QPushButton("maxpkg.dev")
        self.website.setObjectName("StatusLink")
        self.website.setCursor(Qt.PointingHandCursor)
        self.website.setToolTip("Open maxpkg.dev in your browser")
        self.website.setLayoutDirection(Qt.RightToLeft)
        themes.bind_icon(self.website, "external-link", "successText", 11)
        self.footer_version = label("Runtime " + self.runtime.version)
        self.connection_status = label("Offline")
        status.setLayout(hbox(self.package_status, 12, self.update_status, None, self.website, None,
                              self.footer_version, 14, self.connection_status, spacing=0, margins=(14, 0, 14, 0)))

        self.content = QtWidgets.QWidget()
        content_layout = vbox(header, tabs, self.page_toolbar, self.details_nav, self.stack, status, spacing=0)
        content_layout.setStretch(4, 1)
        self.content.setLayout(content_layout)
        root = vbox(self.chrome.mini_bar, self.content, spacing=0, margins=(EDGE, EDGE, EDGE, EDGE))
        root.setStretch(1, 1)
        self.setLayout(root)
        self.details_nav.hide()

        self.busy = QtWidgets.QWidget(self)
        self.busy.setObjectName("BusyShade")
        self.busy.setAttribute(Qt.WA_StyledBackground)
        self.busy_message = label("Working...", "BusyMessage", parent=self.busy)
        self.busy_message.setAlignment(Qt.AlignCenter)
        self.busy_message.setFixedWidth(240)
        self.busy.hide()
        self.settings_panel = SettingsPanel(self, self)
        self.settings_panel.uninstall_requested.connect(self._runtime_uninstall)

    def _connect(self):
        runtime = self.runtime
        for key, button in self.tab_buttons.items():
            button.clicked.connect(lambda _checked=False, tab=key: self.show_tab(tab))
        self.configurator_button.clicked.connect(lambda: self.open_settings("toolbar"))
        self.settings_button.clicked.connect(lambda: self.open_settings(""))  # reopens the last page
        self.check_button.clicked.connect(lambda: runtime.check_updates(True))
        self.update_all_button.clicked.connect(runtime.update_all)
        self.website.clicked.connect(lambda: runtime.open_link(_SITE, "homepage"))
        self.search.textChanged.connect(self._on_search)
        self.search.returnPressed.connect(self._run_discover_search)
        self.category.changed.connect(self.select_category)
        self.discover_sort.changed.connect(self._on_discover_sort)
        self.installed_filter.changed.connect(lambda value: self._set_manager("manager_filter", value))
        self.installed_sort.changed.connect(lambda value: self._set_manager("manager_sort", value))
        runtime.packages_changed.connect(self._on_packages)
        runtime.catalog_changed.connect(self._on_catalog)
        runtime.busy_changed.connect(self._on_busy)
        runtime.notify.connect(self.notify)
        runtime.settings_changed.connect(self._on_settings)
        runtime.updates_checking_changed.connect(self._on_checking)
        self.themes.manager_changed.connect(self.apply_theme)
        # Keyboard: Ctrl+F search, Esc back from Details, F5 refresh, Ctrl+1..3 tabs, Ctrl+, Settings.
        shortcuts = (("Ctrl+F", self._focus_search), ("Escape", self._escape), ("F5", self.refresh_all),
                     ("Ctrl+1", lambda: self.show_tab("discover")), ("Ctrl+2", lambda: self.show_tab("installed")),
                     ("Ctrl+3", lambda: self.show_tab("updates")), ("Ctrl+,", lambda: self.open_settings("")))
        for sequence, slot in shortcuts:
            shortcut = QShortcut(QtGui.QKeySequence(sequence), self)
            shortcut.setContext(Qt.WindowShortcut)
            shortcut.activated.connect(slot)

    def _focus_search(self):
        if self.tab == "details":
            self.details_back()
        self.search.setFocus()
        self.search.selectAll()

    def _escape(self):
        if self.tab == "details":
            self.details_back()
        elif self.search.hasFocus() and self.search.text():
            self.search.clear()

    def refresh_all(self):
        self.runtime.scan()
        self.runtime.load_collections()
        self.runtime.browse()
        self.images.retry_failed()

    def disconnect_all(self):
        """Detach from long-lived Runtime signals before the window is deleted."""
        runtime = self.runtime
        pairs = ((runtime.packages_changed, self._on_packages), (runtime.catalog_changed, self._on_catalog),
                 (runtime.busy_changed, self._on_busy), (runtime.notify, self.notify),
                 (runtime.settings_changed, self._on_settings), (runtime.updates_checking_changed, self._on_checking),
                 (self.themes.manager_changed, self.apply_theme),
                 (runtime.settings_changed, self.settings_panel._on_settings_changed),
                 (runtime.details_changed, self.details_page._on_details))
        for signal, slot in pairs:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass

    # --- lifecycle ------------------------------------------------------------------
    def start(self, tab="", settings_page=""):
        self.installed_filter.set_value(self.runtime.settings.manager_filter)
        self.installed_sort.set_value(self.runtime.settings.manager_sort)
        self._on_packages()
        self.runtime.load_collections()
        self.runtime.browse()
        self.show_tab(tab or self.runtime.settings.manager_last_tab or "installed")
        self.content.setFocusPolicy(Qt.StrongFocus)  # no header button shows a focus ring on open
        self.content.setFocus()
        if settings_page:
            self.open_settings(settings_page)

    def _restore_geometry(self):
        """Last size and place (Manager.PositionX/Y, Width, Height, Maximized). A place that is no longer on
        any screen (monitor unplugged, resolution changed) falls back to the centre of 3ds Max."""
        settings = self.runtime.settings
        available = QtWidgets.QApplication.primaryScreen().availableGeometry()
        width = min(max(MIN_WIDTH, settings.manager_width), available.width())
        height = min(max(480, settings.manager_height), available.height())
        self.resize(width, height)
        x, y = settings.manager_position_x, settings.manager_position_y
        title_point = QtCore.QPoint(x + min(120, width // 2), y + 12)  # the title bar must stay reachable
        if x != -1 and y != -1 and QtWidgets.QApplication.screenAt(title_point) is not None:
            self.move(bounded_position(QtCore.QPoint(x, y), self.size(), title_point))
        else:
            parent = self.parentWidget()
            center = parent.frameGeometry().center() if parent is not None else available.center()
            self.move(bounded_position(QtCore.QPoint(center.x() - width // 2, center.y() - height // 2), self.size()))
        self._restore_maximized = settings.manager_maximized

    def show_restored(self):
        """First show: maximised again when it was left maximised."""
        if getattr(self, "_restore_maximized", False):
            self.showMaximized()
        else:
            self.show()

    def save_geometry(self):
        """Persist place, size, maximised state and tab. While collapsed the expanded geometry is saved."""
        if self._restoring:
            return
        self._geometry_timer.stop()
        settings = self.runtime.settings
        if self.chrome.collapsed:
            geometry = self.chrome._mini[0]
        elif self.isMaximized():
            geometry = self.normalGeometry()
        else:
            geometry = self.geometry()
        if geometry.width() >= MIN_WIDTH:
            settings.manager_position_x, settings.manager_position_y = geometry.x(), geometry.y()
            settings.manager_width, settings.manager_height = geometry.width(), geometry.height()
        settings.manager_maximized = self.isMaximized() and not self.chrome.collapsed
        settings.manager_last_tab = self.tab if self.tab != "details" else self._before_details
        self.runtime.save_settings("manager-geometry")

    def _remember_mini_position(self, point):
        settings = self.runtime.settings
        settings.manager_mini_x, settings.manager_mini_y = point.x(), point.y()
        self.runtime.save_settings("manager-geometry")

    def _schedule_geometry_save(self):
        if not self._restoring and not self.chrome.collapsed and self.isVisible():
            self._geometry_timer.start()

    def chrome_parts(self):
        return [self.content]

    def before_collapse(self):
        if self.settings_panel.isVisible():
            self.settings_panel.close_panel()

    def content_rect(self):
        return self.content.geometry()

    def closeEvent(self, event):
        self.save_geometry()
        self.chrome.stop()
        QtWidgets.QWidget.closeEvent(self, event)
        self.closed.emit()

    def moveEvent(self, event):
        QtWidgets.QWidget.moveEvent(self, event)
        self._schedule_geometry_save()

    def changeEvent(self, event):
        QtWidgets.QWidget.changeEvent(self, event)
        if event.type() == QtCore.QEvent.WindowStateChange:
            self._schedule_geometry_save()

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def leaveEvent(self, event):
        if self.chrome._resizing is None:
            self.unsetCursor()
        QtWidgets.QWidget.leaveEvent(self, event)

    # --- painting ------------------------------------------------------------------
    def paintEvent(self, _event):
        """Rounded window (square while maximised): the top level is translucent, we paint the shape."""
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        radius = 0.0 if self.isMaximized() else WINDOW_RADIUS
        shape = QtCore.QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        gradient = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, theme.color("backgroundGradientTop"))
        gradient.setColorAt(0.48, theme.color("surfaceSecondary"))
        gradient.setColorAt(1.0, theme.color("backgroundGradientBottom"))
        painter.setPen(QtGui.QPen(theme.color("borderStrong"), 1))
        painter.setBrush(QtGui.QBrush(gradient))
        painter.drawRoundedRect(shape, radius, radius)
        painter.end()

    def apply_theme(self):
        self.setStyleSheet(self.themes.qss())
        self.update()
        if self.isVisible():
            self.refresh_pages()

    # --- tabs and pages -------------------------------------------------------------
    def show_tab(self, tab):
        if tab not in ("discover", "installed", "updates"):
            tab = "installed"
        self.tab = tab
        for key, button in self.tab_buttons.items():
            button.setChecked(key == tab)
        self.details_nav.hide()
        self.page_toolbar.show()
        discover = tab == "discover"
        self.search.setPlaceholderText("Search Discover" if discover else "Search installed packages")
        self.search.blockSignals(True)
        self.search.setText(self.runtime.query.text if discover else self.installed_page.search)
        self.search.blockSignals(False)
        self._update_tools()
        if discover:
            self.stack.setCurrentWidget(self.discover_page)
            self.discover_page.refresh()
        else:
            self.installed_page.view = tab
            self.stack.setCurrentWidget(self.installed_page)
            self.installed_page.refresh()

    def _update_tools(self):
        discover = self.tab == "discover"
        wide = self.width() >= WIDE_DISCOVER
        has_categories = bool(self.runtime.catalog.categories)
        self.category.setVisible(discover and not wide and has_categories)
        self.discover_sort.setVisible(discover)
        self.installed_filter.setVisible(not discover)
        self.installed_sort.setVisible(not discover and self.tab != "updates")

    def refresh_pages(self):
        current = self.stack.currentWidget()
        if current is self.discover_page:
            self.discover_page.refresh()
        elif current is self.installed_page:
            self.installed_page.refresh()
        elif current is self.details_page:
            self.details_page.refresh()

    def open_details(self, guid):
        if self.tab != "details":
            self._before_details = self.tab
        self.tab = "details"
        self.page_toolbar.hide()
        self.details_nav.show()
        self.stack.setCurrentWidget(self.details_page)
        self.details_page.set_single_column(self.width() < SINGLE_COLUMN)
        self.details_page.show_package(guid)

    def set_details_path(self, package):
        installed = self.runtime.package(package.guid) is not None and self._before_details != "discover"
        self.path_root.setText("Installed" if installed else "Discover")
        self.path_name.setText(package.display_name)

    def details_back(self):
        self.show_tab(self._before_details)

    def open_settings(self, page=""):
        self.settings_panel.open_page(page)

    # --- actions used by cards/pages ------------------------------------------------
    def run(self, guid):
        self.runtime.run(guid)

    def install(self, guid):
        self.runtime.install(guid)

    def update_package(self, guid):
        self.runtime.update(guid)

    def uninstall(self, guid):
        package = self.runtime.package(guid)
        if package is None:
            return
        answer = QtWidgets.QMessageBox.question(self, "MaxPkg", "Uninstall {}?".format(package.display_name),
                                                QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No,
                                                QtWidgets.QMessageBox.No)
        if answer == QtWidgets.QMessageBox.Yes and self.runtime.uninstall(guid) and self.tab == "details":
            self.details_back()

    def package_menu(self, guid, anchor):
        package = self.runtime.package(guid)
        if package is None:
            return
        developer = self.runtime.settings.developer_mode
        menu = themed_menu(self)
        add_action(menu, "Run", lambda: self.run(guid))
        if self.tab == "updates" and package.update_available:
            add_action(menu, "Update to " + package.latest_version, lambda: self.update_package(guid))
        add_action(menu, "Details", lambda: self.open_details(guid))
        if developer:
            add_action(menu, "Open Folder", lambda: self.runtime.open_folder(guid))
        if package.documentation_url:
            add_action(menu, "Help", lambda: self.runtime.open_link(package, "documentation"))
        on_toolbar = self.runtime.is_on_toolbar(package)
        add_action(menu, "Hide from Toolbar" if on_toolbar else "Show in Toolbar",
                   lambda: self.runtime.set_toolbar_visible(guid, not on_toolbar))
        if developer:
            menu.addSeparator()
            add_action(menu, "Copy GUID", lambda: self.copy_text(package.guid, "GUID copied."))
            add_action(menu, "Copy Path", lambda: self.copy_text(package.install_path, "Path copied."))
        menu.addSeparator()
        add_action(menu, "Uninstall", lambda: self.uninstall(guid), self.themes, "trash-2", "iconDanger")
        exec_menu(menu, anchor.mapToGlobal(QtCore.QPoint(0, anchor.height() + 4)))
        menu.deleteLater()

    def copy_text(self, text, message):
        QtWidgets.QApplication.clipboard().setText(text)
        self.notify(message, "success")

    def preview_screenshots(self, shots, index):
        if shots:
            ScreenshotPreview(self, shots, index)

    def reset_toolbar_position(self):
        if self.toolbar is not None:
            self.toolbar.reset_floating_position()

    def select_collection(self, value):
        query = self.runtime.query.copy()
        query.page = 1
        query.featured = value == "featured"
        query.collection = "" if value in ("all", "featured") else value
        query.category = ""
        self.category.set_value("")
        self.runtime.browse(query)

    def select_category(self, slug):
        query = self.runtime.query.copy()
        query.page = 1
        query.category = slug or ""
        query.featured = False
        query.collection = ""
        self.category.set_value(query.category)
        self.runtime.browse(query)

    def _on_discover_sort(self, value):
        query = self.runtime.query.copy()
        query.sort = value or "popular"
        query.page = 1
        self.runtime.browse(query)

    def _on_search(self, text):
        if self.tab == "discover":
            self._search_timer.start()
        else:
            self.installed_page.search = text.strip()
            self.installed_page.refresh()

    def _run_discover_search(self):
        if self.tab != "discover":
            return
        query = self.runtime.query.copy()
        if query.text == self.search.text().strip():
            return
        query.text = self.search.text().strip()
        query.page = 1
        self.runtime.browse(query)

    def _set_manager(self, attribute, value):
        setattr(self.runtime.settings, attribute, value)
        self.runtime.save_settings("manager")
        if self.tab in ("installed", "updates"):
            self.installed_page.refresh()

    def _runtime_uninstall(self):
        self.notify("Removing MaxPkg Runtime is not available in this preview build. Use the MaxScript Runtime "
                    "(Settings > Uninstall) until the Qt Runtime replaces it.", "warning")

    # --- runtime -> view ----------------------------------------------------------------
    def _on_packages(self):
        runtime = self.runtime
        count = len(runtime.packages)
        updates = runtime.update_count()
        self.tab_buttons["installed"].set_count(count)
        self.tab_buttons["updates"].set_count(updates)
        self.package_status.setText("{} package{}".format(count, "" if count == 1 else "s"))
        self.update_status.setText("{} update{}".format(updates, "" if updates == 1 else "s"))
        self.update_all_button.setVisible(updates > 0)
        if self.tab in ("installed", "updates"):
            self.installed_page.refresh()
        elif self.tab == "discover":
            self.discover_page.refresh()
        elif self.tab == "details":
            self.details_page.refresh()

    def _on_catalog(self):
        catalog = self.runtime.catalog
        total = catalog.total_packages
        self.tab_buttons["discover"].set_count(total if total >= 0 else None)
        choices = [("", "All Categories")] + [(category.slug, category.name) for category in catalog.categories]
        self.category.set_choices(choices)
        self.category.set_value(self.runtime.query.category if not (self.runtime.query.featured or
                                                                    self.runtime.query.collection) else "")
        online = self.runtime.connection == "online"
        self.connection_status.setText("Online" if online else ("Offline" if self.runtime.connection == "offline"
                                                                else ""))
        self.connection_status.setProperty("tone", "success" if online else "warning")
        self.connection_status.style().polish(self.connection_status)
        self._update_tools()
        # Catalog requests are asynchronous: Discover shows its own loading state and the rest of the window
        # stays usable (the HTML Manager blocked everything because its requests froze 3ds Max).
        if self.tab == "discover":
            self.discover_page.refresh()

    def _on_busy(self, message):
        if message:
            self._show_busy(message)
        else:
            self.busy.hide()

    def _on_checking(self, checking):
        self.check_button.set_label("Checking updates..." if checking else "Check Updates")
        self.check_button.setEnabled(not checking)

    def _on_settings(self, area):
        if area in ("cards", "manager", "toolbar"):
            if self.tab in ("installed", "updates"):
                self.installed_page.refresh()
        if area == "developer" and self.tab == "details":
            self.details_page.refresh()

    def _show_busy(self, message):
        self.busy_message.setText(message)
        self.busy.setGeometry(self.content_rect())
        self._place_busy()
        self.busy.show()
        self.busy.raise_()

    def _place_busy(self):
        self.busy_message.adjustSize()
        self.busy_message.move((self.busy.width() - self.busy_message.width()) // 2, int(self.busy.height() * 0.46))

    def notify(self, text, kind="info"):
        toast = Toast(text, kind, self.themes, self)
        toast.show()
        self._toasts = [item for item in self._toasts if is_valid(item) and item.isVisible()] + [toast]
        self.place_toasts()

    def place_toasts(self):
        area = self.content_rect()
        y = area.top() + 74
        alive = []
        for toast in self._toasts:
            if not is_valid(toast) or not toast.isVisible():
                continue
            toast.adjustSize()
            toast.move(area.right() - toast.width() - 14, y)
            toast.raise_()
            y += toast.height() + 8
            alive.append(toast)
        self._toasts = alive

    # --- responsive layout ----------------------------------------------------------
    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self._schedule_geometry_save()
        if self.chrome.collapsed:
            return
        width = self.width() - 2 * EDGE
        icon_only = width < HEADER_ICON_ONLY
        for button in self._header_buttons:
            button.set_icon_only(icon_only)
        wide = width >= WIDE_DISCOVER
        if self.discover_page.wide != wide:
            self.discover_page.set_wide(wide)
        self._update_tools()
        self.details_page.set_single_column(width < SINGLE_COLUMN)
        self.busy.setGeometry(self.content_rect())
        self._place_busy()
        for child in self.findChildren(ScreenshotPreview):
            child.setGeometry(self.content_rect())
        self.place_toasts()


class _Site:
    """Pseudo package so the footer link reuses Runtime.open_link."""

    homepage_url = "https://maxpkg.dev"
    documentation_url = support_url = purchase_url = license_url = ""
    slug = guid = ""


_SITE = _Site()

__all__ = ["ManagerWindow", "icons", "QtGui"]
