"""Check Updates checks the packages and the Package Manager itself, says one result and installs a newer Package
Manager (now, or after the running package operation). A real Runtime in a temporary folder; the network, the timers
and the final restart are fakes, so nothing is downloaded and nothing of this 3ds Max changes.

Needs Qt and runs inside 3ds Max through tests/run_unit.py; skipped where there is no Qt.
"""

import hashlib
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

try:
    from maxpkg_runtime.qt_compat import QtCore
    from maxpkg_runtime.domain import self_update as rules
    from maxpkg_runtime.domain.packages import Package
    from maxpkg_runtime.services import max_api, self_update
    from maxpkg_runtime.services import runtime as runtime_module
except ImportError:
    QtCore = None

ROOT = Path(__file__).resolve().parents[2]
GUID = "11111111-2222-3333-4444-555555555555"


def _from_this_repository():
    """run_unit.py imports this repository's modules; never patch the ones of a running Package Manager."""
    module = os.path.normcase(str(Path(runtime_module.__file__).resolve()))
    return module.startswith(os.path.normcase(str(ROOT)) + os.sep)


class FakeNetwork:
    """Keeps every request; the test answers them."""

    stopped = False

    def __init__(self):
        self.downloads = []   # [url, target, on_done]
        self.posts = []       # [request, on_done]

    def download(self, url, target, on_done, max_bytes=0):
        self.downloads.append([url, target, on_done])
        return len(self.downloads)

    def post(self, endpoint, request, parse, on_done):
        self.posts.append([request, on_done])
        return len(self.posts)

    def forget(self, ticket):
        pass

    def stop(self):
        self.stopped = True


class Remote:
    def __init__(self, version):
        self.version = version
        self.download_url = "https://maxpkg.dev/download/" + version
        self.download_sha256 = ""


