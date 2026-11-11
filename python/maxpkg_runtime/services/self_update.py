"""Package Manager self-update: look for a newer GitHub release, download and verify it, then restart on it.

All network work runs through the Runtime's NetworkService (Qt event loop, no Python threads); unpacking and the
file swap are short and happen on the main thread. The swap itself is done by python/entry.py (outside the
reloadable package), which stops this Runtime, replaces the program files and starts the new code; it undoes the
swap if the new code does not start. See domain/self_update.py for the rules.
"""

import datetime
import os
import runpy
import shutil

from ..domain import integrity
from ..domain import self_update as rules
from ..qt_compat import QtCore, Signal
from . import log, max_api, network

RESTART_DELAY_MS = 300
WAIT_MS = 15000            # an automatic update looks this often whether a running package operation ended ...
WAIT_LIMIT_MS = 300000     # ... for up to 5 minutes, then it only offers the update
MANUAL_WAIT_MS = 2000      # after Check Updates the user is waiting: look more often

# What check(report=...) hands to its caller.
CURRENT = "current"
AVAILABLE = "available"    # self.available holds the release
FAILED = "failed"


def _read_text(path):
    with open(path, "rb") as stream:
        return stream.read().decode("utf-8", "replace")


def _remove(path):
    if not path:  # a failed download hands over no file
        return
    try:
        if os.path.isdir(path):
            shutil.rmtree(path)
        elif os.path.exists(path):
            os.remove(path)
    except OSError:
        pass


