"""Runtime state and operations: the Python counterpart of the MaxScript `MaxPkg` facade.

Owns settings, installed packages, catalog state and the single critical-operation lock.
UI code reads state from here and calls its methods; it never talks to the network or pymxs itself.
"""

import datetime
import os
import re
import shutil
import stat
import uuid

from ..domain import api
from ..domain.packages import (DIVIDER, Package, compatible, incompatibility, is_divider, is_newer,
                               merge_visible_order, normalized_order, ordered_for_toolbar, read_mzp_manifest, scan,
                               supported_versions, toolbar_entries, with_brand_divider)
from ..domain.settings import load_or_migrate
from ..qt_compat import QtCore, Signal
from . import log, max_api, network

LEGACY_FOLDER = "MaxPkg-Runtime-Manager"
DATA_FOLDER = "MaxPkg-Runtime-Manager-Qt"


class Paths:
    def __init__(self, temp_dir):
        self.max_temp = temp_dir
        self.legacy_root = os.path.join(temp_dir, LEGACY_FOLDER)
        self.data_root = os.path.join(temp_dir, DATA_FOLDER)
        self.settings = os.path.join(self.data_root, "settings.ini")
        self.legacy_settings = os.path.join(self.legacy_root, "settings.ini")
        self.logs = os.path.join(self.data_root, "logs")
        self.image_cache = os.path.join(self.data_root, "cache", "images")
        self.downloads = os.path.join(self.data_root, "downloads")
        self.packages = os.path.join(self.data_root, "data", "packages")

    def package_roots(self, extra):
        roots = [self.max_temp, os.path.join(self.legacy_root, "data", "packages"), self.packages]
        roots.extend(extra)
        unique = []
        for root in roots:
            if root and os.path.normcase(root) not in [os.path.normcase(known) for known in unique]:
                unique.append(root)
        return unique


class DiscoverQuery:
    """What Discover shows: either a collection/featured selection or a category filter."""

    def __init__(self):
        self.text = ""
        self.category = ""
        self.sort = "popular"
        self.page = 1
        self.featured = False
        self.collection = ""

    def copy(self):
        clone = DiscoverQuery()
        clone.__dict__.update(self.__dict__)
        return clone


class CatalogState:
    def __init__(self):
        self.loading = False
        self.available = False
        self.message = "Preparing the package catalog."
        self.page = None              # api.CatalogPage
        self.collections_loaded = False
        self.featured_count = 0
        self.collections = []
        self.categories = []
        self.total_packages = -1


