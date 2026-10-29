"""Package Details page: hero, purchase notice, Description/Screenshots/Changelog tabs, information table."""

from ..domain import markdown
from ..domain.packages import compact_number
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal
from ..services.images import rounded
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



class ScreenshotViewer(QtWidgets.QWidget):
    """Screenshot gallery: main image with round previous/next buttons and a 'n / N' counter, title and caption,
    and a thumbnail strip. A click on the image opens the full-window lightbox.

    compact=True is the side gallery of wide Details windows (above Package information): smaller image, one
    horizontally scrollable row of thumbnails, caption under the title.
    """

    preview_requested = Signal(int)

    def __init__(self, shots, images, themes, compact=False, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.shots = shots
        self.images = images
        self.compact = compact
        self.index = 0
        self.main = SlideView(len(shots), lambda position: images.get(shots[position].url), themes, radius=7)
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
        self.caption.setVisible(bool(shot.caption))
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
            height = max(260, min(460, int(self.width() * 0.56)))
        self.main.setFixedHeight(height)
        self.left.move(10, height // 2 - 16)
        self.right.move(self.width() - 42, height // 2 - 16)
        self.counter.adjustSize()  # the first select() runs before the stylesheet padding is known
        self.counter.move(self.width() - self.counter.width() - 10, height - self.counter.height() - 10)
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
            html = "<p>" + markdown.inline(package.description or "No description provided.") + "</p>"
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
        browser.setHtml(html)
        layout.addWidget(browser)
        column = vbox(frame, spacing=12)
        links = self._links(package) if self.single_column else None  # wide windows show Links in the side column
        if links is not None:
            column.addWidget(links)
        holder.setLayout(column)
        return holder

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
        compatibility = (package.min_max_version + " and newer") if package.min_max_version else "Any version"
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
