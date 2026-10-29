"""Settings modal (inside the Manager window, like the HTML version). Every change saves immediately."""

from ..domain.settings import normalize_endpoint
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, disable_max_accelerators
from .frame import (EDGE, WindowChrome, apply_native_frame, bounded_position, glass_border, native_event,
                    paint_window_shape, prepare_window)
from .toolbar import ToolbarPreview, ToolbarStyle
from .widgets import Button, Dropdown, IconLabel, Switch, hbox, label, vbox

PAGES = (("general", "General"), ("updates", "Updates"), ("toolbar", "Toolbar"), ("themes", "Themes"),
         ("developer", "Developer"), ("endpoint", "Endpoint"), ("about", "About"), ("uninstall", "Uninstall"))
FREQUENCIES = ((1, "Every hour"), (6, "Every 6 hours"), (12, "Every 12 hours"), (24, "Every day"),
               (48, "Every 2 days"), (168, "Every week"))
NARROW = 760
NAV_ICONS = {"general": "sliders-horizontal", "updates": "refresh-cw", "toolbar": "panel-top", "themes": "palette",
             "developer": "code", "endpoint": "globe", "about": "info", "uninstall": "trash-2"}


class Segments(QtWidgets.QWidget):
    """Row of exclusive segment buttons (Toolbar Configurator)."""

    changed = Signal(str)

    def __init__(self, options, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.buttons = {}
        layout = QtWidgets.QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)
        for value, text in options:
            button = QtWidgets.QPushButton(text)
            button.setObjectName("Segment")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, choice=value: self._choose(choice))
            layout.addWidget(button)
            self.buttons[value] = button
        layout.addStretch(1)
        self.setLayout(layout)

    def _choose(self, value):
        self.set_value(value)
        self.changed.emit(value)

    def set_value(self, value):
        for key, button in self.buttons.items():
            button.setChecked(key == value)