class Runtime(QtCore.QObject):
    packages_changed = Signal()
    catalog_changed = Signal()
    details_changed = Signal(str)        # guid
    settings_changed = Signal(str)       # area: general/toolbar/theme/updates
    busy_changed = Signal(str)           # operation message, '' when idle
    # message, kind (info/success/warning/error), actions: [(label, icon name, callback)] the toast offers
    notify = Signal(str, str, object)
    details_requested = Signal(str)      # guid: a toast's Details button (the Controller opens the Manager page)
    updates_checking_changed = Signal(bool)

    def __init__(self, root, version, channel, parent=None):
        QtCore.QObject.__init__(self, parent)
        self.root = root
        self.version = version
        self.channel = channel
        # Package channel sent to the API. The Runtime build channel (version.ini) is separate:
        # the server rejects unknown channels such as "preview" with HTTP 400.
        self.api_channel = "stable"
        self.max_year = max_api.max_year()
        self.paths = Paths(max_api.get_dir("temp") or os.path.join(os.environ.get("TEMP", "."), "maxpkg-test"))
        log.configure(self.paths.logs)
        self.settings, migrated = load_or_migrate(self.paths.settings, self.paths.legacy_settings)
        log.configure(self.paths.logs, self.settings.debug_logging)
        if migrated:
            log.info("settings", "Imported settings from " + self.paths.legacy_settings)
        self.network = network.NetworkService(self)
        self.packages = []
        self.catalog = CatalogState()
        self.query = DiscoverQuery()
        self.details = {}             # guid_lower -> remote Package with details
        self.details_errors = {}
        self.operation = ""           # '' when no critical operation runs
        self.checking_updates = False
        self.connection = "unknown"   # online / offline
        self._catalog_ticket = 0
        self._stopped = False

    # ----------------------------------------------------------------- lifecycle
    def start(self):
        self.scan()
        self._restore_update_cache()
        log.info("startup", "MaxPkg Runtime (Qt) {} on 3ds Max {}".format(self.version, self.max_year))

    def stop(self):
        self._stopped = True
        self.network.stop()

    def say(self, text, kind="info", actions=None):
        """A message for the user; `actions` are offered as buttons on its toast (the first one is the main one)."""
        self.notify.emit(text, kind, list(actions or []))

    # ----------------------------------------------------------------- settings
    def save_settings(self, area="general"):
        try:
            self.settings.save()
        except OSError as error:
            log.error("settings", "Could not save settings: " + str(error))
            # str(error) names the file (and so the Windows user name): the toast only gives the reason.
            reason = (error.strerror or "The settings file could not be written") + "."
            self.say("Settings could not be saved.\n" + reason, "error")
            return False
        self.settings_changed.emit(area)
        return True

    # ----------------------------------------------------------------- packages
    def scan(self):
        self.packages = scan(self.paths.package_roots(self.settings.package_roots),
                             lambda message: log.warning("scanner", message))
        order = normalized_order(self.packages, self.settings.toolbar_order)
        if self.packages and not self.settings.toolbar_brand_divider_added:
            order = with_brand_divider(order)  # once: later the user may move or remove it
            self.settings.toolbar_brand_divider_added = True
            self.settings.toolbar_order = []  # forces the save below
        if [guid.lower() for guid in order] != [guid.lower() for guid in self.settings.toolbar_order]:
            self.settings.toolbar_order = order
            self.save_settings("toolbar")
        self._apply_known_updates()
        log.info("scanner", "Discovered {} package(s)".format(len(self.packages)))
        self.packages_changed.emit()
        return self.packages

    def package(self, reference):
        for package in self.packages:
            if package.same(reference):
                return package
        return None

    def toolbar_packages(self):
        return ordered_for_toolbar(self.packages, self.settings.toolbar_order, self.settings.is_hidden)

    def toolbar_entries(self):
        """Visible packages and DIVIDER entries in toolbar order (only the toolbar shows dividers)."""
        return toolbar_entries(self.packages, self.settings.toolbar_order, self.settings.is_hidden)

    def set_toolbar_locked(self, locked):
        """A locked toolbar keeps its buttons and dividers where they are (no reordering, dividers or hiding)."""
        self.settings.toolbar_locked = bool(locked)
        return self.save_settings("toolbar")

    def add_toolbar_divider(self, after_guid):
        """Insert a divider right after `after_guid` in the saved order (any number of dividers is allowed)."""
        if self.settings.toolbar_locked:
            return False
        order = list(self.settings.toolbar_order)
        lowered = [entry.lower() for entry in order]
        position = lowered.index(after_guid.lower()) + 1 if after_guid.lower() in lowered else len(order)
        order.insert(position, DIVIDER)
        return self.set_full_order(order)

    def remove_toolbar_divider(self, ordinal):
        """Remove the `ordinal`-th divider (0-based, the same count as on the toolbar)."""
        if self.settings.toolbar_locked:
            return False
        order = list(self.settings.toolbar_order)
        positions = [index for index, entry in enumerate(order) if is_divider(entry)]
        if not 0 <= ordinal < len(positions):
            return False
        order.pop(positions[ordinal])
        return self.set_full_order(order)

    def is_on_toolbar(self, package):
        return package.toolbar_visible and not self.settings.is_hidden(package.guid)

    def update_count(self):
        return sum(1 for package in self.packages if package.update_available)

    def run(self, reference):
        package = self.package(reference)
        if package is None:
            self.say("The package could not be found.", "error")
            return False
        problem = incompatibility(package, self.max_year)
        if problem:  # its own version check would stop it anyway, with a less clear error
            log.warning("launcher", package.guid + ": not started on 3ds Max {}: supports {}".format(
                self.max_year, supported_versions(package)))
            self.say(package.display_name + " could not be started.\n" + problem, "error")
            return False
        ok, message = max_api.run_package(package)
        if not ok:
            self.say(package.display_name + " could not be started.\n" + message, "error")
        return ok

    def warn_if_incompatible(self, reference):
        """An MZP dropped into the viewport runs its own installer, so nothing could check it first: say right
        away that it will not start in this 3ds Max."""
        package = self.package(reference)
        problem = incompatibility(package, self.max_year) if package is not None else ""
        if problem:
            guid = package.guid
            self.say(package.display_name + " was installed, but it will not start here.\n" + problem, "warning",
                     [("Details", "info", lambda: self.details_requested.emit(guid))])
        return bool(problem)

    def set_toolbar_visible(self, reference, visible):
        package = self.package(reference)
        if package is None:
            return False
        self.settings.set_hidden(package.guid, not visible)
        ok = self.save_settings("toolbar")
        self.packages_changed.emit()
        return ok

    def set_toolbar_order(self, visible_guids):
        if self.settings.toolbar_locked:
            self.packages_changed.emit()  # puts a live-dragged floating button back in its place
            return False
        visible = [package.guid for package in self.toolbar_packages()]
        merged = merge_visible_order(self.settings.toolbar_order, visible_guids, visible)
        self.settings.toolbar_order = normalized_order(self.packages, merged)
        ok = self.save_settings("toolbar")
        self.packages_changed.emit()
        return ok

    def set_full_order(self, guids):
        self.settings.toolbar_order = normalized_order(self.packages, guids)
        ok = self.save_settings("toolbar")
        self.packages_changed.emit()
        return ok

    def reset_toolbar_order(self):
        self.settings.toolbar_order = with_brand_divider(
            package.guid for package in sorted(self.packages, key=lambda item: (item.toolbar_order, item.name.lower())))
        ok = self.save_settings("toolbar")
        self.packages_changed.emit()
        return ok

    def open_folder(self, reference):
        package = self.package(reference)
        return package is not None and max_api.open_folder(package.install_path)

    def open_logs(self):
        """Explorer on the log folder (one file per day)."""
        try:
            os.makedirs(self.paths.logs, exist_ok=True)
        except OSError:
            return False
        return max_api.open_folder(self.paths.logs)

    def open_image_cache(self):
        """Explorer on the image cache; the folder is created first, so it opens before any picture is cached."""
        try:
            os.makedirs(self.paths.image_cache, exist_ok=True)
        except OSError as error:
            log.warning("images", "Cannot create the image cache folder: " + str(error))
            return False
        return max_api.open_folder(self.paths.image_cache)

    def site_url(self, path=""):
        """The maxpkg.dev site of the configured service (a development endpoint keeps its own site)."""
        origin = re.match(r"^(https?://[^/]+)", self.settings.effective_endpoint)
        return (origin.group(1) if origin else "https://maxpkg.dev") + path

    def open_catalog(self):
        """The website's catalog in the browser."""
        return max_api.open_url(self.site_url("/catalog"))

    def link_url(self, package, kind):
        if kind == "maxpkg":
            return self.site_url("/catalog/" + (package.slug or package.guid))
        return {"homepage": package.homepage_url, "documentation": package.documentation_url,
                "support": package.support_url, "purchase": package.purchase_url,
                "license": package.license_url}.get(kind, "")

    def open_link(self, package, kind):
        url = self.link_url(package, kind)
        if not max_api.open_url(url):
            self.say("This link is not available.", "warning")
            return False
        return True

    # ----------------------------------------------------------------- catalog
    def _post(self, request, parse, on_done):
        return self.network.post(self.settings.effective_endpoint, request, parse, on_done)

    def load_collections(self):
        def done(result, error):
            if error is None:
                self.catalog.featured_count, self.catalog.collections = result
                self.catalog.collections_loaded = True
            else:
                log.warning("catalog", "Collections: " + network.describe(error))
            self.catalog_changed.emit()

        def categories_done(result, error):
            if error is None:
                self.catalog.categories = result
            else:
                log.warning("catalog", "Categories: " + network.describe(error))
            self.catalog_changed.emit()

        self._post(api.collections_request(self.max_year, self.version, self.api_channel), api.parse_collections, done)
        self._post(api.categories_request(self.max_year, self.version, self.api_channel), api.parse_categories,
                   categories_done)

    def browse(self, query=None):
        """Load a catalog page for `query` (or the current one). Older responses are dropped."""
        if query is not None:
            self.query = query
        query = self.query
        self.network.forget(self._catalog_ticket)
        self.catalog.loading = True
        self.catalog_changed.emit()
        request = api.catalog_request(self.max_year, self.version, self.api_channel, query.text, query.category,
                                      query.sort, query.page, query.featured, query.collection)
        max_year = self.max_year

        def done(page, error):
            self.catalog.loading = False
            if error is None:
                self.catalog.available = True
                self.catalog.page = page
                if page.total_packages >= 0:
                    self.catalog.total_packages = page.total_packages
                elif not (query.text or query.category or query.featured or query.collection):
                    self.catalog.total_packages = page.total
                self.connection = "online"
            else:
                self.catalog.available = False
                self.catalog.message = network.describe(error)
                self.connection = "offline"
                log.warning("catalog", "Catalog: " + self.catalog.message)
            self.catalog_changed.emit()

        self._catalog_ticket = self._post(request, lambda text: api.parse_catalog(text, max_year), done)

    def load_details(self, package):
        key = package.guid.lower()
        if key in self.details:
            return self.details[key]
        max_year = self.max_year

        def done(result, error):
            if error is None:
                self.details[key] = result
                self.details_errors.pop(key, None)
            else:
                self.details_errors[key] = network.describe(error)
            self.details_changed.emit(package.guid)

        self._post(api.details_request(package.slug or package.guid, max_year, self.version, self.api_channel),
                   lambda text: api.parse_details(text, max_year), done)
        return None

    def merged_details(self, guid):
        """Best known information for a package: installed record enriched with online details."""
        installed = self.package(guid)
        remote = self.details.get(guid.lower())
        if installed is None:
            return remote
        if remote is None:
            return installed
        merged = Package(**installed.__dict__)
        for field in ("full_description", "screenshots", "rating", "review_count", "download_count", "icon_url",
                      "category"):
            setattr(merged, field, getattr(remote, field))
        if remote.changelog:
            merged.changelog = remote.changelog
        for field in ("homepage_url", "documentation_url", "support_url", "purchase_url", "purchase_button_label",
                      "license_type", "license_url"):
            if not getattr(merged, field):
                setattr(merged, field, getattr(remote, field))
        merged.details_loaded = True
        return merged

    # ----------------------------------------------------------------- updates
    def _restore_update_cache(self):
        self._apply_known_updates()
        self.packages_changed.emit()

    def _apply_known_updates(self):
        cached = {}
        for entry in self.settings.package_update_cache:
            guid, _, version = entry.partition("@")
            cached[guid.lower()] = version
        for package in self.packages:
            latest = cached.get(package.guid.lower(), "")
            package.update_available = bool(latest) and is_newer(latest, package.version)
            package.latest_version = latest if package.update_available else package.version

    def automatic_check_due(self):
        if not self.settings.auto_check_packages or not self.settings.last_package_check_utc:
            return self.settings.auto_check_packages
        try:
            last = datetime.datetime.strptime(self.settings.last_package_check_utc[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            return True
        elapsed = datetime.datetime.utcnow() - last
        return elapsed.total_seconds() >= self.settings.update_frequency_hours * 3600

    def check_updates(self, manual=True):
        if self.checking_updates or not self.packages:
            if manual and not self.packages:
                self.say("No installed packages to check.", "info")
            return False
        self.checking_updates = True
        self.updates_checking_changed.emit(True)
        max_year = self.max_year

        def done(remote, error):
            self.checking_updates = False
            self.updates_checking_changed.emit(False)
            if error is not None:
                log.warning("updater", "Update check failed: " + network.describe(error))
                if manual:
                    self.say("The package update check failed.\nThe previous result is still available.", "error",
                             [("Try Again", "refresh-cw", lambda: self.check_updates(True))])
                return
            cache = []
            for package in self.packages:
                found = remote.get(package.guid.lower())
                if found is not None and is_newer(found.version, package.version):
                    cache.append(package.guid + "@" + found.version)
                    package.download_url = found.download_url
            self.settings.package_update_cache = cache
            self.settings.last_package_check_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
            self.save_settings("updates")
            self._apply_known_updates()
            self.packages_changed.emit()
            if manual:
                self._offer_updates()

        self._post(api.updates_request(self.packages, max_year, self.version, self.api_channel),
                   lambda text: api.parse_updates(text, max_year), done)
        return True

    def _offer_updates(self):
        """The result of a manual check, with the update right on the toast."""
        pending = [package for package in self.packages if package.update_available]
        if not pending:
            self.say("All packages are up to date.", "success")
        elif len(pending) == 1:
            package = pending[0]
            self.say("An update is available.\n{} {} → {}".format(package.display_name, package.version,
                                                                        package.latest_version), "info",
                     [("Update", "download", lambda: self.update(package.guid))])
        else:
            names = ", ".join(package.display_name for package in pending[:3]) + (
                " and {} more".format(len(pending) - 3) if len(pending) > 3 else "")
            self.say("{} updates are available.\n{}".format(len(pending), names), "info",
                     [("Update All", "download", self.update_all)])

    # ----------------------------------------------------------------- critical operations
    def _begin(self, message):
        if self.operation:
            self.say("Another package operation is already running.", "warning")
            return False
        self.operation = message
        self.busy_changed.emit(message)
        return True

    def _finish(self):
        self.operation = ""
        self.busy_changed.emit("")

    def install(self, reference, on_done=None, updating=False, previous=None):
        """Resolve (API) and download asynchronously, then fileIn the MZP on the main thread and verify.
        `updating`: the package is installed over an older version (the messages say "updated").
        `previous`: the installed package being updated; it gives the GUID, name and old version when `reference`
        is a download URL (the downloaded file's name says nothing about the package)."""
        reference = (reference or "").strip()
        if not reference or not self._begin("Updating package..." if updating else "Installing package..."):
            return False
        max_year = self.max_year
        retry = [("Try Again", "refresh-cw", lambda: self.install(reference, updating=updating, previous=previous))]
        is_location = reference.lower().startswith(("http://", "https://")) or os.path.isfile(reference)
        # Messages name the package, never a URL or file path.
        fallback_name = previous.display_name if previous is not None else ("The package" if is_location else reference)

        def failed(error):
            self._finish()
            message = error.message if isinstance(error, api.ApiError) else network.describe(error)
            log.error("installer", "{} could not be {}: {}".format(fallback_name, "updated" if updating else "installed",
                                                                   message))
            self.say("{} could not be {}.\n{}".format(fallback_name, "updated" if updating else "installed", message),
                     "error", retry)
            if on_done:
                on_done(False)

        def fetch(source, guid):
            if not source.lower().startswith(("http://", "https://")):
                done((source, guid, False), None)
                return
            target = os.path.join(self.paths.downloads, "maxpkg-download-" + uuid.uuid4().hex + ".mzp")
            self.network.download(source, target, lambda path, error: done((path, guid, True), error))

        def resolved(package, error):
            if error is not None:
                failed(error)
            elif not package.download_url:
                failed(api.ApiError("ARTIFACT_NOT_FOUND", "The MaxPkg service did not provide a download for this package."))
            else:
                fetch(package.download_url, package.guid)

        def done(result, error):
            if error is not None:
                failed(error)
                return
            path, guid, temporary = result
            bundled = read_mzp_manifest(path)
            problem = incompatibility(bundled, max_year) if bundled is not None else ""
            if problem:  # a file chosen by hand or a direct link: the catalog never offers it for this 3ds Max
                if temporary:
                    _remove_file(path)
                self._finish()
                log.warning("installer", "Not installed on 3ds Max {}: {} supports {}".format(
                    max_year, bundled.guid or "package", supported_versions(bundled)))
                name = bundled.display_name if bundled.name else fallback_name
                self.say("{} was not {}.\n{}".format(name, "updated" if updating else "installed", problem), "error")
                if on_done:
                    on_done(False)
                return
            guid = guid or (previous.guid if previous is not None else "") or _guid_from_file_name(path)
            ok = self._install_file(path, guid)
            if temporary:
                _remove_file(path)
            self._finish()
            package = self.package(guid) if guid else None
            label = package.display_name if package else fallback_name
            if ok:
                run = [("Run", "play", lambda: self.run(package.guid)),
                       ("Details", "info", lambda: self.details_requested.emit(package.guid))] if package else []
                if updating:
                    # Same shape as "An update is available.": the name, then old → new version.
                    old = previous.version if previous is not None else ""
                    new = package.version if package else ""
                    versions = "{} → {}".format(old, new) if old and new and old != new else (new and "Version " + new)
                    log.success("installer", "Updated {}{}".format(label, " " + versions if versions else ""))
                    self.say("{} was updated.".format(label) + ("\n" + versions if versions else ""), "success", run)
                else:
                    on_toolbar = (package is not None and self.settings.toolbar_visible
                                  and self.is_on_toolbar(package))
                    log.success("installer", "Installed {}{}".format(label, " " + package.version if package else ""))
                    self.say(label + " was installed." + ("\nIt is on the toolbar now." if on_toolbar else ""),
                             "success", run)
            else:
                log.error("installer", label + (" could not be updated or verified." if updating else
                                                " could not be installed or verified."))
                self.say(label + (" could not be updated or verified." if updating else
                                  " could not be installed or verified."), "error", retry)
            if on_done:
                on_done(ok)

        if is_location:
            fetch(reference, previous.guid if previous is not None else "")
        else:
            self._post(api.resolve_request(reference, max_year, self.version, self.api_channel),
                       lambda text: api.parse_details(text, max_year), resolved)
        return True

    def _install_file(self, path, guid):
        count_before = len(self.packages)
        try:
            _clear_read_only(max_api.get_dir("userStartupScripts"))
            max_api.file_in(path)
            log.info("installer", "Executed " + path)
        except Exception as error:  # noqa: BLE001 - installer scripts are third-party code
            log.error("installer", "Installation failed: " + max_api.error_text(error))
            self.scan()
            return False
        self.scan()
        return self.package(guid) is not None if guid else len(self.packages) >= count_before

    def update(self, reference, on_done=None):
        package = self.package(reference)
        if package is None or not package.update_available:
            self.say("No compatible package update is available.", "info")
            return False
        return self.install(package.download_url or package.guid, on_done, updating=True, previous=package)

    def update_all(self):
        pending = [package.guid for package in self.packages if package.update_available]

        def next_one(_ok=True):
            if pending and not self._stopped:
                self.update(pending.pop(0), next_one)

        next_one()
        return bool(pending)

    def uninstall(self, reference):
        package = self.package(reference)
        if package is None:
            self.say("The package could not be found.", "error")
            return False
        if not self._begin("Uninstalling package..."):
            return False
        try:
            ok, message = self._uninstall(package)
        finally:
            self.scan()
            self._finish()
        if ok and self.package(package.guid) is None:
            guid = package.guid
            log.success("uninstaller", "Removed {} {}".format(package.display_name, package.version))
            self.say(package.display_name + " was removed.\nYour scenes are not changed.", "success",
                     [("Reinstall", "download", lambda: self.install(guid))])
            return True
        log.error("uninstaller", package.display_name + " could not be removed." + (" " + message if message else ""))
        self.say(package.display_name + " could not be removed." + ("\n" + message if message else ""), "error")
        return False

    def _uninstall(self, package):
        """Same order and safety checks as core/uninstaller.ms. Returns (ok, message): the message is for the user
        (no paths or GUIDs); the details go to the log."""
        problem = self._unsafe_folder(package)
        if problem:
            log.error("uninstaller", problem)
            return False, "Its folder is not a normal package folder, so nothing was deleted."
        hook = os.path.join(package.install_path, package.uninstall_script or "")
        try:
            _clear_read_only(max_api.get_dir("userStartupScripts"))
            if package.uninstall_script and os.path.isfile(hook):
                max_api.file_in(hook)
            quad_helper = os.path.join(package.install_path, "maxpkg-quad.ms")
            if os.path.isfile(quad_helper):
                max_api.file_in(quad_helper)
                literal = package.install_path.replace("\\", "\\\\").replace('"', '\\"')
                if max_api.execute('(MaxPkgQuadMenuManagerData packageFolder: "' + literal + '\\\\").uninstall()') is not True:
                    return False, "Quad Menu commands could not be removed."
        except Exception as error:  # noqa: BLE001
            log.error("uninstaller", "Hook failed for " + package.guid + ": " + max_api.error_text(error))
            return False, "Its uninstall script stopped with an error. The MaxScript Listener shows the details."
        macros = max_api.get_dir("userMacros")
        icons = max_api.get_dir("userIcons")
        startup = max_api.get_dir("userStartupScripts")
        compact = package.guid.replace("-", "")
        files = [os.path.join(macros, "maxpkg-" + package.guid + ".mcr"),
                 os.path.join(macros, "MaxPkg-MaxPkg_" + compact + ".mcr"),
                 os.path.join(icons, package.guid + ".svg"),
                 os.path.join(startup, "maxpkg-" + package.guid + "-quad-startup.ms")]
        if macros and os.path.isdir(macros):
            prefix = ("maxpkg-" + package.guid + "-").lower()
            files.extend(os.path.join(macros, name) for name in os.listdir(macros)
                         if name.lower().startswith(prefix) and name.lower().endswith(".mcr"))
        for path in files:
            if path and not _remove_file(path):
                log.error("uninstaller", "Could not remove " + path)
                return False, "One of its 3ds Max files is in use. Restart 3ds Max and try again."
        try:
            shutil.rmtree(package.install_path, onerror=_force_remove)
        except OSError as error:
            log.error("uninstaller", "Could not remove the package folder: " + str(error))
            return False, "Its folder could not be removed completely. Restart 3ds Max and try again."
        return not os.path.isdir(package.install_path), ""

    def _unsafe_folder(self, package):
        folder = os.path.normcase(os.path.abspath(package.install_path or ""))
        if not package.install_path or not os.path.isfile(package.manifest_path):
            return "Refused unresolved package path for " + package.guid
        if os.path.normcase(os.path.dirname(os.path.abspath(package.manifest_path))) != folder:
            return "Manifest is outside the package folder: " + package.manifest_path
        protected = [self.paths.max_temp, max_api.get_dir("userScripts"), max_api.get_dir("userStartupScripts"),
                     self.paths.legacy_root, self.paths.data_root, str(self.root)]
        for path in protected:
            if path and os.path.normcase(os.path.abspath(path)) == folder:
                return "Refused protected folder: " + package.install_path
        for runtime_root in (self.paths.legacy_root, self.paths.data_root, str(self.root)):
            normalized = os.path.normcase(os.path.abspath(runtime_root))
            if normalized.startswith(folder + os.sep):
                return "Refused a folder that contains the Runtime: " + package.install_path
            if folder.startswith(normalized + os.sep) and "packages" not in folder[len(normalized):]:
                return "Refused a folder inside the Runtime: " + package.install_path
        return ""


def _guid_from_file_name(path):
    parts = os.path.splitext(os.path.basename(path))[0].split("@")
    return parts[-1] if len(parts) >= 3 else ""


def _remove_file(path):
    if not os.path.exists(path):
        return True
    try:
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)
        return True
    except OSError:
        return False


def _force_remove(function, path, _info):
    os.chmod(path, stat.S_IWRITE)
    function(path)


def _clear_read_only(folder):
    if not folder or not os.path.isdir(folder):
        return
    for name in os.listdir(folder):
        path = os.path.join(folder, name)
        if os.path.isfile(path):
            try:
                os.chmod(path, stat.S_IWRITE)
            except OSError:
                pass


__all__ = ["Runtime", "DiscoverQuery", "compatible"]