class SelfUpdater(QtCore.QObject):
    changed = Signal()  # state, result or last-check text changed (Settings > Updates redraws)

    def __init__(self, runtime):
        QtCore.QObject.__init__(self, runtime)
        self.runtime = runtime
        self.state = "idle"        # idle | checking | downloading | installing
        self.available = None      # rules.ReleaseInfo of a newer release, or None
        self.error = ""            # why the last check/update failed ('' = fine)
        self.checked_once = False  # a check finished in this session
        # The Controller sets this: is the Manager
        # window open (it is opened again after the restart).
        self.manager_is_open = lambda: False
        # Only this repository's releases. The in-Max test sets these two to a local feed on this object.
        self.releases_url = rules.RELEASES_URL
        self.download_prefix = rules.DOWNLOAD_PREFIX
        self._later = QtCore.QTimer.singleShot  # (ms, callback); unit tests run the waits at once
        self._stopped = False

    # ----------------------------------------------------------------- facts
    def source_checkout(self):
        return rules.is_source_checkout(self.runtime.root)

    def can_install(self):
        return not self.source_checkout()

    def check_due(self):
        """Every start looks for a new version (the interval only rules the package checks)."""
        return bool(self.runtime.settings.auto_check_runtime)

    def stop(self):
        self._stopped = True

    # ----------------------------------------------------------------- check
    def check(self, manual=False, report=None):
        """Ask GitHub for the newest release. `manual`: answer with a toast even when nothing is new.
        `report`: Check Updates, which also checks the packages, gets CURRENT, AVAILABLE or FAILED instead of any
        toast and decides itself what to say and whether to install. False when a check or update already runs."""
        if self._stopped or self.state != "idle":
            return False
        self.state = "checking"
        self.error = ""
        self.changed.emit()
        target = os.path.join(self.runtime.paths.downloads, "maxpkg-runtime-releases.json")
        self.runtime.network.download(self.releases_url, target,
                                      lambda path, error: self._checked(path, error, manual, report),
                                      max_bytes=4 * 1024 * 1024)
        return True

    def _checked(self, path, error, manual, report=None):
        if self._stopped:
            return
        self.state = "idle"
        releases = []
        if error is None:
            try:
                releases = rules.parse_releases(_read_text(path), self.download_prefix)
            except (OSError, rules.UpdateError) as problem:
                error = problem
        _remove(path)
        if error is not None:
            self.error = "The update check failed. Try again later."
            log.warning("self-update", "Release check failed: " + (str(error) if isinstance(error, rules.UpdateError)
                                                                  else network.describe(error)))
            if manual and report is None:
                self.runtime.say("The Package Manager update check failed.\nThe MaxPkg release list could not be "
                                 "read.", "error", [("Try Again", "refresh-cw", lambda: self.check(True))])
            self.changed.emit()
            if report is not None:
                report(FAILED)
            return
        self.checked_once = True
        self.runtime.settings.last_runtime_check_utc = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.0000000Z")
        self.runtime.save_settings("updates")
        self.available = rules.select_update(releases, self.runtime.version, self.runtime.channel)
        if self.available is None:
            log.info("self-update", "Package Manager {} is current".format(self.runtime.version))
            if manual and report is None:
                self.runtime.say("Package Manager {} is up to date.".format(self.runtime.version), "success")
        else:
            log.info("self-update", "Package Manager {} is available (running {})".format(
                self.available.version, self.runtime.version))
            if report is None:
                self._offer(manual)
        self.changed.emit()
        if report is not None:
            report(CURRENT if self.available is None else AVAILABLE)

    def _offer(self, manual):
        update = self.available
        if not self.can_install():
            if manual:
                self.runtime.say("Package Manager {} is available.\nThis copy runs from a source folder: update it "
                                 "with git.".format(update.version), "info")
            return
        if not manual and self.runtime.settings.auto_check_runtime:
            # The startup check updates without asking; it only waits for a running package operation to end.
            self._install_when_idle(update)
        else:
            self.runtime.say("Package Manager {} is available.\nYou have {}.".format(update.version, self.runtime.version),
                             "info", [("Update", "download", self.install)])

    def busy_with_packages(self):
        """A package operation runs or waits: the Package Manager must not restart now."""
        return bool(self.runtime.operation or self.runtime.install_queue)

    def install_when_idle(self, interval=MANUAL_WAIT_MS):
        """Install the available release as soon as no package operation runs (Check Updates found it)."""
        if self.available is None or not self.can_install():
            return False
        self._install_when_idle(self.available, interval=interval)
        return True

    def _install_when_idle(self, update, waited=0, interval=WAIT_MS):
        if self._stopped or self.available is not update or self.state != "idle":
            return
        if self.busy_with_packages():
            if waited >= WAIT_LIMIT_MS:
                log.warning("self-update", "Automatic update postponed: a package operation keeps running")
                self.runtime.say("Package Manager {} is available.".format(update.version), "info",
                                 [("Update", "download", self.install)])
                return
            self._later(interval, lambda: self._install_when_idle(update, waited + interval, interval))
            return
        log.info("self-update", "Updating automatically to " + update.version)
        self.install()

    # ----------------------------------------------------------------- install
    def install(self):
        """Download, verify and unpack the available release, then restart the Package Manager on it."""
        update = self.available
        if self._stopped or self.state != "idle" or update is None:
            return False
        if not self.can_install():
            self.runtime.say("This copy runs from a source folder: update it with git.", "info")
            return False
        if not self.runtime._begin("Updating Package Manager..."):
            return False
        self.state = "downloading"
        self.error = ""
        self.changed.emit()
        folder = self.runtime.paths.downloads
        names = "maxpkg-runtime-" + update.version
        paths = {"hash": os.path.join(folder, names + ".sha256"), "package": os.path.join(folder, names + ".mzp"),
                 "unpacked": os.path.join(folder, names + "-unpacked")}
        rules.clear_staging(folder)

        def fail(message, detail=""):
            if detail:
                log.error("self-update", "Update to {} failed: {}".format(update.version, detail))
            for path in paths.values():
                _remove(path)
            self.state = "idle"
            self.error = message
            self.runtime._finish()
            self.runtime.say("Package Manager could not be updated.\n" + message, "error",
                             [("Try Again", "refresh-cw", self.install),
                              ("Download manually", "external-link", self.open_latest_release)])
            self.changed.emit()

        def hash_downloaded(path, error):
            if self._stopped:
                return
            if error is not None:
                fail("The checksum could not be downloaded.", network.describe(error))
                return
            expected = rules.parse_sha256(_read_text(path))
            if not expected:
                fail("The published checksum is missing or unreadable.", "no SHA-256 in the release")
                return
            self.runtime.network.download(update.package_url, paths["package"],
                                          lambda target, problem: package_downloaded(target, problem, expected))

        def package_downloaded(path, error, expected):
            if self._stopped:
                return
            if error is not None:
                fail("The update could not be downloaded.", network.describe(error))
                return
            result, actual = integrity.verify_file(path, expected)
            if result != integrity.MATCH:
                fail("The downloaded update does not match its published checksum and was not installed.",
                     "SHA-256 {}: expected {}, got {}".format(result, expected, actual))
                return
            try:
                rules.safe_extract(path, paths["unpacked"])
                staged = rules.find_package_root(paths["unpacked"])
                version, _channel = rules.read_version_ini(staged)
            except (OSError, rules.UpdateError) as problem:
                fail(str(problem) if isinstance(problem, rules.UpdateError) else "The update could not be unpacked.",
                     str(problem))
                return
            if version != update.version:
                fail("The downloaded update has an unexpected version.", "release {} contains {}".format(
                    update.version, version))
                return
            self.state = "installing"
            self.runtime._finish()
            self.changed.emit()
            log.info("self-update", "Update {} verified and unpacked; restarting".format(version))
            self._later(RESTART_DELAY_MS, lambda: self._restart(str(staged)))

        self.runtime.network.download(update.hash_url, paths["hash"], hash_downloaded)
        return True

    def open_latest_release(self):
        """The newest release on GitHub in the browser, for an update that failed: its MZP can be installed by hand
        (dragged into a viewport)."""
        log.info("self-update", "Opened the latest release page for a manual download")
        return max_api.open_url(rules.LATEST_RELEASE_URL)

    def _restart(self, staged):
        """Hand over to python/entry.py: it stops this Runtime (and so this object), swaps the files and starts the
        new code. Nothing here may touch the Runtime afterwards."""
        if self._stopped:
            return
        reopen = bool(self.manager_is_open())
        entry = runpy.run_path(os.path.join(str(self.runtime.root), "python", "entry.py"), run_name="maxpkg_entry")
        entry["apply_update"](staged, reopen)
