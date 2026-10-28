"""Package Details page: hero, purchase notice, Description/Screenshots/Changelog tabs, information table."""

from ..domain import markdown
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal
from ..services.images import rounded
from .cards import PackageIcon
from .pages import ScrollPage
from .widgets import Badge, Button, FlowRow, IconButton, IconLabel, hbox, label, vbox

SINGLE_COLUMN = 900

PURCHASE_COPY = {
    "donate": "This package is free. If it helps your work, consider donating to support the author and continued development.",
    "support": "This package is free. Support the author to help fund maintenance, improvements, and future releases.",
    "sponsor": "This package is free. Sponsor the author to help turn new ideas into updates and new tools.",
    "purchase": "Purchase this package directly from the author to unlock the tool and support its continued development.",
    "buy": "Buy this package directly from the author and support its continued development.",
}
LICENSE_COPY = "Get your license directly from the author and receive access according to the developer's terms."
DEFAULT_PURCHASE_COPY = ("Support this package directly through the author. Your contribution helps fund maintenance "
                         "and future updates.")
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


class ScreenshotViewer(QtWidgets.QWidget):
    """Large image with previous/next arrows, caption and a thumbnail strip; click opens the preview."""

    preview_requested = Signal(int)

    def __init__(self, shots, images, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.shots = shots
        self.images = images
        self.index = 0
        self.main = QtWidgets.QLabel()
        self.main.setObjectName("ScreenshotMain")
        self.main.setAlignment(Qt.AlignCenter)
        self.main.setMinimumHeight(260)
        self.main.setCursor(Qt.PointingHandCursor)
        self.main.mouseReleaseEvent = lambda _event: self.preview_requested.emit(self.index)
        self.left = QtWidgets.QPushButton(self.main)
        self.right = QtWidgets.QPushButton(self.main)
        for button, icon_name, step in ((self.left, "gallery-chevron-left", -1), (self.right, "gallery-chevron-right", 1)):
            button.setObjectName("GalleryNav")
            button.setCursor(Qt.PointingHandCursor)
            themes.bind_icon(button, icon_name, "textStrong", 18)
            button.clicked.connect(lambda _checked=False, delta=step: self.select(self.index + delta))
        self.title = label("", "ChangelogVersion")
        self.caption = label("", "Muted", wrap=True)
        self.thumbs = FlowRow(spacing=8)
        self._thumb_buttons = []
        for position, shot in enumerate(shots):
            button = QtWidgets.QPushButton()
            button.setObjectName("Thumb")
            button.setCheckable(True)
            button.setFixedSize(120, 72)
            button.setIconSize(QtCore.QSize(114, 66))
            button.setToolTip(shot.title)
            button.clicked.connect(lambda _checked=False, value=position: self.select(value))
            self._thumb_buttons.append(button)
            self.thumbs.add(button)
        self.setLayout(vbox(self.main, self.title, self.caption, self.thumbs, spacing=8))
        images.ready.connect(self._on_ready)
        self.select(0)

    def select(self, index):
        if not self.shots:
            return
        self.index = index % len(self.shots)
        shot = self.shots[self.index]
        self.title.setText(shot.title)
        self.caption.setText(shot.caption)
        self.caption.setVisible(bool(shot.caption))
        for position, button in enumerate(self._thumb_buttons):
            button.setChecked(position == self.index)
        self._paint()

    def _paint(self):
        shot = self.shots[self.index]
        pixmap = self.images.get(shot.url)
        if pixmap is not None:
            dpr = self.devicePixelRatioF()
            target = QtCore.QSize(int((self.main.width() - 4) * dpr), int(self.main.height() * dpr))
            scaled = pixmap.scaled(target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            scaled.setDevicePixelRatio(dpr)
            self.main.setPixmap(scaled)
        else:
            self.main.setText("Loading screenshot...")
        for position, button in enumerate(self._thumb_buttons):
            thumb = self.images.get(self.shots[position].thumbnail_url)
            if thumb is not None:
                button.setIcon(QtGui.QIcon(rounded(thumb, 114, 6, self.devicePixelRatioF()).scaled(
                    int(114 * self.devicePixelRatioF()), int(66 * self.devicePixelRatioF()),
                    Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)))

    def _on_ready(self, _source):
        self._paint()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        height = max(260, min(460, int(self.width() * 0.56)))
        self.main.setFixedHeight(height)
        self.left.move(10, height // 2 - 16)
        self.right.move(self.main.width() - 46, height // 2 - 16)
        self._paint()


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
            layout = hbox(spacing=16)
            layout.addWidget(main, 62)
            layout.addWidget(sidebar, 38, Qt.AlignTop)
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
        top = hbox(icon, vbox(name, by, badges, spacing=4), spacing=12)
        top.setStretch(1, 1)
        actions = FlowRow(spacing=12)
        if installed is None:
            install = Button("Install", "download", "primary", themes)
            install.clicked.connect(lambda: self.manager_window.install(package.guid))
            actions.add(install)
        else:
            run = Button("Run", "play", "primary", themes)
            run.clicked.connect(lambda: self.manager_window.run(package.guid))
            actions.add(run)
            if installed.update_available:
                update = Button("Update to " + installed.latest_version, "download", "success", themes)
                update.clicked.connect(lambda: self.manager_window.update_package(package.guid))
                actions.add(update)
            remove = Button("Uninstall", "trash-2", "danger", themes)
            remove.clicked.connect(lambda: self.manager_window.uninstall(package.guid))
            actions.add(remove)
        frame.setLayout(vbox(top, actions, spacing=12, margins=(12, 12, 12, 12)))
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
        copy = PURCHASE_COPY.get(lowered) or (LICENSE_COPY if "license" in lowered else DEFAULT_PURCHASE_COPY)
        heart = lowered in ("donate", "support", "sponsor")
        frame = QtWidgets.QFrame()
        frame.setObjectName("PurchaseNotice")
        badge = QtWidgets.QLabel()
        badge.setFixedSize(32, 32)
        badge.setAlignment(Qt.AlignCenter)
        badge.setStyleSheet("border: 1px solid " + _rgba(themes.color("warningBorder")) + "; border-radius: 8px;")
        themes.bind_icon(badge, "heart" if heart else "circle-dollar-sign", "iconWarning", 16)
        text = label(copy, "", wrap=True)
        button = Button(action_label, "heart-success" if heart else "shopping-cart", "installed", themes)
        button.clicked.connect(lambda: self.runtime.open_link(package, "purchase"))
        frame.setLayout(hbox(badge, text, button, spacing=12, margins=(12, 10, 12, 10)))
        frame.layout().setStretch(1, 1)
        return frame

    def _tabs(self, package):
        row = hbox(spacing=0)
        shots = len(package.screenshots)
        if self.tab == "screenshots" and not shots:
            self.tab = "description"
        tabs = [("description", "Description", None)]
        if shots:
            tabs.append(("screenshots", "Screenshots", shots))
        tabs.append(("changelog", "Changelog", len(package.changelog)))
        for key, text, count in tabs:
            button = QtWidgets.QPushButton(text)
            button.setObjectName("DetailsTab")
            button.setCheckable(True)
            button.setChecked(key == self.tab)
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _checked=False, value=key: self._select_tab(value))
            row.addWidget(button)
            if count is not None:
                counter = label(str(count), "DetailsTabCount")
                counter.setFixedHeight(16)
                counter.setAlignment(Qt.AlignCenter)
                row.addWidget(counter, 0, Qt.AlignVCenter)
                row.addSpacing(13)
        row.addStretch(1)
        return row

    def _select_tab(self, key):
        self.tab = key
        self.refresh()

    def _tab_panel(self, package):
        if self.tab == "screenshots":
            frame, layout = section("Screenshots")
            viewer = ScreenshotViewer(package.screenshots, self.manager_window.images, self.manager_window.themes)
            viewer.preview_requested.connect(lambda index: self.manager_window.preview_screenshots(package.screenshots, index))
            layout.addWidget(viewer)
            return frame
        if self.tab == "changelog":
            return self._changelog(package)
        holder = QtWidgets.QWidget()
        frame, layout = section("Description")
        browser = AutoHeightBrowser()
        html = markdown.to_html(package.full_description) if package.full_description else ""
        if not html:
            html = "<p>" + (package.description or "No description provided.") + "</p>"
        theme = self.manager_window.themes.manager
        browser.document().setDefaultStyleSheet(
            "p, li {{ line-height: 150%; color: {}; }} h3, h4, h5, h6 {{ color: {}; }} a {{ color: {}; }}"
            " code, pre {{ font-family: Consolas; color: {}; }}".format(
                theme.color("textSecondary").name(), theme.color("textStrong").name(),
                theme.color("accentHover").name(), theme.color("textPrimary").name()))
        browser.setHtml(html)
        layout.addWidget(browser)
        column = vbox(frame, spacing=12)
        links = self._links(package)
        if links is not None:
            column.addWidget(links)
        holder.setLayout(column)
        return holder

    def _links(self, package):
        themes = self.manager_window.themes
        row = FlowRow(spacing=12, row_spacing=10)
        if package.slug:
            copy = IconButton("copy", "Copy MaxPkg link", themes)
            copy.clicked.connect(lambda: self.manager_window.copy_text(self.runtime.link_url(package, "maxpkg"), "Link copied."))
            row.add(copy)
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
        layout.addWidget(row)
        return frame

    def _changelog(self, package):
        frame, layout = section("Full changelog")
        if not package.changelog:
            layout.addWidget(label("No changelog entries were provided with this package.", "Muted"))
            return frame
        groups = []
        for entry in package.changelog:
            key = (entry.version or package.version or "Unknown", entry.release_date or package.release_date)
            if not groups or groups[-1][0] != key:
                groups.append((key, []))
            groups[-1][1].append(entry)
        for (version, date), entries in groups:
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

    def _information(self, package):
        frame = QtWidgets.QFrame()
        frame.setObjectName("DetailsSection")
        layout = vbox(spacing=0, margins=(12, 12, 12, 8))
        layout.addWidget(label("PACKAGE INFORMATION", "SectionTitle"))
        layout.addSpacing(8)
        installed = self.runtime.package(package.guid)
        integration = "Toolbar" if installed is not None and self.runtime.is_on_toolbar(installed) else (
            "Package" if installed is None else "Hidden")
        packager = (package.packager_name + (" " + package.packager_version if package.packager_version else "")).strip()
        compatibility = (package.min_max_version + " and newer") if package.min_max_version else "Any version"
        rows = [("Version", package.version), ("Release date", package.release_date), ("3ds Max", compatibility),
                ("Author", package.developer), ("Type", package.runtime), ("Channel", package.release_channel),
                ("License", package.license_type), ("Integration", integration), ("Packager", packager)]
        identifier = package.slug or package.guid
        if identifier:
            layout.addWidget(self._info_row("Package ID", identifier, copy=True))
        for key, value in rows:
            if value:
                layout.addWidget(self._info_row(key, value))
        frame.setLayout(layout)
        return frame

    def _info_row(self, key, value, copy=False):
        row = QtWidgets.QFrame()
        row.setObjectName("InfoRow")
        value_label = label(value, "InfoValue")
        value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        value_label.setToolTip(value)
        layout = hbox(label(key, "InfoKey"), None, value_label, spacing=6, margins=(0, 8, 0, 8))
        if copy:
            button = IconButton("copy", "Copy Package ID", self.manager_window.themes)
            button.setFixedSize(26, 26)
            button.clicked.connect(lambda: self.manager_window.copy_text(value, "Package ID copied."))
            layout.addWidget(button)
        row.setLayout(layout)
        return row


def _rgba(color):
    return "rgba({}, {}, {}, {})".format(color.red(), color.green(), color.blue(), color.alpha())


__all__ = ["DetailsPage", "SINGLE_COLUMN", "IconLabel"]
