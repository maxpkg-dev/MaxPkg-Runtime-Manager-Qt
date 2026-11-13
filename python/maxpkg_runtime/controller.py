"""Lifecycle owner of one Runtime instance: services, toolbar, Manager window, screen toasts.

Created passively by bootstrap.py; `start()` acquires everything, `stop()` releases it in reverse
order and is safe to call twice or after a partial start. Closing the Manager window only
destroys the window; the Runtime (toolbar, update checks) keeps running until the next restart.
"""

import os

from . import qt_compat
from .domain.api import split_references
from .domain import self_update as self_update_rules
from .domain.ini import IniDocument
from .domain.packages import is_divider, split_layout
from .qt_compat import QtCore, QtGui, QtWidgets, is_valid, screen_at
from .services import log, max_api
from .services.images import ImageService
from .services.runtime import Runtime
from .ui.manager_window import ManagerWindow, Toast
from .ui.theme import ThemeService
from .ui.toolbar import ToolbarController
from .ui.welcome import WelcomeWindow

AUTO_CHECK_DELAY_MS = 4000


def read_version(root):
    """(Version, Channel) from version.ini. MaxScript setINISetting rewrites it as UTF-16, so never assume UTF-8."""
    try:
        document = IniDocument.load(root / "version.ini")
    except OSError:
        return "0.0.0", "stable"
    return (document.get("Runtime", "Version") or "0.0.0"), (document.get("Runtime", "Channel") or "stable")


