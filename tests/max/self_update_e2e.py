"""Self-update end to end, inside 3ds Max: python.ExecuteFile this file. Writes logs/self_update.txt.

Builds fake releases (the repository's own code, version 9.9.x, served as file:// URLs), copies the repository into a
copy of the installed folder (the 3ds Max temp folder's MaxPkg-Runtime-Manager-Qt) and lets that copy update itself:
  1. a release whose SHA-256 is wrong is refused and nothing changes;
  2. a good release is downloaded, verified, swapped in and started (new version, `.old` backup, data kept);
  3. a release whose code does not start is rolled back to the previous version.
The installed files are backed up first and put back at the end; the development Runtime is started again.
Do not run it while the owner uses the Package Manager: it restarts it several times.
"""

import hashlib
import json
import os
import runpy
import shutil
import sys
import time
import zipfile
from pathlib import Path

from PySide2 import QtCore, QtWidgets  # Max 2022-2024; Max 2025+ has PySide6

ROOT = Path(__file__).resolve().parent.parent.parent
SESSION = "_maxpkg_runtime_session"
LOG = []
PROGRAM = ("python", "assets", "StartMaxPkg.ms", "version.ini", "uninstall.ms")
app = QtWidgets.QApplication.instance()


def note(text):
    LOG.append(text)


def check(name, condition):
    note(("PASS " if condition else "FAIL ") + name)
    return bool(condition)


def pump(seconds=0.2, until=None, limit=40.0):
    end = time.monotonic() + (limit if until else seconds)
    while time.monotonic() < end:
        app.processEvents()
        if until is not None and until():
            return True
        time.sleep(0.02)
    return until is None


def owner():
    return getattr(sys.modules.get(SESSION), "owner", None)


def stop_owner():
    state = sys.modules.get(SESSION)
    if state is not None and getattr(state, "owner", None) is not None:
        state.owner.stop()
        state.owner = None


def launch(root, **options):
    boot = runpy.run_path(str(Path(root) / "python" / "bootstrap.py"), run_name="maxpkg_bootstrap")
    return boot["launch"](Path(root), **options)


