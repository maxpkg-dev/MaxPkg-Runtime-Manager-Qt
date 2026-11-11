"""Package Manager self-update, pure Python: choose a GitHub release, unpack the MZP safely and swap the program
files with a rollback.

The idea is the one of the MaxScript Runtime (compare versions and channels, download, copy over the installed
folder except the user's data, restart), with its weak points fixed: the update is a published release (not the
`main` branch), the archive must match the published SHA-256, nothing is written outside the staging folder
before the checks pass, and a failed swap restores the previous files.
"""

import json
import os
import shutil
import time
import zipfile
from pathlib import Path

from .ini import IniDocument
from .packages import is_newer, version_key

REPOSITORY = "maxpkg-dev/MaxPkg-Runtime-Manager-Qt"
RELEASES_URL = "https://api.github.com/repos/" + REPOSITORY + "/releases?per_page=15"
DOWNLOAD_PREFIX = "https://github.com/" + REPOSITORY + "/releases/download/"  # nothing else is ever downloaded
LATEST_RELEASE_URL = "https://github.com/" + REPOSITORY + "/releases/latest"  # a failed update: install it by hand
PACKAGE_ASSET = "MaxPkg-Runtime-Manager-Qt.mzp"
HASH_ASSET = "MaxPkg-Runtime-Manager-Qt.sha256"

# What an update replaces. settings.ini, logs, cache and downloads belong to the user and stay.
REPLACED_FOLDERS = ("python", "assets")
REPLACED_FILES = ("StartMaxPkg.ms", "version.ini", "uninstall.ms")
BACKUP_SUFFIX = ".old"

MAX_UNPACKED_BYTES = 150 * 1024 * 1024
MAX_UNPACKED_FILES = 5000


class UpdateError(Exception):
    """An update step failed; the message is safe to show (no paths)."""


class ReleaseInfo:
    def __init__(self, version, tag, prerelease, notes, package_url, hash_url):
        self.version = version
        self.tag = tag
        self.prerelease = prerelease
        self.notes = notes
        self.package_url = package_url
        self.hash_url = hash_url


def normalize_version(text):
    """'v2.0.8' -> '2.0.8'."""
    text = (text or "").strip()
    return text[1:] if text[:1] in ("v", "V") else text


def parse_releases(text, download_prefix=DOWNLOAD_PREFIX):
    """Installable releases from the GitHub API reply: not drafts, with the MZP and its SHA-256 file attached, both
    from this repository's releases (`download_prefix`)."""
    try:
        data = json.loads(text)
    except ValueError:
        raise UpdateError("The release list could not be read.")
    if not isinstance(data, list):
        raise UpdateError("The release list could not be read.")
    releases = []
    for entry in data:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        assets = {}
        for asset in entry.get("assets") or []:
            if isinstance(asset, dict) and asset.get("name") and asset.get("browser_download_url"):
                assets[asset["name"]] = asset["browser_download_url"]
        version = normalize_version(entry.get("tag_name", ""))
        if not version or PACKAGE_ASSET not in assets or HASH_ASSET not in assets:
            continue
        if not (assets[PACKAGE_ASSET].startswith(download_prefix) and assets[HASH_ASSET].startswith(download_prefix)):
            continue
        if not all(part.isdigit() for part in version.split(".")):
            continue
        releases.append(ReleaseInfo(version, entry.get("tag_name", ""), bool(entry.get("prerelease")),
                                    entry.get("body") or "", assets[PACKAGE_ASSET], assets[HASH_ASSET]))
    return releases


def select_update(releases, current_version, channel):
    """The newest release above `current_version`, or None. The `stable` channel ignores pre-releases; any other
    channel (preview) takes pre-releases and stable releases alike."""
    stable_only = (channel or "stable").strip().lower() == "stable"
    newest = None
    for release in releases:
        if stable_only and release.prerelease:
            continue
        if not is_newer(release.version, current_version):
            continue
        if newest is None or version_key(release.version) > version_key(newest.version):
            newest = release
    return newest


def parse_sha256(text, file_name=PACKAGE_ASSET):
    """The hash from a `sha256sum` style file ('<hex>  <name>') or a bare hash; '' when there is none."""
    fallback = ""
    for line in (text or "").splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        candidate = parts[0].lower()
        if len(candidate) != 64 or any(char not in "0123456789abcdef" for char in candidate):
            continue
        name = parts[-1].lstrip("*") if len(parts) > 1 else ""
        if name == file_name:
            return candidate
        if not name and not fallback:
            fallback = candidate
    return fallback


def read_version_ini(folder):
    """(Version, Channel) of a version.ini; ('', '') when it is missing."""
    try:
        document = IniDocument.load(Path(folder) / "version.ini")
    except OSError:
        return "", ""
    return (document.get("Runtime", "Version") or ""), (document.get("Runtime", "Channel") or "")


def is_source_checkout(root):
    """A git checkout or development folder is updated with git, never overwritten by an update."""
    root = Path(root)
    return any((root / name).exists() for name in (".git", ".github", "tests"))