@unittest.skipIf(QtCore is None, "Qt is not available")
class CheckUpdatesFlowTests(unittest.TestCase):
    def setUp(self):
        if not _from_this_repository():
            self.skipTest("the maxpkg_runtime modules are not this repository's (run tests/run_unit.py)")
        self.base = Path(tempfile.mkdtemp(prefix="maxpkg-check-updates-"))
        self.root = self.base / "installed"  # an installed copy: no .git, so it may update itself
        self.root.mkdir()
        temp = self.base / "max-temp"
        temp.mkdir()
        originals = (max_api.get_dir, max_api.max_year)
        max_api.get_dir = lambda name: str(temp) if name == "temp" else ""
        max_api.max_year = lambda: 2027
        self.addCleanup(lambda: (setattr(max_api, "get_dir", originals[0]), setattr(max_api, "max_year", originals[1])))
        self.runtime = runtime_module.Runtime(self.root, "2.1.1", "stable")
        self.runtime.network.stop()
        self.runtime.network = self.network = FakeNetwork()
        package = Package(guid=GUID, name="Scatter Tool", version="1.0.0")
        self.runtime.packages = [package]
        self.messages = []
        self.runtime.notify.connect(lambda text, kind, actions: self.messages.append((text, kind, actions)))
        # PySide2 cannot connect a signal to a list's own append (it hashes the receiver): lambdas.
        self.checking = []
        self.runtime.updates_checking_changed.connect(lambda checking: self.checking.append(checking))
        self.busy = []
        self.runtime.busy_changed.connect(lambda message: self.busy.append(message))
        updater = self.updater = self.runtime.self_update
        self.timers = []
        updater._later = lambda delay, callback: self.timers.append((delay, callback))
        self.restarts = []
        updater._restart = self.restarts.append

    def tearDown(self):
        self.runtime.stop()
        self.runtime.deleteLater()
        shutil.rmtree(str(self.base), ignore_errors=True)

    # ----------------------------------------------------------------- answers
    def release_feed(self, version):
        """A GitHub answer with one release of `version` (its files are answered by answer_install)."""
        tag = "v" + version
        return json.dumps([{"tag_name": tag, "prerelease": False, "draft": False, "body": "",
                            "assets": [{"name": name, "browser_download_url": rules.DOWNLOAD_PREFIX + tag + "/" + name}
                                       for name in (rules.PACKAGE_ASSET, rules.HASH_ASSET)]}])

    def answer_manager(self, version=None, error=None):
        url, target, on_done = self.network.downloads.pop(0)
        self.assertEqual(url, rules.RELEASES_URL)
        if error is not None:
            on_done(None, error)
            return
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        Path(target).write_text(self.release_feed(version or "2.1.1"), encoding="utf-8")
        on_done(target, None)

    def answer_packages(self, newer=None, error=None):
        _request, on_done = self.network.posts.pop(0)
        on_done(None, error) if error is not None else on_done({GUID.lower(): Remote(newer)} if newer else {}, None)

    def release_archive(self, version):
        folder = self.base / "release"
        (folder / "python" / "maxpkg_runtime").mkdir(parents=True)
        (folder / "assets").mkdir()
        for name in ("python/bootstrap.py", "python/maxpkg_runtime/__init__.py", "assets/icon.svg", "StartMaxPkg.ms",
                     "uninstall.ms"):
            (folder / name).write_text("# " + version, encoding="utf-8")
        (folder / "version.ini").write_text("[Runtime]\nVersion={}\nChannel=stable\n".format(version), encoding="utf-8")
        archive = self.base / "release.mzp"
        with zipfile.ZipFile(str(archive), "w") as handle:
            for path in folder.rglob("*"):
                if path.is_file():
                    handle.write(str(path), path.relative_to(folder).as_posix())
        return archive.read_bytes()

    def answer_install(self, version, digest=None, hash_error=None):
        """Answer the .sha256 and then the .mzp download of `version`."""
        data = self.release_archive(version)
        url, target, on_done = self.network.downloads.pop(0)
        self.assertTrue(url.endswith(rules.HASH_ASSET), url)
        Path(target).parent.mkdir(parents=True, exist_ok=True)
        if hash_error is not None:
            on_done(None, hash_error)
            return
        Path(target).write_text((digest or hashlib.sha256(data).hexdigest()) + "  " + rules.PACKAGE_ASSET + "\n",
                                encoding="utf-8")
        on_done(target, None)
        url, target, on_done = self.network.downloads.pop(0)
        self.assertTrue(url.endswith(rules.PACKAGE_ASSET), url)
        Path(target).write_bytes(data)
        on_done(target, None)

    def run_timers(self):
        while self.timers:
            _delay, callback = self.timers.pop(0)
            callback()

    # ----------------------------------------------------------------- checking state
    def test_checking_state_covers_both_checks_in_either_order(self):
        for first in ("packages", "manager"):
            self.messages, self.checking[:] = [], []
            self.assertTrue(self.runtime.check_all_updates())
            self.assertFalse(self.runtime.check_all_updates())  # a second click while it checks does nothing
            (self.answer_packages if first == "packages" else self.answer_manager)()
            self.assertTrue(self.runtime.checking_updates)
            self.assertEqual((self.checking, self.messages), ([True], []))
            (self.answer_manager if first == "packages" else self.answer_packages)()
            self.assertFalse(self.runtime.checking_updates)
            self.assertEqual(self.checking, [True, False])
            self.assertEqual(len(self.messages), 1)

    def test_everything_current_is_one_message(self):
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.1")
        self.assertEqual(self.messages, [("Everything is up to date.\n"
                                          "All packages and Package Manager 2.1.1 are the latest versions.", "success",
                                          [])])
        self.assertEqual(self.network.downloads, [])

    def test_package_updates_and_current_manager(self):
        self.runtime.check_all_updates()
        self.answer_manager("2.1.1")
        self.answer_packages(newer="1.1.0")
        text, kind, actions = self.messages[0]
        self.assertEqual(text, "An update is available.\nScatter Tool 1.0.0 → 1.1.0\nPackage Manager 2.1.1 is up to date.")
        self.assertEqual([label for label, _icon, _callback in actions], ["Update"])
        self.assertEqual(self.runtime.settings.package_update_cache, [GUID + "@1.1.0"])

    def test_no_installed_packages_still_checks_the_manager(self):
        self.runtime.packages = []
        self.assertTrue(self.runtime.check_all_updates())
        self.assertEqual(self.network.posts, [])
        self.answer_manager("2.1.1")
        self.assertEqual(self.messages[0][0], "Package Manager 2.1.1 is up to date.\nNo installed packages to check.")

    # ----------------------------------------------------------------- a newer Package Manager
    def test_newer_manager_is_installed_and_restarted(self):
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.2")
        self.assertEqual(self.busy, ["Updating Package Manager..."])
        self.assertEqual(self.messages, [("Package Manager 2.1.2 is available.\nInstalling it now.\n"
                                          "All packages are up to date.", "info", [])])
        self.answer_install("2.1.2")
        self.assertEqual(self.busy, ["Updating Package Manager...", ""])
        self.assertEqual(self.updater.state, "installing")
        self.run_timers()
        self.assertEqual(len(self.restarts), 1)
        self.assertEqual(rules.read_version_ini(Path(self.restarts[0]))[0], "2.1.2")
        self.assertEqual(len(self.messages), 1)  # the restart says the rest

    def test_newer_manager_waits_for_a_running_package_operation(self):
        self.runtime.operation = "Installing package..."
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.2")
        self.assertEqual(self.messages[0], ("Package Manager 2.1.2 is available.\n"
                                            "It will be installed when the current package operation ends.\n"
                                            "All packages are up to date.", "info", []))
        self.assertEqual(self.network.downloads, [])  # nothing starts while the operation runs
        self.assertEqual(self.timers[0][0], self_update.MANUAL_WAIT_MS)
        _delay, callback = self.timers.pop(0)
        callback()  # still running
        self.assertEqual((self.network.downloads, len(self.timers)), ([], 1))
        self.runtime.operation = ""
        self.runtime.install_queue = ["queued-package"]  # a queued install also keeps the restart away
        self.timers.pop(0)[1]()
        self.assertEqual(self.network.downloads, [])
        self.runtime.install_queue = []
        self.timers.pop(0)[1]()
        self.assertEqual(self.busy, ["Updating Package Manager..."])
        self.answer_install("2.1.2")
        self.run_timers()
        self.assertEqual(len(self.restarts), 1)

    def test_a_package_operation_that_never_ends_leaves_an_offer(self):
        self.runtime.operation = "Installing package..."
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.2")
        rounds = 0
        while self.timers and rounds < 1000:
            self.timers.pop(0)[1]()
            rounds += 1
        self.assertEqual(rounds, self_update.WAIT_LIMIT_MS // self_update.MANUAL_WAIT_MS)
        text, kind, actions = self.messages[-1]
        self.assertEqual((text, kind, [label for label, _icon, _callback in actions]),
                         ("Package Manager 2.1.2 is available.", "info", ["Update"]))
        self.assertEqual((self.network.downloads, self.restarts), ([], []))

    def test_source_checkout_only_says_that_an_update_exists(self):
        (self.root / ".git").mkdir()
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.2")
        self.assertEqual(self.messages[0][0], "Package Manager 2.1.2 is available.\n"
                                              "This copy runs from a source folder: update it with git.\n"
                                              "All packages are up to date.")
        self.assertEqual((self.network.downloads, self.busy, self.timers), ([], [], []))

    def test_checksum_that_cannot_be_downloaded(self):
        self.runtime.check_all_updates()
        self.answer_packages(newer="1.1.0")
        self.answer_manager("2.1.2")
        self.answer_install("2.1.2", hash_error=RuntimeError("Downloaded file is empty"))
        self.assertEqual(len(self.messages), 2)
        self.assertIn("An update for Scatter Tool is available too.", self.messages[0][0])  # shown before
        text, kind, actions = self.messages[1]
        self.assertEqual((text, kind), ("Package Manager could not be updated.\nThe checksum could not be downloaded.",
                                        "error"))
        self.assertEqual([label for label, _icon, _callback in actions], ["Try Again", "Download manually"])
        self.assertEqual((self.updater.state, self.runtime.operation, self.restarts), ("idle", "", []))
        self.assertEqual(self.busy, ["Updating Package Manager...", ""])
        opened = []
        original = max_api.open_url
        max_api.open_url = lambda url: opened.append(url) or True
        self.addCleanup(setattr, max_api, "open_url", original)
        actions[1][2]()  # Download manually: the newest release page, nothing is downloaded by us
        self.assertEqual(opened, ["https://github.com/maxpkg-dev/MaxPkg-Runtime-Manager-Qt/releases/latest"])
        self.assertEqual(self.network.downloads, [])
        actions[0][2]()  # Try Again downloads the checksum again
        self.assertTrue(self.network.downloads[0][0].endswith(rules.HASH_ASSET))

    def test_checksum_mismatch_installs_nothing(self):
        self.runtime.check_all_updates()
        self.answer_packages()
        self.answer_manager("2.1.2")
        self.answer_install("2.1.2", digest="0" * 64)
        text, kind, actions = self.messages[-1]
        self.assertEqual(text, "Package Manager could not be updated.\nThe downloaded update does not "
                               "match its published checksum and was not installed.")
        self.assertEqual([label for label, _icon, _callback in actions], ["Try Again", "Download manually"])
        self.assertEqual((self.restarts, self.timers), ([], []))
        self.assertEqual(list(Path(self.runtime.paths.downloads).glob("maxpkg-runtime-*")), [])

    # ----------------------------------------------------------------- failed checks
    def test_failed_manager_check_keeps_the_package_result(self):
        self.runtime.check_all_updates()
        self.answer_packages(newer="1.1.0")
        self.answer_manager(error=RuntimeError("offline"))
        text, kind, actions = self.messages[0]
        self.assertEqual(text, "An update is available.\nScatter Tool 1.0.0 → 1.1.0\n"
                               "The Package Manager update check failed.")
        self.assertEqual([label for label, _icon, _callback in actions], ["Update", "Try Again"])
        self.assertEqual(len(self.messages), 1)

    def test_failed_package_check_keeps_the_manager_result(self):
        self.runtime.check_all_updates()
        self.answer_manager("2.1.1")
        self.answer_packages(error=RuntimeError("offline"))
        self.assertEqual(self.messages[0][:2], ("The package update check failed.\n"
                                                "The previous result is still available.\n"
                                                "Package Manager 2.1.1 is up to date.", "error"))

    def test_failed_package_check_does_not_stop_the_manager_update(self):
        self.runtime.check_all_updates()
        self.answer_packages(error=RuntimeError("offline"))
        self.answer_manager("2.1.2")
        self.assertEqual(self.messages[0][0], "Package Manager 2.1.2 is available.\nInstalling it now.\n"
                                              "The package update check failed.")
        self.answer_install("2.1.2")
        self.run_timers()
        self.assertEqual(len(self.restarts), 1)

    def test_try_again_checks_both_again(self):
        self.runtime.check_all_updates()
        self.answer_packages(error=RuntimeError("offline"))
        self.answer_manager(error=RuntimeError("offline"))
        text, kind, actions = self.messages[0]
        self.assertEqual(kind, "error")
        self.assertTrue(text.startswith("The update check failed."))
        actions[0][2]()  # Try Again
        self.assertEqual((len(self.network.posts), len(self.network.downloads)), (1, 1))
        self.assertTrue(self.runtime.checking_updates)

    def test_running_self_update_leaves_only_the_package_result(self):
        self.updater.state = "downloading"
        self.runtime.check_all_updates()
        self.assertEqual(self.network.downloads, [])
        self.answer_packages()
        self.assertEqual(self.messages, [("All packages are up to date.", "success", [])])
        self.assertFalse(self.runtime.checking_updates)

    # ----------------------------------------------------------------- Check Manager Updates (toolbar menu)
    def test_manager_alone_current(self):
        self.assertTrue(self.runtime.check_manager_update())
        self.assertEqual(self.network.posts, [])  # the packages are not asked
        self.assertFalse(self.runtime.checking_updates)
        self.answer_manager("2.1.1")
        self.assertEqual(self.messages, [("Package Manager 2.1.1 is up to date.", "success", [])])

    def test_manager_alone_installs_a_newer_version(self):
        self.runtime.check_manager_update()
        self.answer_manager("2.1.2")
        self.assertEqual(self.messages, [("Package Manager 2.1.2 is available.\nInstalling it now.", "info", [])])
        self.answer_install("2.1.2")
        self.run_timers()
        self.assertEqual(len(self.restarts), 1)

    def test_manager_alone_waits_for_a_package_operation(self):
        self.runtime.install_queue = ["queued-package"]
        self.runtime.check_manager_update()
        self.answer_manager("2.1.2")
        self.assertEqual(self.messages[0][0], "Package Manager 2.1.2 is available.\n"
                                              "It will be installed when the current package operation ends.")
        self.assertEqual(self.network.downloads, [])
        self.runtime.install_queue = []
        self.timers.pop(0)[1]()
        self.assertTrue(self.network.downloads[0][0].endswith(rules.HASH_ASSET))

    def test_manager_alone_failure_tries_the_manager_again(self):
        self.runtime.check_manager_update()
        self.answer_manager(error=RuntimeError("offline"))
        text, kind, actions = self.messages[0]
        self.assertEqual((text, kind), ("The Package Manager update check failed.\n"
                                        "The MaxPkg release list could not be read.", "error"))
        actions[0][2]()  # Try Again: the Package Manager alone again, still no package request
        self.assertEqual((len(self.network.downloads), self.network.posts), (1, []))

    def test_manager_alone_is_refused_while_its_update_runs(self):
        self.updater.state = "downloading"
        self.assertFalse(self.runtime.check_manager_update())
        self.assertEqual((self.network.downloads, self.messages), ([], []))

    # ----------------------------------------------------------------- around it
    def test_automatic_check_after_start_still_waits_15_seconds(self):
        self.runtime.operation = "Updating package..."
        self.updater.check(manual=False)
        self.answer_manager("2.1.2")
        self.assertEqual(self.timers[0][0], self_update.WAIT_MS)
        self.assertEqual(self.messages, [])

    def test_settings_check_keeps_its_own_offer(self):
        self.updater.check(manual=True)
        self.answer_manager("2.1.2")
        text, kind, actions = self.messages[0]
        self.assertEqual((text, [label for label, _icon, _callback in actions]),
                         ("Package Manager 2.1.2 is available.\nYou have 2.1.1.", ["Update"]))
        self.assertEqual(self.busy, [])

    def test_after_restart_the_known_package_updates_are_offered(self):
        self.runtime.settings.package_update_cache = [GUID + "@1.1.0"]
        self.runtime._apply_known_updates()
        self.runtime.say_self_updated()
        text, kind, actions = self.messages[0]
        self.assertEqual((text, kind), ("Package Manager updated to 2.1.1.\n"
                                        "An update is available for Scatter Tool: 1.0.0 → 1.1.0.", "success"))
        self.assertEqual([label for label, _icon, _callback in actions], ["Update"])


if __name__ == "__main__":
    unittest.main()
