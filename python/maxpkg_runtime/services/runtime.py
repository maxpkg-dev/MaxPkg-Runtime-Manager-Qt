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

from ..domain import api, integrity, update_check
from ..domain.packages import (DIVIDER, Package, compatible, incompatibility, is_divider, is_newer,
                               merge_visible_order, normalized_order, ordered_for_toolbar, read_mzp_manifest, scan,
                               supported_versions, toolbar_entries, with_brand_divider)
from ..domain.settings import load_or_migrate
from ..qt_compat import QtCore, Signal
from . import log, max_api, network
from . import self_update as manager_update
from .self_update import SelfUpdater

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
        self.install_queue = []       # references MaxScript asked to install while an operation ran
        self._batch = None            # results of those installs until the queue is empty (collection summary)
        self.last_install = ("", False, "")  # (name, ok, reason) of the last install, for the summary
        self.checking_updates = False
        self.connection = "unknown"   # online / offline
        self._catalog_ticket = 0
        self._stopped = False
        self.self_update = SelfUpdater(self)  # the Package Manager's own updates

    # ----------------------------------------------------------------- lifecycle
    def start(self):
        self.scan()
        self._restore_update_cache()
        log.info("startup", "MaxPkg Runtime (Qt) {} on 3ds Max {}".format(self.version, self.max_year))

    def stop(self):
        self._stopped = True
        self.self_update.stop()
        if self.install_queue:
            log.warning("installer", "Stopped with {} queued installs: {}".format(len(self.install_queue),
                                                                                 ", ".join(self.install_queue)))
            self.install_queue = []
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

    def open_video(self, url):
        """A package video in the browser (only http and https links open)."""
        if not max_api.open_url(url):
            self.say("This video is not available.", "warning")
            return False
        log.info("details", "Opened video " + url)
        return True

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
        for field in ("full_description", "screenshots", "videos", "rating", "review_count", "download_count",
                      "icon_url", "category"):
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
        """The packages only: the automatic check after start (Check Updates uses check_all_updates)."""
        if self.checking_updates or not self.packages:
            if manual and not self.packages:
                self.say("No installed packages to check.", "info")
            return False
        self.checking_updates = True
        self.updates_checking_changed.emit(True)

        def done(result):
            self.checking_updates = False
            self.updates_checking_changed.emit(False)
            if manual:
                self._say_notice(update_check.summarize(result,
                                                        update_check.ManagerResult(update_check.MANAGER_SKIPPED)))

        self._check_packages(done)
        return True

    def check_all_updates(self):
        """Check Updates (the Manager's header and the toolbar menu): the packages and the Package Manager itself at
        the same time, then one message for both. A newer Package Manager is installed right away, or as soon as the
        running package operation ends. False when a check already runs."""
        if self._stopped or self.checking_updates:
            return False
        self.checking_updates = True  # "Checking updates..." until both answers are in
        self.updates_checking_changed.emit(True)
        results = {}

        def finished(part, result):
            results[part] = result
            if len(results) < 2 or self._stopped:
                return
            self.checking_updates = False
            self.updates_checking_changed.emit(False)
            self._finish_check(results["packages"], results["manager"])

        # A Package Manager update that already runs (download, restart) has its own messages: only packages then.
        if not self.self_update.check(manual=True, report=lambda status: finished("manager", status)):
            finished("manager", "")
        if self.packages:
            self._check_packages(lambda result: finished("packages", result))
        else:
            finished("packages", update_check.PackagesResult(update_check.PACKAGES_NONE))
        return True

    def check_manager_update(self):
        """Check Manager Updates (the toolbar menu): the Package Manager alone. A newer version is installed the same
        way as by Check Updates. False when a Package Manager check or update already runs."""
        if self._stopped:
            return False
        skipped = update_check.PackagesResult(update_check.PACKAGES_SKIPPED)
        return self.self_update.check(
            manual=True, report=lambda status: self._finish_check(skipped, status, retry=self.check_manager_update))

    def _finish_check(self, packages, manager_status, retry=None):
        """Both answers of Check Updates are in: install a newer Package Manager (now, or after the running package
        operation) and say the result once. `retry`: what Try Again runs (Check Updates by default)."""
        updater = self.self_update
        update = updater.available
        if manager_status == manager_update.CURRENT:
            manager = update_check.ManagerResult(update_check.MANAGER_CURRENT, self.version)
        elif manager_status == manager_update.FAILED:
            manager = update_check.ManagerResult(update_check.MANAGER_FAILED)
        elif manager_status == manager_update.AVAILABLE and update is not None:
            if not updater.can_install():
                status = update_check.MANAGER_SOURCE
            elif updater.busy_with_packages():
                status = update_check.MANAGER_WAIT
            else:
                status = update_check.MANAGER_INSTALL
            manager = update_check.ManagerResult(status, update.version)
        else:
            manager = update_check.ManagerResult(update_check.MANAGER_SKIPPED)
        if manager.status == update_check.MANAGER_INSTALL:
            log.info("self-update", "Check Updates installs Package Manager " + update.version)
            if not updater.install():
                manager = update_check.ManagerResult(update_check.MANAGER_SKIPPED)
        elif manager.status == update_check.MANAGER_WAIT:
            log.info("self-update", "Package Manager {} waits for the running package operation".format(update.version))
            updater.install_when_idle()
        # After install() began: the toast lies above the Manager's busy card, not under it.
        self._say_notice(update_check.summarize(packages, manager), retry)

    def _check_packages(self, on_result):
        """Ask the service for newer package versions, keep the answer (settings cache, the packages' update links)
        and hand on_result an update_check.PackagesResult."""
        max_year = self.max_year

        def done(remote, error):
            if self._stopped:
                return
            if error is not None:
                log.warning("updater", "Update check failed: " + network.describe(error))
                on_result(update_check.PackagesResult(update_check.PACKAGES_FAILED))
                return
            cache = []
            for package in self.packages:
                found = remote.get(package.guid.lower())
                if found is not None and is_newer(found.version, package.version):
                    cache.append(package.guid + "@" + found.version)
                    package.download_url = found.download_url
                    package.download_sha256 = found.download_sha256  # same response as the link
            self.settings.package_update_cache = cache
            self.settings.last_package_check_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
            self.save_settings("updates")
            self._apply_known_updates()
            self.packages_changed.emit()
            on_result(update_check.PackagesResult(update_check.PACKAGES_CHECKED, self._pending_updates()))

        self._post(api.updates_request(self.packages, max_year, self.version, self.api_channel),
                   lambda text: api.parse_updates(text, max_year), done)

    def _pending_updates(self):
        return [(package.display_name, package.version, package.latest_version)
                for package in self.packages if package.update_available]

    def say_self_updated(self):
        """After the Package Manager restarted on a new version: say so, with the package updates already known."""
        self._say_notice(update_check.updated_notice(self.version, self._pending_updates()))

    def _say_notice(self, notice, retry=None):
        """An update_check.Notice as a toast; its action names become buttons. `retry`: Try Again (Check Updates)."""
        guids = [package.guid for package in self.packages if package.update_available]
        buttons = {update_check.UPDATE: ("Update", "download", lambda: self.update(guids[0]) if guids else False),
                   update_check.UPDATE_ALL: ("Update All", "download", self.update_all),
                   update_check.RETRY: ("Try Again", "refresh-cw", retry or self.check_all_updates)}
        self.say(notice.text, notice.kind, [buttons[name] for name in notice.actions])

    # ----------------------------------------------------------------- critical operations
    def _begin(self, message):
        if self.operation:
            log.warning("installer", "Refused while another operation runs ({}): {}".format(self.operation, message))
            self.say("Another package operation is already running.", "warning")
            return False
        self.operation = message
        self.busy_changed.emit(message)
        return True

    def _finish(self):
        self.operation = ""
        self.busy_changed.emit("")
        if self.install_queue:
            QtCore.QTimer.singleShot(0, self._next_queued)  # after this operation's message and callback

    def request_install(self, reference):
        """An install asked for from MaxScript (MaxPkg.install / installMany, such as a maxpkg.dev collection
        installer). It starts now, or waits for the running operation and earlier requests instead of being refused.
        Returns False only for an empty reference."""
        reference = (reference or "").strip()
        if not reference:
            return False
        if reference.lower() in (queued.lower() for queued in self.install_queue):
            log.info("installer", "Already waiting to be installed: " + reference)
            return True
        if self._batch is None:
            self._batch = []
        if self.operation or self.install_queue:
            self.install_queue.append(reference)
            log.info("installer", "Queued {} ({} waiting)".format(reference, len(self.install_queue)))
            return True
        log.info("installer", "Install requested: " + reference)
        return self.install(reference, on_done=self._batch_done)

    def _next_queued(self):
        if self._stopped or self.operation or not self.install_queue:
            return  # an operation started meanwhile (Update All): its end calls this again
        reference = self.install_queue.pop(0)
        log.info("installer", "Installing from the queue: {} ({} left)".format(reference, len(self.install_queue)))
        self.install(reference, on_done=self._batch_done)

    def _batch_done(self, _ok):
        """One requested install ended. When nothing waits any more and the batch had several packages (a
        collection), one summary names the packages that were not installed; each one also had its own message."""
        if self._batch is None:
            return
        self._batch.append(self.last_install)
        if self.install_queue:
            return
        results, self._batch = self._batch, None
        if len(results) < 2:
            return
        missing = [name + (" (" + reason + ")" if reason else "") for name, ok, reason in results if not ok]
        installed = len(results) - len(missing)
        if not missing:
            log.success("installer", "All {} requested packages were installed".format(len(results)))
            self.say("All {} packages were installed.".format(len(results)), "success")
            return
        log.warning("installer", "{} of {} requested packages were installed; not installed: {}".format(
            installed, len(results), ", ".join(missing)))
        self.say("{} of {} packages were installed.\nNot installed: {}.".format(installed, len(results),
                                                                              ", ".join(missing)), "warning")

    def _verify_download(self, file_path, published):
        """Check a downloaded package against the SHA-256 that the API response giving its link published, before
        anything opens the archive. `published` is (sha256, name, version), or None for a link from MaxScript that
        came without an API response. Returns '' when the file may be installed, else the message for the user;
        the hashes go only to the log."""
        expected, name, version = published if published is not None else ("", "", "")
        title = " ".join(part for part in (name, version) if part) or "the package"
        result, actual = integrity.verify_file(file_path, expected)
        if result == integrity.MATCH:
            log.info("installer", "SHA-256 verified for {}: {}".format(title, actual))
            return ""
        if result == integrity.UNPUBLISHED:  # versions imported before the service stored hashes
            log.warning("installer", "{} has no published SHA-256{}; installing without verification (file {})".format(
                title, "" if published is not None else " (direct link)", actual))
            return ""
        if result == integrity.UNREADABLE:
            log.error("installer", "SHA-256 of {} could not be computed: the downloaded file could not be read".format(
                title))
            return ("Package verification failed: {}.\nThe downloaded file could not be checked and was not "
                    "installed.".format(title))
        log.error("installer", "SHA-256 mismatch for {}: expected {}, got {}; the file was deleted and not "
                               "installed".format(title, expected.strip(), actual))
        return ("Package verification failed: {}.\nThe downloaded file does not match the published version and was "
                "not installed.".format(title))

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
        self.last_install = (fallback_name, False, "")

        def failed(error):
            self._finish()
            message = error.message if isinstance(error, api.ApiError) else network.describe(error)
            log.error("installer", "{} could not be {}: {}".format(fallback_name, "updated" if updating else "installed",
                                                                   message))
            self.last_install = (fallback_name, False, "")
            self.say("{} could not be {}.\n{}".format(fallback_name, "updated" if updating else "installed", message),
                     "error", retry)
            if on_done:
                on_done(False)

        def fetch(source, guid, published=None):
            """`published`: (sha256, name, version) from the API response that gave `source`."""
            if not source.lower().startswith(("http://", "https://")):
                done((source, guid, False, None), None)  # a file the user chose: nothing was downloaded
                return
            target = os.path.join(self.paths.downloads, "maxpkg-download-" + uuid.uuid4().hex + ".mzp")
            self.network.download(source, target, lambda path, error: done((path, guid, True, published), error))

        def resolved(package, error):
            if error is not None:
                failed(error)
            elif not package.download_url:
                failed(api.ApiError("ARTIFACT_NOT_FOUND", "The MaxPkg service did not provide a download for this package."))
            else:
                fetch(package.download_url, package.guid,
                      (package.download_sha256, package.display_name, package.version))

        def done(result, error):
            if error is not None:
                failed(error)
                return
            path, guid, temporary, published = result
            if temporary:
                # Before the archive is opened (manifest, fileIn): the file installed is the file that was checked.
                problem = self._verify_download(path, published)
                if problem:
                    _remove_file(path)
                    self._finish()
                    self.last_install = ((published[1] if published else "") or fallback_name, False,
                                         "verification failed")
                    self.say(problem, "error", retry)
                    if on_done:
                        on_done(False)
                    return
            bundled = read_mzp_manifest(path)
            problem = incompatibility(bundled, max_year) if bundled is not None else ""
            if problem:  # a file chosen by hand or a direct link: the catalog never offers it for this 3ds Max
                if temporary:
                    _remove_file(path)
                self._finish()
                log.warning("installer", "Not installed on 3ds Max {}: {} supports {}".format(
                    max_year, bundled.guid or "package", supported_versions(bundled)))
                name = bundled.display_name if bundled.name else fallback_name
                self.last_install = (name, False, "")
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
            self.last_install = (label, ok, "")
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
            # An update link comes with the hash of the same update check; another link has no API response.
            published = None
            if previous is not None and reference == previous.download_url:
                published = (previous.download_sha256, previous.display_name, previous.latest_version)
            fetch(reference, previous.guid if previous is not None else "", published)
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