def build_release(feed, version, broken=False, bad_hash=False):
    """A fake release folder: the MZP (zip of the repository's program files), its SHA-256 file and a feed JSON."""
    folder = feed / version
    folder.mkdir(parents=True, exist_ok=True)
    mzp = folder / "MaxPkg-Runtime-Manager-Qt.mzp"
    with zipfile.ZipFile(str(mzp), "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("mzp.run", "install.ms", "uninstall.ms", "StartMaxPkg.ms"):
            archive.write(str(ROOT / name), name)
        archive.writestr("version.ini", "[Runtime]\nVersion={}\nChannel=preview\n".format(version))
        for top in ("python", "assets"):
            for path in (ROOT / top).rglob("*"):
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    relative = path.relative_to(ROOT).as_posix()
                    if broken and relative == "python/maxpkg_runtime/controller.py":
                        archive.writestr(relative, "raise RuntimeError('this update is broken on purpose')\n")
                    else:
                        archive.write(str(path), relative)
    digest = "0" * 64 if bad_hash else hashlib.sha256(mzp.read_bytes()).hexdigest()
    sha = folder / "MaxPkg-Runtime-Manager-Qt.sha256"
    sha.write_text(digest + "  MaxPkg-Runtime-Manager-Qt.mzp\n", encoding="utf-8")
    url = lambda path: QtCore.QUrl.fromLocalFile(str(path)).toString()  # noqa: E731
    feed_file = folder / "releases.json"
    feed_file.write_text(json.dumps([{
        "tag_name": "v" + version, "prerelease": True, "draft": False, "body": "fake",
        "assets": [{"name": "MaxPkg-Runtime-Manager-Qt.mzp", "browser_download_url": url(mzp)},
                   {"name": "MaxPkg-Runtime-Manager-Qt.sha256", "browser_download_url": url(sha)}]}]), encoding="utf-8")
    return url(feed_file)


def installed_version(root):
    from maxpkg_runtime.domain import self_update as rules
    return rules.read_version_ini(root)[0]


def run():
    current = owner()
    if current is None:
        raise RuntimeError("Start the Package Manager first")
    data_root = Path(current.runtime.paths.data_root)
    sandbox = data_root  # the installed folder (code and data share it)
    work = ROOT / "logs" / "self-update-e2e"
    shutil.rmtree(str(work), ignore_errors=True)
    backup = work / "installed-backup"
    feed = work / "feed"
    backup.mkdir(parents=True)
    saved_settings = {name: getattr(current.runtime.settings, name) for name in
                      ("download_automatically", "auto_check_runtime", "last_runtime_check_utc")}
    for name in PROGRAM:  # the installed copy as it is now
        source = sandbox / name
        if source.is_dir():
            shutil.copytree(str(source), str(backup / name))
        elif source.is_file():
            shutil.copy2(str(source), str(backup / name))
    had_files = {name: (sandbox / name).exists() for name in PROGRAM}
    stop_owner()
    try:
        # Install the repository's current code into the sandbox as version 2.0.8 ("installed" state).
        for name in PROGRAM:
            target = sandbox / name
            if target.is_dir():
                shutil.rmtree(str(target))
            elif target.exists():
                target.unlink()
            if (ROOT / name).is_dir():
                shutil.copytree(str(ROOT / name), str(target), ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            elif (ROOT / name).is_file():
                shutil.copy2(str(ROOT / name), str(target))
        (sandbox / "version.ini").write_text("[Runtime]\nVersion=2.0.8\nChannel=preview\n", encoding="utf-8")
        for stale in ("python.old", "assets.old"):
            shutil.rmtree(str(sandbox / stale), ignore_errors=True)
        settings_file = sandbox / "settings.ini"
        settings_before = settings_file.read_bytes() if settings_file.exists() else b""

        # --- 1. wrong checksum
        feed_bad = build_release(feed / "bad", "9.9.9", bad_hash=True)
        os.environ["MAXPKG_RUNTIME_RELEASES_URL"] = feed_bad
        first = launch(sandbox, open_manager=False)
        check("sandbox runs the installed copy", first.runtime.version == "2.0.8" and not first.runtime.self_update.source_checkout())
        updater = first.runtime.self_update
        first.runtime.settings.download_automatically = False
        updater.check(manual=True)
        pump(until=lambda: updater.state == "idle")
        check("check finds 9.9.9", updater.available is not None and updater.available.version == "9.9.9")
        updater.install()
        pump(until=lambda: updater.state == "idle")
        check("wrong checksum refused", bool(updater.error) and installed_version(sandbox) == "2.0.8")
        check("operation lock released after a failure", first.runtime.operation == "")
        check("no leftovers after a refused update", not (sandbox / "python.old").exists())

        # --- 2. good release, installed automatically
        feed_good = build_release(feed / "good", "9.9.9")
        updater.releases_url = feed_good
        first.runtime.settings.download_automatically = False  # the startup check updates without asking
        first.runtime.settings.auto_check_runtime = True
        updater.check(manual=False)  # the automatic path: no click
        replaced = pump(until=lambda: owner() is not None and owner() is not first and owner().running)
        second = owner()
        check("automatic update restarted the Package Manager", replaced)
        if replaced:
            pump(0.6)
            check("new code runs as 9.9.9", second.runtime.version == "9.9.9")
            check("installed version.ini says 9.9.9", installed_version(sandbox) == "9.9.9")
            check("previous program kept as .old", (sandbox / "python.old").is_dir() and (sandbox / "assets.old").is_dir())
            check("settings.ini was not replaced", settings_file.read_bytes()[:2] == settings_before[:2] or not settings_before)
            check("old Runtime was stopped", first.stopped)

            # --- 3. a release that does not start rolls back
            feed_broken = build_release(feed / "broken", "9.9.10", broken=True)
            updater2 = second.runtime.self_update
            updater2.releases_url = feed_broken
            second.runtime.settings.download_automatically = False
            updater2.check(manual=False)
            pump(until=lambda: owner() is not second and owner() is not None and owner().running)
            third = owner()
            pump(0.6)
            check("broken update rolled back and the previous version runs", third is not None and third.running
                  and third.runtime.version == "9.9.9" and installed_version(sandbox) == "9.9.9")
            check("rolled-back code is the good code", (sandbox / "python" / "maxpkg_runtime" / "controller.py")
                  .read_text(encoding="utf-8").count("broken on purpose") == 0)
    finally:
        stop_owner()
        os.environ.pop("MAXPKG_RUNTIME_RELEASES_URL", None)
        for name in PROGRAM + ("python.old", "assets.old", "version.ini.old", "StartMaxPkg.ms.old", "uninstall.ms.old"):
            target = sandbox / name
            if target.is_dir():
                shutil.rmtree(str(target), ignore_errors=True)
            elif target.exists():
                target.unlink()
        for name in PROGRAM:  # put the installed copy back as it was
            if (backup / name).is_dir():
                shutil.copytree(str(backup / name), str(sandbox / name))
            elif (backup / name).is_file():
                shutil.copy2(str(backup / name), str(sandbox / name))
        launch(ROOT, open_manager=False)  # the development Runtime, as before the test
        restored = owner()
        if restored is not None:
            for name, value in saved_settings.items():
                setattr(restored.runtime.settings, name, value)
            restored.runtime.save_settings("updates")
        check("development Runtime runs again", restored is not None and restored.running)
        check("installed files restored", all((sandbox / name).exists() == had_files[name] for name in PROGRAM))
    summary = "SELF-UPDATE {} ({} checks)".format("OK" if all(line.startswith("PASS") for line in LOG) else "FAILED", len(LOG))
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "self_update.txt").write_text(summary + "\n" + "\n".join(LOG) + "\n", encoding="utf-8")
    shutil.rmtree(str(work), ignore_errors=True)


try:
    run()
except Exception as error:  # noqa: BLE001 - recorded for the reader of logs/self_update.txt
    import traceback
    (ROOT / "logs").mkdir(exist_ok=True)
    (ROOT / "logs" / "self_update.txt").write_text("SELF-UPDATE CRASHED\n" + "\n".join(LOG) + "\n"
                                                    + traceback.format_exc(), encoding="utf-8")
    raise