class Controller:
    def __init__(self, root):
        self.root = root
        self.running = False
        self.stopped = False
        self.themes = None
        self.runtime = None
        self.images = None
        self.toolbar = None
        self.window = None
        self.welcome = None
        self._timers = []
        self._close_pending = False
        self._screen_toasts = []  # bottom-right toasts while the Manager is closed

    # ----------------------------------------------------------------- lifecycle
    def start(self, open_manager=True, welcome=False, from_startup=False, updated_from=""):
        """open_manager: launcher/macro; welcome: right after installation; from_startup: 3ds Max start
        (honours 'Start Runtime with 3ds Max' and 'Open Manager on startup'); updated_from: the version this start
        replaced after a self-update (the user is told)."""
        if qt_compat.application() is None:
            raise RuntimeError("No QApplication: run the MaxPkg Runtime inside 3ds Max")
        version, channel = read_version(self.root)
        # Before the auto-start check: with startup off, MaxPkg.isStarted() is false and MaxPkg.start() starts us,
        # so package installers and maxpkg.dev still see the Package Manager instead of offering the old Runtime.
        if not max_api.define_facade(self.root, version):
            log.warning("startup", "MaxPkg global belongs to the old MaxScript Runtime; packages show their own installer")
        self.themes = ThemeService(self.root)
        self.runtime = Runtime(self.root, version, channel)
        settings = self.runtime.settings
        if from_startup and not settings.auto_start:
            log.info("startup", "Start with 3ds Max is off")
            self.runtime.stop()
            self.runtime = None
            self.stopped = True
            return
        self.images = ImageService(self.runtime.network, self.runtime.paths.image_cache)
        self.runtime.packages_changed.connect(self.images.retry_failed)  # a rescan retries icons that failed
        settings.manager_theme = self.themes.set_manager(settings.manager_theme)
        self.runtime.start()
        self.runtime.notify.connect(self._notify_outside)
        self.runtime.details_requested.connect(self.open_details)
        self.runtime.settings_changed.connect(self._on_settings)
        self.toolbar = ToolbarController(self.runtime, self.themes, self.images, self.open_manager,
                                         self.open_details, self.feedback)
        self.toolbar.start()
        self.running = True
        if settings.auto_check_packages and self.runtime.automatic_check_due():
            self._later(AUTO_CHECK_DELAY_MS, lambda: self.runtime.check_updates(manual=False))
        updater = self.runtime.self_update
        updater.manager_is_open = self._manager_showing
        if updater.check_due() and not updated_from:
            # Check Updates pressed in the first seconds already asked (and maybe tried the update): not twice.
            self._later(AUTO_CHECK_DELAY_MS + 3000, lambda: updater.checked_once or updater.check(manual=False))
        # The previous version stays as <name>.old until the new one has run for a while.
        self._later(30000, lambda: self_update_rules.cleanup_backups(self.root))
        self._later(60000, self.images.prune_disk)
        if updated_from:
            log.success("self-update", "Updated from {} to {}".format(updated_from, version))
            self.runtime.say_self_updated()  # also offers the package updates the last check found
        if open_manager or settings.open_manager_on_startup:
            self.open_manager("")
        if welcome:
            self.show_welcome()
        log.success("startup", "Runtime started ({})".format(qt_compat.binding_info()))

    def show_welcome(self):
        if not self.running:
            return False
        if not is_valid(self.welcome):
            self.welcome = WelcomeWindow(self.runtime, self.themes, self.open_manager, qt_compat.max_main_window())
            self.welcome.closed.connect(self._on_welcome_closed)
        self.welcome.show_centered()
        return True

    def _on_welcome_closed(self):
        welcome, self.welcome = self.welcome, None
        if is_valid(welcome):
            welcome.deleteLater()

    def stop(self):
        """Release every owned object; safe after a partial start and on repeated calls."""
        if self.stopped:
            return
        self.running = False
        for timer in self._timers:
            if is_valid(timer):
                timer.stop()
                timer.deleteLater()
        self._timers = []
        for toast in self._screen_toasts:
            if is_valid(toast):
                toast.hide()
                toast.deleteLater()
        self._screen_toasts = []
        self._destroy_window()
        if is_valid(self.welcome):
            self.welcome.hide()
            self.welcome.deleteLater()
        self.welcome = None
        if self.toolbar is not None:
            self.toolbar.stop()
            self.toolbar.deleteLater()
        if self.runtime is not None:
            for signal, slot in ((self.runtime.notify, self._notify_outside),
                                 (self.runtime.details_requested, self.open_details),
                                 (self.runtime.settings_changed, self._on_settings)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self.runtime.stop()
        if self.images is not None:
            self.images.stop()
        if self.themes is not None:
            self.themes.unbind_all()
        for owned in (self.images, self.runtime, self.themes):
            if is_valid(owned):
                owned.deleteLater()
        self.toolbar = self.images = self.runtime = self.themes = None
        self.stopped = True
        log.info("shutdown", "Runtime stopped")

    def _later(self, delay, callback):
        timer = QtCore.QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(callback)
        timer.start(delay)
        self._timers.append(timer)
        return timer

    # ----------------------------------------------------------------- Manager window
    def open_manager(self, target=""):
        """target: '' | 'discover' | 'installed' | 'updates' | 'settings:<page>'."""
        if not self.running:
            return False
        tab, page = (target or ""), ""
        if tab.startswith("settings:"):
            tab, page = "", tab.split(":", 1)[1]
        if self.window is None or not is_valid(self.window):
            self.window = ManagerWindow(self.runtime, self.themes, self.images, self.toolbar,
                                        qt_compat.max_main_window())
            self.window.closed.connect(self._on_window_closed)
            self.window.show_welcome = self.show_welcome  # Settings > About opens the welcome window
            self.window.show_restored()
            self.window.start(tab, page)
        else:
            if self.window.chrome.collapsed:
                self.window.chrome.restore()
            if self.window.isMinimized():
                self.window.showNormal()
            self.window.show()
            if tab:
                self.window.show_tab(tab)
            if page:
                self.window.open_settings(page)
        self.window.raise_()
        self.window.activateWindow()
        return True

    def open_details(self, guid):
        if self.open_manager(""):
            self.window.open_details(guid)

    def _on_window_closed(self):
        if not self._close_pending:
            self._close_pending = True
            self._later(0, self._destroy_window)  # closeEvent is still on the stack

    def _destroy_window(self):
        self._close_pending = False
        window = self.window
        self.window = None
        if is_valid(window):
            try:
                window.closed.disconnect(self._on_window_closed)
            except (RuntimeError, TypeError):
                pass
            if window.isVisible():  # a Runtime restart, not the user's close: keep the place and size
                window.save_geometry()
            window.chrome.stop()
            window.disconnect_all()
            window.hide()
            window.deleteLater()

    # ----------------------------------------------------------------- MaxPkg MaxScript global
    def maxscript_call(self):
        """Handle one call of the MaxScript `MaxPkg` facade (services/max_api.py) and store its reply."""
        try:
            command, argument = max_api.facade_request()
            reply = self._facade_command(command, argument)
        except Exception as error:  # noqa: BLE001 - a broken call must not raise into third-party MaxScript
            log.error("facade", "MaxPkg call failed: " + str(error))
            reply = False
        max_api.facade_reply(reply)

    def _facade_command(self, command, argument):
        if command == "isStarted":
            return self.running
        if not self.running:
            log.warning("facade", "MaxPkg.{} was called while the Package Manager is not running".format(command))
            return False
        if command == "shutdown":
            self._later(0, self.stop)  # never destroy the Controller inside its own call
            return True
        if command == "openManager":
            return self.open_manager("")
        if command == "welcome":
            return self.show_welcome()
        if command == "scan":
            self.runtime.scan()
            return True
        if command in ("packageInstalled", "packageRemoved"):
            own_operation = bool(self.runtime.operation)
            if not own_operation:  # our own install/uninstall rescans when the package script returns
                self.runtime.scan()
            present = self.runtime.package(argument) is not None
            if command == "packageInstalled" and present and not own_operation:  # ours checked the MZP before
                self._later(0, lambda: self.runtime.warn_if_incompatible(argument))
            return present if command == "packageInstalled" else not present
        if command == "install":
            # While another operation runs the package waits in the queue: a collection installer that calls
            # MaxPkg.install for each package gets every one installed, one after another.
            self.open_manager("")
            return True if self.runtime.request_install(argument) else "The package could not be installed."
        if command == "installMany":
            references = split_references(argument)
            if not references:
                log.warning("facade", "MaxPkg.installMany without packages: " + argument)
                return "No packages were given."
            log.info("installer", "{} packages requested: {}".format(len(references), ", ".join(references)))
            self.open_manager("")
            for reference in references:
                self.runtime.request_install(reference)
            return True
        if command == "installLayout":
            # A favorite collection arranged as a toolbar on maxpkg.dev: GUIDs and "divider" in the owner's order.
            entries = split_layout(argument)
            if not any(not is_divider(entry) for entry in entries):
                log.warning("facade", "MaxPkg.installLayout without packages: " + argument)
                return "No packages were given."
            log.info("installer", "Collection layout requested: " + "; ".join(entries))
            if self.runtime.request_layout(entries):
                self.open_manager("")  # its progress and summary, as for installMany
            return True
        if command == "uninstall":
            return bool(self.runtime.uninstall(argument))
        log.warning("facade", "Unknown MaxPkg call: " + command)
        return False

    # ----------------------------------------------------------------- feedback toasts
    SCREEN_TOAST_MARGIN = 16
    SCREEN_TOAST_GAP = 8
    SCREEN_TOAST_LIMIT = 4  # older ones close when more arrive

    def _manager_showing(self):
        window = self.window
        return (is_valid(window) and window.isVisible() and not window.isMinimized()
                and not window.chrome.collapsed)

    def feedback(self, text, kind="success", action=None):
        """What an action did, as a toast: in the Manager when it is open, else in the screen corner."""
        if self._manager_showing():
            self.window.notify(text, kind, action=action)
            return
        self.screen_toast(text, kind, action)

    def screen_toast(self, text, kind="info", action=None):
        """A toast in the bottom-right corner of 3ds Max's screen, above the taskbar, like a Windows notification.
        New toasts arrive at the bottom and push older ones up."""
        alive = [toast for toast in self._screen_toasts if is_valid(toast) and toast.isVisible()]
        while len(alive) >= self.SCREEN_TOAST_LIMIT:
            oldest = alive.pop(0)
            oldest.hide()
            oldest.deleteLater()
        toast = Toast(text, kind, self.themes, None, action=action)
        toast.expired.connect(self._place_screen_toasts)
        toast.fit()
        toast.show()
        self._screen_toasts = alive + [toast]
        self._place_screen_toasts()

    def _place_screen_toasts(self):
        self._screen_toasts = [toast for toast in self._screen_toasts if is_valid(toast) and toast.isVisible()]
        if not self._screen_toasts:
            return
        # The monitor that holds 3ds Max's main window (not the pointer's): its work area ends above the taskbar.
        anchor = qt_compat.max_main_window()
        center = anchor.frameGeometry().center() if is_valid(anchor) else QtGui.QCursor.pos()
        area = screen_at(center).availableGeometry()
        bottom = area.bottom() - self.SCREEN_TOAST_MARGIN
        for toast in reversed(self._screen_toasts):  # the newest sits lowest
            toast.fit()
            point = QtCore.QPoint(area.right() - self.SCREEN_TOAST_MARGIN - toast.width(), bottom - toast.height())
            toast.place(point)
            bottom = point.y() - self.SCREEN_TOAST_GAP

    # ----------------------------------------------------------------- messages
    def _notify_outside(self, text, kind, actions=None):
        """With the Manager closed, Runtime messages (installs, updates, errors) appear as screen toasts."""
        if self._manager_showing():
            return
        if not self.runtime.settings.notifications and kind != "error":
            return
        self.screen_toast(text, kind, actions)

    def _on_settings(self, area):
        if area == "developer":
            log.configure(self.runtime.paths.logs, self.runtime.settings.debug_logging)

    # ----------------------------------------------------------------- diagnostics
    def describe(self):
        """Owned-resource snapshot for tests."""
        main = qt_compat.max_main_window()
        toolbars = [bar for bar in main.findChildren(QtWidgets.QToolBar)
                    if bar.objectName() == "MaxPkgToolbar" and bar.isVisible()] if main else []
        windows = [widget for widget in QtWidgets.QApplication.topLevelWidgets()
                   if widget.objectName() in ("ManagerRoot", "MaxPkgFloatingToolbar") and widget.isVisible()]
        return {"running": self.running, "stopped": self.stopped, "toolbars": len(toolbars),
                "visible_windows": len(windows), "packages": len(self.runtime.packages) if self.runtime else 0,
                "pid": os.getpid()}
