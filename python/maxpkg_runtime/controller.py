"""Lifecycle owner of one Runtime instance: services, toolbar, Manager window, tray messages.

Created passively by bootstrap.py; `start()` acquires everything, `stop()` releases it in reverse
order and is safe to call twice or after a partial start. Closing the Manager window only
destroys the window; the Runtime (toolbar, update checks) keeps running until the next restart.
"""

import configparser
import os

from . import qt_compat
from .qt_compat import QtCore, QtWidgets, is_valid
from .services import log
from .services.images import ImageService
from .services.runtime import Runtime
from .ui.manager_window import ManagerWindow
from .ui.theme import ThemeService
from .ui.toolbar import ToolbarController

AUTO_CHECK_DELAY_MS = 4000


def read_version(root):
    parser = configparser.ConfigParser()
    try:
        parser.read(str(root / "version.ini"), encoding="utf-8")
        return parser.get("Runtime", "Version", fallback="0.0.0"), parser.get("Runtime", "Channel", fallback="stable")
    except configparser.Error:
        return "0.0.0", "stable"


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
        self.tray = None
        self._timers = []
        self._close_pending = False

    # ----------------------------------------------------------------- lifecycle
    def start(self, open_manager=True):
        if qt_compat.application() is None:
            raise RuntimeError("No QApplication: run the MaxPkg Runtime inside 3ds Max")
        version, channel = read_version(self.root)
        self.themes = ThemeService(self.root)
        self.runtime = Runtime(self.root, version, channel)
        self.images = ImageService(self.runtime.network, self.runtime.paths.image_cache)
        settings = self.runtime.settings
        settings.manager_theme = self.themes.set_manager(settings.manager_theme)
        self.runtime.start()
        self.runtime.notify.connect(self._notify_outside)
        self.runtime.settings_changed.connect(self._on_settings)
        self.toolbar = ToolbarController(self.runtime, self.themes, self.images, self.open_manager,
                                         self.open_details)
        self.toolbar.start()
        self.running = True
        if settings.auto_check_packages and self.runtime.automatic_check_due():
            self._later(AUTO_CHECK_DELAY_MS, lambda: self.runtime.check_updates(manual=False))
        self._later(60000, self.images.prune_disk)
        if open_manager or settings.open_manager_on_startup:
            self.open_manager("")
        log.info("startup", "Runtime started ({})".format(qt_compat.binding_info()))

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
        self._destroy_window()
        if self.toolbar is not None:
            self.toolbar.stop()
            self.toolbar.deleteLater()
        if self.runtime is not None:
            for signal, slot in ((self.runtime.notify, self._notify_outside),
                                 (self.runtime.settings_changed, self._on_settings)):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self.runtime.stop()
        if self.images is not None:
            self.images.stop()
        if is_valid(self.tray):
            self.tray.hide()
            self.tray.deleteLater()
        if self.themes is not None:
            self.themes.unbind_all()
        for owned in (self.images, self.runtime, self.themes):
            if is_valid(owned):
                owned.deleteLater()
        self.toolbar = self.images = self.runtime = self.themes = self.tray = None
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

    # ----------------------------------------------------------------- messages
    def _notify_outside(self, text, kind):
        """When the Manager is closed, show Runtime messages as a Windows notification instead."""
        if is_valid(self.window) and self.window.isVisible():
            return
        if not self.runtime.settings.notifications and kind != "error":
            return
        if not QtWidgets.QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self.tray is None:
            self.tray = QtWidgets.QSystemTrayIcon(QtWidgets.QApplication.windowIcon())
            self.tray.setToolTip("MaxPkg")
        self.tray.show()
        icon = {"error": QtWidgets.QSystemTrayIcon.Critical, "warning": QtWidgets.QSystemTrayIcon.Warning}.get(
            kind, QtWidgets.QSystemTrayIcon.Information)
        self.tray.showMessage("MaxPkg", text, icon, 5000)

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