# ----------------------------------------------------------------------------- unpacking
def safe_extract(archive_path, destination):
    """Unpack a ZIP/MZP into `destination`, refusing entries that leave it and absurd sizes."""
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    base = os.path.normcase(os.path.realpath(str(destination)))
    try:
        archive = zipfile.ZipFile(str(archive_path))
    except (zipfile.BadZipFile, OSError):
        raise UpdateError("The downloaded update is not a valid archive.")
    with archive:
        members = archive.infolist()
        if len(members) > MAX_UNPACKED_FILES or sum(member.file_size for member in members) > MAX_UNPACKED_BYTES:
            raise UpdateError("The downloaded update is larger than allowed.")
        for member in members:
            target = os.path.realpath(os.path.join(str(destination), member.filename))
            if os.path.normcase(target) != base and not os.path.normcase(target).startswith(base + os.sep):
                raise UpdateError("The downloaded update contains an unsafe path.")
        for member in members:
            target = Path(os.path.join(str(destination), member.filename))
            if member.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, open(str(target), "wb") as sink:
                shutil.copyfileobj(source, sink)


def find_package_root(extracted):
    """The folder of an unpacked release that holds the program (the MZP keeps it at the top level)."""
    extracted = Path(extracted)
    candidates = [extracted] + sorted(path for path in extracted.iterdir() if path.is_dir())
    for candidate in candidates:
        if ((candidate / "StartMaxPkg.ms").is_file() and (candidate / "version.ini").is_file()
                and (candidate / "python" / "bootstrap.py").is_file()
                and (candidate / "python" / "maxpkg_runtime" / "__init__.py").is_file()
                and (candidate / "assets").is_dir()):
            return candidate
    raise UpdateError("The downloaded update does not contain the Package Manager.")


# ----------------------------------------------------------------------------- swapping files
def _retry(action, attempts=6, delay=0.25):
    """Windows keeps a folder busy for a moment after its files were read (antivirus, indexer)."""
    for attempt in range(attempts):
        try:
            return action()
        except OSError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


def _remove(path):
    path = Path(path)
    if path.is_dir():
        _retry(lambda: shutil.rmtree(str(path)))
    elif path.exists():
        _retry(lambda: path.unlink())


class Swap:
    """What install_staged() changed, so a failure (or a start failure of the new code) can be undone."""

    def __init__(self, root):
        self.root = Path(root)
        self.steps = []  # (name, "folder"|"file", moved_old, put_new)

    def rollback(self):
        for name, kind, moved_old, put_new in reversed(self.steps):
            current = self.root / name
            backup = self.root / (name + BACKUP_SUFFIX)
            if kind == "folder":
                if put_new:
                    _remove(current)
                if moved_old and backup.exists():
                    _retry(lambda: os.rename(str(backup), str(current)))
            elif moved_old and backup.exists():
                _retry(lambda: shutil.copyfile(str(backup), str(current)))
        self.steps = []


def install_staged(root, staged):
    """Put the staged program in place of the installed one. Folders are renamed (the old one stays as `<name>.old`
    until cleanup_backups), files are backed up and replaced. On any error everything is restored and the error
    raised. Returns the Swap, whose rollback() undoes a completed swap."""
    root, staged = Path(root), Path(staged)
    for name in REPLACED_FOLDERS:
        if not (staged / name).is_dir():
            raise UpdateError("The update is incomplete.")
    swap = Swap(root)
    try:
        for name in REPLACED_FOLDERS:
            current, backup = root / name, root / (name + BACKUP_SUFFIX)
            _remove(backup)
            step = [name, "folder", False, False]
            swap.steps.append(tuple(step))
            index = len(swap.steps) - 1
            if current.exists():
                _retry(lambda: os.rename(str(current), str(backup)))
                step[2] = True
                swap.steps[index] = tuple(step)
            _retry(lambda: os.rename(str(staged / name), str(current)))
            step[3] = True
            swap.steps[index] = tuple(step)
        for name in REPLACED_FILES:
            source = staged / name
            if not source.is_file():
                continue
            current, backup = root / name, root / (name + BACKUP_SUFFIX)
            moved = False
            if current.exists():
                _retry(lambda: shutil.copyfile(str(current), str(backup)))
                moved = True
            swap.steps.append((name, "file", moved, True))
            temporary = root / (name + ".new")
            _retry(lambda: shutil.copyfile(str(source), str(temporary)))
            _retry(lambda: os.replace(str(temporary), str(current)))
    except Exception:
        swap.rollback()
        raise
    return swap


def cleanup_backups(root):
    """Delete the `.old` copies left by the last update. Best effort; returns how many were removed."""
    root = Path(root)
    removed = 0
    for name in REPLACED_FOLDERS + REPLACED_FILES:
        backup = root / (name + BACKUP_SUFFIX)
        if backup.exists():
            try:
                _remove(backup)
                removed += 1
            except OSError:
                pass
    for leftover in root.glob("*.new"):
        try:
            leftover.unlink()
        except OSError:
            pass
    return removed


def clear_staging(downloads):
    """Delete update leftovers (archives, hash files, unpacked folders) from the downloads folder."""
    downloads = Path(downloads)
    if not downloads.is_dir():
        return
    for path in downloads.glob("maxpkg-runtime-*"):
        try:
            _remove(path)
        except OSError:
            pass