class SettingsPanel(QtWidgets.QWidget):
    """Floating Settings window (improvement over the HTML modal): it does not block the Manager, so the
    toolbar, cards and themes can be watched while settings change. It stays above the Manager, has the
    same own chrome (drag the title, resize by the edges, rounded corners) and remembers its place,
    size and last page. `open_page(name)` shows it; `closed` fires when the user closes it."""

    closed = Signal()
    uninstall_requested = Signal()

    def __init__(self, window, parent):
        QtWidgets.QWidget.__init__(self, parent)
        self.setObjectName("SettingsWindow")
        self.setWindowTitle("MaxPkg Settings")
        prepare_window(self)
        self.manager_window = window
        self.runtime = window.runtime
        self.themes = window.themes
        self.chrome = WindowChrome(self, "Settings", self.themes, collapsible=False, flags=Qt.Tool)
        self.setMinimumSize(560, 420)
        self.modal = QtWidgets.QFrame(self)
        self.modal.setObjectName("SettingsBody")
        header = QtWidgets.QFrame()
        header.setObjectName("ModalHeader")
        header.setFixedHeight(54)
        title_icon = IconLabel("settings", self.themes, "iconAccent", 18)
        title_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        title = label("Settings", "ModalTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        close = self.chrome.window_buttons("Close Settings")[0]
        header.setLayout(hbox(title_icon, title, None, close, spacing=10, margins=(16, 0, 10, 0)))
        self.chrome.attach_title_bar(header)
        outer = vbox(self.modal, margins=(EDGE, EDGE, EDGE, EDGE))
        self.setLayout(outer)
        navigation = QtWidgets.QFrame()
        navigation.setObjectName("SettingsNavigation")
        navigation.setFixedWidth(155)
        nav_layout = vbox(spacing=4, margins=(12, 12, 12, 12))
        self.nav_buttons = {}
        for key, text in PAGES:
            button = QtWidgets.QPushButton(text)
            button.setObjectName("SettingsNavButton")
            button.setCheckable(True)
            button.setCursor(Qt.PointingHandCursor)
            button.setIconSize(QtCore.QSize(15, 15))
            self.themes.bind_icon(button, NAV_ICONS[key], "iconDanger" if key == "uninstall" else "iconMuted", 15)
            if key == "uninstall":
                button.setProperty("danger", "true")
            button.clicked.connect(lambda _checked=False, page=key: self.show_page(page))
            nav_layout.addWidget(button)
            self.nav_buttons[key] = button
        nav_layout.addStretch(1)
        navigation.setLayout(nav_layout)
        self.stack = QtWidgets.QStackedWidget()
        self.pages = {}
        for key, _text in PAGES:
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.NoFrame)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
            content = QtWidgets.QWidget()
            content.setObjectName("PageCanvas")
            content.setLayout(vbox(spacing=12, margins=(18, 16, 18, 20)))
            scroll.setWidget(content)
            self.stack.addWidget(scroll)
            self.pages[key] = content.layout()
        body = hbox(navigation, self.stack, spacing=0)
        body.setStretch(1, 1)
        self.modal.setLayout(vbox(header, body, spacing=0))
        self._saving = False
        self._build()
        self.runtime.settings_changed.connect(self._on_settings_changed)
        self.hide()

    # --- shell ----------------------------------------------------------------------
    def open_page(self, page=""):
        self.refresh()
        settings = self.runtime.settings
        self.show_page(page if page in self.pages else (settings.settings_page or "general"))
        if not self.isVisible():
            self._place()
        self.show()
        self.raise_()
        self.activateWindow()

    def _place(self):
        """Last place and size; first time centred over the Manager (90% of its width like the old modal)."""
        settings = self.runtime.settings
        manager = self.manager_window.frameGeometry()
        width = settings.settings_width if settings.settings_width > 0 else min(1024, max(620, int(manager.width() * 0.9)))
        height = settings.settings_height if settings.settings_height > 0 else max(460, int(manager.height() * 0.85))
        self.resize(max(self.minimumWidth(), width), max(self.minimumHeight(), height))
        point = QtCore.QPoint(settings.settings_x, settings.settings_y)
        if settings.settings_x == -1 or QtWidgets.QApplication.screenAt(point + QtCore.QPoint(60, 12)) is None:
            point = manager.center() - QtCore.QPoint(self.width() // 2, self.height() // 2)
        self.move(bounded_position(point, self.size()))

    def _remember_geometry(self):
        if not self.isVisible():
            return
        settings = self.runtime.settings
        geometry = self.geometry()
        settings.settings_x, settings.settings_y = geometry.x(), geometry.y()
        settings.settings_width, settings.settings_height = geometry.width(), geometry.height()
        settings.settings_page = getattr(self, "current_page", "general")
        self.runtime.save_settings("settings-window")

    def close_panel(self):
        self._flush_endpoint()
        self._remember_geometry()
        self.hide()
        self.closed.emit()

    def closeEvent(self, event):
        event.ignore()  # Alt+F4 or the close button: hide, the window is reused
        self.close_panel()

    def show_page(self, page):
        if page == "endpoint" and not self.runtime.settings.developer_mode:
            page = "developer"
        for key, button in self.nav_buttons.items():
            button.setChecked(key == page)
        self.stack.setCurrentIndex([key for key, _ in PAGES].index(page))
        self.current_page = page

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        narrow = self.width() < NARROW
        for row in getattr(self, "_config_rows", []):
            row.setDirection(QtWidgets.QBoxLayout.TopToBottom if narrow else QtWidgets.QBoxLayout.LeftToRight)

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        paint_window_shape(self, painter, theme.color("surfacePrimary"), glass_border(theme.color("surfacePrimary")))
        painter.end()

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QWidget.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        apply_native_frame(self, glass_border(self.themes.color("surfacePrimary")))

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_panel()
            return
        QtWidgets.QWidget.keyPressEvent(self, event)

    # --- pages ----------------------------------------------------------------------
    def _switch(self, page, text, attribute, area="general", after=None):
        switch = Switch(text, self.themes)
        switch.toggled.connect(lambda checked: self._set(attribute, checked, area, after))
        self.pages[page].addWidget(switch)
        self._switches[attribute] = switch
        return switch

    def _set(self, attribute, value, area, after=None):
        if self._saving or getattr(self.runtime.settings, attribute) == value:
            return
        setattr(self.runtime.settings, attribute, value)
        self.runtime.save_settings(area)
        if after is not None:
            after()

    def _build(self):
        self._switches = {}
        themes = self.themes
        general = self.pages["general"]
        general.addWidget(label("General", "PageTitle"))
        general.addWidget(label("Language", "FieldLabel"))
        self.language = Dropdown(themes, [("English", "English")])
        self.language.setSizeAdjustPolicy(QtWidgets.QComboBox.AdjustToMinimumContentsLengthWithIcon)
        general.addWidget(self.language)
        self._switch("general", "Start Package Manager with 3ds Max", "auto_start")
        self._switch("general", "Open Manager on startup", "open_manager_on_startup")
        self._switch("general", "Show notifications", "notifications")
        self._switch("general", "Show full package cards in Installed views", "manager_full_cards", "cards")
        general.addStretch(1)

        updates = self.pages["updates"]
        updates.addWidget(label("Updates", "PageTitle"))
        self._switch("updates", "Check package updates automatically", "auto_check_packages", "updates")
        self._switch("updates", "Check Package Manager updates automatically", "auto_check_runtime", "updates")
        self._switch("updates", "Download updates automatically", "download_automatically", "updates")
        updates.addWidget(label("Check interval", "FieldLabel"))
        self.frequency = Dropdown(themes, [(hours, text) for hours, text in FREQUENCIES])
        self.frequency.currentIndexChanged.connect(
            lambda _index: self._set("update_frequency_hours", self.frequency.value(), "updates"))
        updates.addWidget(self.frequency)
        updates.addStretch(1)

        self._build_toolbar_page()

        page = self.pages["themes"]
        page.addWidget(label("Themes", "PageTitle"))
        page.addWidget(label("Choose independent themes for the Manager and the docked toolbar.", "Muted"))
        page.addWidget(label("Manager theme", "FieldLabel"))
        self.manager_theme = Dropdown(themes, themes.manager_choices())
        self.manager_theme.currentIndexChanged.connect(lambda _index: self._set_theme("manager", self.manager_theme.value()))
        page.addWidget(self.manager_theme)
        page.addWidget(label("Toolbar theme", "FieldLabel"))
        self.toolbar_theme = Dropdown(themes, themes.toolbar_choices())
        self.toolbar_theme.currentIndexChanged.connect(lambda _index: self._set_theme("toolbar", self.toolbar_theme.value()))
        page.addWidget(self.toolbar_theme)
        page.addStretch(1)

        page = self.pages["developer"]
        page.addWidget(label("Developer", "PageTitle"))
        self._switch("developer", "Enable developer mode", "developer_mode", "developer",
                     after=lambda: self.nav_buttons["endpoint"].setVisible(self.runtime.settings.developer_mode))
        self._switch("developer", "Enable debug logging", "debug_logging", "developer")
        page.addWidget(label("Developer settings affect Package Manager diagnostics only. Package manifests remain read-only.",
                             "Muted", wrap=True))
        page.addStretch(1)

        page = self.pages["endpoint"]
        page.addWidget(label("Endpoint", "PageTitle"))
        page.addWidget(label("Base endpoint", "FieldLabel"))
        self.endpoint = QtWidgets.QLineEdit()
        self.endpoint.setProperty("field", "true")
        self.endpoint.setPlaceholderText("https://maxpkg.dev/api/runtime/v1/")
        disable_max_accelerators(self.endpoint)
        self._endpoint_timer = QtCore.QTimer(self)
        self._endpoint_timer.setSingleShot(True)
        self._endpoint_timer.setInterval(600)
        self._endpoint_timer.timeout.connect(self._flush_endpoint)
        self.endpoint.textEdited.connect(lambda _text: self._endpoint_timer.start())
        page.addWidget(self.endpoint)
        page.addWidget(label("The configured override is shown here. Without one, the Package Manager uses its built-in production "
                             "endpoint. API action names such as updates and runtime are appended automatically.",
                             "Muted", wrap=True))
        page.addStretch(1)

        page = self.pages["about"]
        page.addWidget(label("About MaxPkg", "PageTitle"))
        self.about_version = label("", "")
        page.addWidget(self.about_version)
        page.addWidget(label("MaxPkg is a package ecosystem for Autodesk 3ds Max. It connects developers, the maxpkg.dev "
                             "catalog, and the Package Manager inside 3ds Max into one distribution workflow.", "", wrap=True))
        page.addWidget(label("Users can discover, install, run, update, and remove scripts in one place. Developers "
                             "build and publish versioned tools with MaxPkg Packager—eliminating scattered "
                             "installers, duplicate toolbar buttons, and inconsistent script versions across artists, "
                             "workstations, and studios.", "", wrap=True))
        copy = Button("Copy Package Manager info", "copy", "default", themes)
        copy.clicked.connect(self._copy_info)
        welcome = Button("Show welcome window", "sparkles", "default", themes)
        welcome.clicked.connect(lambda: getattr(self.manager_window, "show_welcome", lambda: None)())
        page.addLayout(hbox(copy, welcome, None, spacing=12))
        page.addStretch(1)

        self._build_uninstall_page()

    def _build_toolbar_page(self):
        themes = self.themes
        page = self.pages["toolbar"]
        heading = vbox(label("Toolbar", "PageTitle"), label("Choose where it lives and how much detail it shows.",
                                                             "Muted"), spacing=3)
        self.toolbar_visible = Switch("Show toolbar", themes)
        self.toolbar_visible.toggled.connect(lambda checked: self._set("toolbar_visible", checked, "toolbar"))
        self._switches["toolbar_visible"] = self.toolbar_visible
        page.addLayout(hbox(heading, None, self.toolbar_visible))
        preview_panel = QtWidgets.QFrame()
        preview_panel.setObjectName("PreviewPanel")
        self.preview_summary = label("", "Muted")
        self.preview = ToolbarPreview(self.runtime, themes)
        preview_panel.setLayout(vbox(hbox(label("Live preview", "ConfigLabel"), None, self.preview_summary),
                                     self.preview, spacing=9, margins=(12, 12, 12, 12)))
        page.addWidget(preview_panel)
        config = QtWidgets.QFrame()
        config.setObjectName("ConfigPanel")
        config_layout = vbox(spacing=6, margins=(12, 10, 12, 10))
        self._config_rows = []
        self.segments = {}
        rows = (
            ("position", "Position", "toolbar_dock_position",
             (("top", "Top"), ("bottom", "Bottom"), ("left", "Left"), ("right", "Right"),
              ("floatinghorizontal", "Floating Horizontal"), ("floatingvertical", "Floating Vertical"))),
            ("density", "Spacing", "toolbar_density", (("regular", "Regular"), ("compact", "Compact"))),
            ("icon", "Icon size", "toolbar_icon_size", (("small", "S"), ("medium", "M"), ("large", "L"))),
            ("width", "Button style", "toolbar_button_size",
             (("icon", "Icons only"), ("small", "Narrow"), ("medium", "Medium"), ("large", "Wide"))),
            ("subtitle", "Second line", "toolbar_subtitle_mode",
             (("none", "None"), ("version", "Version"), ("developer", "Developer"))),
        )
        for key, title, attribute, options in rows:
            segments = Segments(options)
            segments.changed.connect(lambda value, name=attribute: self._set(name, value, "toolbar"))
            title_label = label(title, "ConfigLabel")
            title_label.setFixedWidth(96)
            row = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight)
            row.setSpacing(8)
            row.addWidget(title_label, 0, Qt.AlignVCenter)
            row.addWidget(segments, 1)
            self._config_rows.append(row)
            config_layout.addLayout(row)
            self.segments[key] = segments
        self.compact_note = label("This position uses icon-only buttons. Your text settings stay saved.",
                                  "Muted", wrap=True)
        config_layout.addWidget(self.compact_note)
        config.setLayout(config_layout)
        page.addWidget(config)
        reset_order = Button("Reset package order", "", "default", themes)
        reset_order.clicked.connect(self._reset_order)
        self.reset_position = Button("Reset toolbar position", "", "default", themes)
        self.reset_position.clicked.connect(lambda: self.manager_window.reset_toolbar_position())
        reset_defaults = Button("Reset toolbar defaults", "", "default", themes)
        reset_defaults.clicked.connect(self._reset_toolbar)
        page.addLayout(hbox(None, reset_order, self.reset_position, reset_defaults, spacing=7))
        page.addStretch(1)

    def _build_uninstall_page(self):
        themes = self.themes
        page = self.pages["uninstall"]
        page.addWidget(label("Uninstall MaxPkg", "PageTitle"))
        page.addWidget(label("Remove the MaxPkg Package Manager, its toolbar, startup entry, settings, and local files "
                             "from this 3ds Max installation.", "", wrap=True))
        notice = QtWidgets.QFrame()
        notice.setObjectName("Notice")
        notice.setLayout(vbox(label("<b>Your scenes are safe.</b>", ""),
                              label("Uninstalling MaxPkg does not modify your .max scene files. You can install MaxPkg "
                                    "again at any time.", "", wrap=True), spacing=4, margins=(12, 10, 12, 10)))
        page.addWidget(notice)
        page.addWidget(label("1. Save your current work.<br>2. Click Uninstall MaxPkg and confirm the action.<br>"
                             "3. The Manager will close and a result window will appear when removal is finished.", "",
                             wrap=True))
        self.uninstall_button = Button("Uninstall MaxPkg", "trash-2", "danger", themes)
        page.addWidget(self.uninstall_button, 0, Qt.AlignLeft)
        self.confirmation = QtWidgets.QFrame()
        self.confirmation.setObjectName("DangerNotice")
        cancel = Button("Cancel", "", "default", themes)
        confirm = Button("Yes, uninstall MaxPkg", "trash-2", "danger", themes)
        self.confirmation.setLayout(vbox(label("<b>Uninstall MaxPkg now?</b>", ""),
                                         label("The Manager will close immediately. This action does not affect your "
                                               "scene files.", "", wrap=True),
                                         hbox(cancel, confirm, None, spacing=12), spacing=8, margins=(12, 12, 12, 12)))
        self.confirmation.hide()
        page.addWidget(self.confirmation)
        self.uninstall_button.clicked.connect(lambda: self.confirmation.show())
        cancel.clicked.connect(lambda: self.confirmation.hide())
        confirm.clicked.connect(self.uninstall_requested.emit)
        page.addStretch(1)

    # --- actions --------------------------------------------------------------------
    def _set_theme(self, kind, theme_id):
        if self._saving or theme_id is None:
            return
        if kind == "manager":
            self.runtime.settings.manager_theme = self.themes.set_manager(theme_id)
        else:
            self.runtime.settings.toolbar_theme = self.themes.set_toolbar(theme_id)
        self.runtime.save_settings("theme")

    def _flush_endpoint(self):
        if self._endpoint_timer.isActive():
            self._endpoint_timer.stop()
        value = normalize_endpoint(self.endpoint.text())
        if value != self.runtime.settings.api_endpoint and (value or not self.endpoint.text().strip()):
            self._set("api_endpoint", value, "endpoint")

    TOOLBAR_DEFAULTS = (("toolbar_visible", True), ("toolbar_title_mode", "packageName"),
                        ("toolbar_subtitle_mode", "version"), ("toolbar_button_size", "icon"),
                        ("toolbar_dock_position", "top"), ("toolbar_density", "regular"),
                        ("toolbar_icon_size", "large"), ("hidden_packages", []))

    def _reset_toolbar(self):
        settings = self.runtime.settings
        snapshot = {name: getattr(settings, name) for name, _value in self.TOOLBAR_DEFAULTS}
        snapshot["toolbar_order"] = list(settings.toolbar_order)
        for name, value in self.TOOLBAR_DEFAULTS:
            setattr(settings, name, list(value) if isinstance(value, list) else value)
        self.runtime.save_settings("toolbar")
        if self.runtime.reset_toolbar_order():
            self.manager_window.notify("The toolbar is back to its defaults.\nAll scripts are shown, in their "
                                       "original order, without dividers.", "success",
                                       action=("Undo", "undo-2", lambda: self._restore_toolbar(snapshot)))

    def _restore_toolbar(self, snapshot):
        settings = self.runtime.settings
        for name, value in snapshot.items():
            if name != "toolbar_order":
                setattr(settings, name, value)
        self.runtime.save_settings("toolbar")
        if self.runtime.set_full_order(snapshot["toolbar_order"]):
            self.manager_window.notify("Undone. Your toolbar settings are back.", "success")

    def _reset_order(self):
        snapshot = list(self.runtime.settings.toolbar_order)
        if self.runtime.reset_toolbar_order():
            self.manager_window.notify("The toolbar order is reset.\nScripts are back in their original order, "
                                       "without dividers.", "success",
                                       action=("Undo", "undo-2", lambda: self._restore_order(snapshot)))

    def _restore_order(self, snapshot):
        if self.runtime.set_full_order(snapshot):
            self.manager_window.notify("Undone. The toolbar order is back as it was.", "success")

    def _copy_info(self):
        from ..qt_compat import binding_info
        runtime = self.runtime
        text = "MaxPkg Package Manager {} ({})\n3ds Max {}\n{}\nPackages: {}\nSettings: {}".format(
            runtime.version, runtime.channel, runtime.max_year, binding_info(), len(runtime.packages),
            runtime.settings.path)
        self.manager_window.copy_text(text, "Package Manager info copied.")

    # --- state -> controls ----------------------------------------------------------
    def _on_settings_changed(self, area):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        settings = self.runtime.settings
        self._saving = True
        try:
            for attribute, switch in self._switches.items():
                switch.setChecked(bool(getattr(settings, attribute)))
            self.frequency.set_value(settings.update_frequency_hours)
            self.manager_theme.set_choices(self.themes.manager_choices(), self.themes.manager.id)
            self.toolbar_theme.set_choices(self.themes.toolbar_choices(), self.themes.toolbar.id)
            if not self.endpoint.hasFocus():
                self.endpoint.setText(settings.api_endpoint)
            self.nav_buttons["endpoint"].setVisible(settings.developer_mode)
            self.about_version.setText("Package Manager {} ({})".format(self.runtime.version, self.runtime.channel))
            values = {"position": settings.toolbar_dock_position, "density": settings.toolbar_density,
                      "icon": settings.toolbar_icon_size, "width": settings.toolbar_button_size,
                      "subtitle": settings.toolbar_subtitle_mode}
            for key, value in values.items():
                self.segments[key].set_value(value)
            style = ToolbarStyle(settings)
            forced_icons = style.vertical or style.floating
            for key in ("width", "subtitle"):
                self.segments[key].setEnabled(not forced_icons and not (key == "subtitle" and
                                                                        settings.toolbar_button_size == "icon"))
            self.compact_note.setVisible(forced_icons)
            self.reset_position.setVisible(style.floating)
            self.preview.refresh()
            self.preview_summary.setText(self._summary(settings, style))
        finally:
            self._saving = False

    def _summary(self, settings, style):
        names = {"top": "Top", "bottom": "Bottom", "left": "Left", "right": "Right",
                 "floatinghorizontal": "Floating Horizontal", "floatingvertical": "Floating Vertical"}
        parts = [names[settings.toolbar_dock_position], settings.toolbar_density.title(),
                 settings.toolbar_icon_size.title() + " icons"]
        if not style.icon_only:
            parts.append({"small": "Narrow", "medium": "Medium", "large": "Wide"}[settings.toolbar_button_size])
            parts.append({"none": "No second line", "version": "Version", "developer": "Developer"}[
                settings.toolbar_subtitle_mode])
        else:
            parts.append("Icons only")
        return " · ".join(parts)
