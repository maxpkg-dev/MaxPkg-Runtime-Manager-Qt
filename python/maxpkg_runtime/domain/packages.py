"""Package records, manifest scanning and version helpers (port of core/scanner.ms and updater.ms)."""

import os
import re
import zipfile

from .ini import IniDocument, decode, to_bool, to_float, to_int

MZP_MANIFEST_MAX_BYTES = 1024 * 1024


class ChangelogEntry:
    __slots__ = ("change_type", "text", "version", "release_date")

    def __init__(self, change_type="Changed", text="", version="", release_date=""):
        self.change_type = change_type or "Changed"
        self.text = text
        self.version = version
        self.release_date = release_date


class Screenshot:
    __slots__ = ("url", "thumbnail_url", "title", "caption", "sort_order")

    def __init__(self, url="", thumbnail_url="", title="", caption="", sort_order=0):
        self.url = url
        self.thumbnail_url = thumbnail_url or url
        self.title = title
        self.caption = caption
        self.sort_order = sort_order


class Package:
    """One package: installed (from manifest.ini) or remote (from the catalog API)."""

    def __init__(self, **values):
        self.guid = ""
        self.slug = ""
        self.name = ""
        self.button_name = ""
        self.version = ""
        self.developer = ""
        self.description = ""
        self.full_description = ""
        self.category = ""
        self.documentation_url = ""
        self.homepage_url = ""
        self.support_url = ""
        self.purchase_url = ""
        self.purchase_button_label = ""
        self.license_type = ""
        self.license_url = ""
        self.release_channel = "stable"
        self.release_date = ""
        self.min_max_version = ""
        self.max_max_version = ""
        self.packager_name = ""
        self.packager_version = ""
        self.runtime = ""
        self.entry = ""
        self.icon_file = ""      # local icon (installed)
        self.icon_url = ""       # remote icon
        self.cover_image_url = ""
        self.download_url = ""
        self.rating = 0.0
        self.review_count = 0
        self.download_count = 0
        self.install_path = ""
        self.manifest_path = ""
        self.uninstall_script = "uninstall.ms"
        self.toolbar_visible = True  # developer's showInToolbar
        self.toolbar_order = 0
        self.changelog = []
        self.screenshots = []
        self.is_remote = False
        self.details_loaded = False
        self.update_available = False
        self.latest_version = ""
        for key, value in values.items():
            setattr(self, key, value)

    @property
    def display_name(self):
        return self.name or self.slug or self.guid

    @property
    def initials(self):
        words = [word for word in re.split(r"[\s_\-]+", self.display_name) if word]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    def is_free_with_donation(self):
        return bool(self.purchase_url) and (self.purchase_button_label or "").strip().lower() in ("donate", "")

    def purchase_label(self):
        return (self.purchase_button_label or "").strip() or "Buy"

    def same(self, reference):
        lowered = (reference or "").strip().lower()
        return lowered in (self.guid.lower(), self.slug.lower(), self.name.lower()) and lowered != ""


def slug_from_name(name):
    return re.sub(r"[\s_]+", "-", name.strip().lower())


def read_manifest(manifest_path):
    """Package from manifest.ini, or None when required fields are missing."""
    document = IniDocument.load(manifest_path)
    section = "package"
    read = lambda *keys, **kw: document.get_any(section, keys, kw.get("default", ""))  # noqa: E731
    install_path = os.path.dirname(os.path.abspath(manifest_path))
    package = Package()
    package.manifest_path = manifest_path
    package.install_path = install_path
    package.guid = read("packageGuid", "Guid", "guid")
    package.name = read("name", "Name")
    package.slug = read("slug", "Slug", default=slug_from_name(package.name))
    package.button_name = read("buttonName", "ButtonName", default=package.name)
    package.version = read("version", "Version")
    package.developer = read("developerName", "Developer", "developer")
    package.description = read("description", "Description")
    package.documentation_url = read("documentation", "Documentation", "documentationUrl", "help", "Help", "helpUrl")
    package.homepage_url = read("homepage", "Homepage", "homepageUrl")
    package.support_url = read("support", "Support", "supportUrl")
    package.purchase_url = read("purchase", "Purchase", "purchaseUrl", "PurchaseUrl")
    package.purchase_button_label = read("purchaseButtonLabel", "PurchaseButtonLabel", default="Buy")
    package.license_type = read("license", "License")
    package.license_url = read("licenseUrl", "LicenseUrl")
    package.release_channel = read("releaseChannel", "ReleaseChannel", default="stable")
    package.release_date = read("releaseDate", "ReleaseDate")
    package.min_max_version = read("min3dsMax", "Min3dsMax", "minimum3dsMax")
    package.max_max_version = read("max3dsMax", "Max3dsMax", "maximum3dsMax")
    package.packager_name = read("packager", "Packager")
    package.packager_version = read("packagerVersion", "PackagerVersion")
    package.entry = read("entry", "Entry")
    package.runtime = read("runtime", "Runtime")
    if not package.runtime and package.entry:
        package.runtime = "Python" if package.entry.lower().endswith(".py") else "MaxScript"
    icon = read("icon", "Icon")
    if icon:
        package.icon_file = os.path.join(install_path, icon.replace("/", os.sep))
    package.toolbar_visible = to_bool(read("showInToolbar", "ToolbarVisible", default="true"), True)
    package.toolbar_order = to_int(read("toolbarOrder", "ToolbarOrder", default="0"), 0)
    package.uninstall_script = read("uninstallScript", "Uninstall", default="uninstall.ms")
    for index in range(1, 201):
        text = document.get("changelog", str(index) + "_text")
        if not text:
            break
        package.changelog.append(ChangelogEntry(document.get("changelog", str(index) + "_type", "Changed"),
                                                text, package.version, package.release_date))
    missing = [label for label, value in (("Guid", package.guid), ("Name", package.name), ("Version", package.version),
                                          ("Runtime", package.runtime), ("Entry", package.entry)) if not value]
    if missing:
        raise ValueError("missing " + ", ".join(missing))
    return package


def read_mzp_manifest(mzp_path):
    """Name, GUID and 3ds Max range from the manifest.ini inside an MZP (a zip), read before its installer runs.
    None when the file is no zip or has no manifest: such a package is checked after it is installed."""
    try:
        with zipfile.ZipFile(mzp_path) as archive:
            candidates = [member for member in archive.infolist()
                          if member.filename.replace("\\", "/").rsplit("/", 1)[-1].lower() == "manifest.ini"
                          and member.file_size <= MZP_MANIFEST_MAX_BYTES]
            if not candidates:
                return None
            nearest = min(candidates, key=lambda member: member.filename.replace("\\", "/").count("/"))
            document = IniDocument.parse(decode(archive.read(nearest)))
    except (OSError, zipfile.BadZipFile, RuntimeError, ValueError):
        return None
    read = lambda *keys: document.get_any("package", keys, "")  # noqa: E731
    package = Package()
    package.guid = read("packageGuid", "Guid", "guid")
    package.name = read("name", "Name")
    package.min_max_version = read("min3dsMax", "Min3dsMax", "minimum3dsMax")
    package.max_max_version = read("max3dsMax", "Max3dsMax", "maximum3dsMax")
    return package


def manifest_paths(root):
    """manifest.ini directly in `root` and in each first-level subfolder."""
    found = []
    if not root or not os.path.isdir(root):
        return found
    direct = os.path.join(root, "manifest.ini")
    if os.path.isfile(direct):
        found.append(direct)
    try:
        entries = sorted(os.listdir(root))
    except OSError:
        return found
    for entry in entries:
        candidate = os.path.join(root, entry, "manifest.ini")
        if os.path.isfile(candidate):
            found.append(candidate)
    return found


def scan(roots, log=None):
    """Installed packages from all roots. Broken manifests and duplicate GUIDs are skipped."""
    packages = []
    seen_manifests = set()
    seen_guids = set()
    for root in roots:
        for manifest_path in manifest_paths(root):
            key = os.path.normcase(os.path.abspath(manifest_path))
            if key in seen_manifests:
                continue
            seen_manifests.add(key)
            try:
                package = read_manifest(manifest_path)
            except (OSError, ValueError) as error:
                if log:
                    log("Skipped manifest " + manifest_path + ": " + str(error))
                continue
            if package.guid.lower() in seen_guids:
                if log:
                    log("Duplicate package GUID skipped: " + package.guid)
                continue
            seen_guids.add(package.guid.lower())
            packages.append(package)
    return packages


def version_key(text):
    parts = []
    for part in re.split(r"[.\-+]", text or ""):
        parts.append(int(part) if part.isdigit() else -1)
    while len(parts) < 4:
        parts.append(0)
    return parts


def is_newer(candidate, installed):
    return version_key(candidate) > version_key(installed)


def compatible(package, max_year):
    """min3dsMax <= max_year <= max3dsMax, like the maxpkg.dev API; an empty or zero bound is open."""
    minimum = to_int(package.min_max_version, 0)
    maximum = to_int(package.max_max_version, 0)
    return (minimum == 0 or max_year >= minimum) and (maximum == 0 or max_year <= maximum)


def supported_versions(package):
    """'2024–2027', '2024 and newer', '2027 and older', or '' when the package names no versions."""
    minimum = to_int(package.min_max_version, 0)
    maximum = to_int(package.max_max_version, 0)
    if minimum and maximum:
        return str(minimum) if minimum == maximum else "{}–{}".format(minimum, maximum)
    if minimum:
        return "{} and newer".format(minimum)
    if maximum:
        return "{} and older".format(maximum)
    return ""


def incompatibility(package, max_year):
    """User-facing reason why the package does not run in this 3ds Max, or '' when it does."""
    if compatible(package, max_year):
        return ""
    return "It supports 3ds Max {}. This is 3ds Max {}.".format(supported_versions(package), max_year)


def ordered_for_toolbar(packages, order, is_hidden):
    """Visible toolbar packages: saved order first, then the rest by ToolbarOrder and name."""
    visible = [package for package in packages if package.toolbar_visible and not is_hidden(package.guid)]
    index = {guid.lower(): position for position, guid in enumerate(order)}
    ordered = [package for package in visible if package.guid.lower() in index]
    ordered.sort(key=lambda package: index[package.guid.lower()])
    rest = [package for package in visible if package.guid.lower() not in index]
    rest.sort(key=lambda package: (package.toolbar_order, package.name.lower()))
    return ordered + rest


# A toolbar divider: an entry of the saved toolbar order between package GUIDs (any number, toolbar only).
DIVIDER = "divider"


def is_divider(entry):
    return entry.lower() == DIVIDER


def normalized_order(packages, order):
    """Saved order with unknown GUIDs dropped and newly discovered packages appended; dividers are kept."""
    known = {package.guid.lower(): package.guid for package in packages}
    result = []
    for guid in order:
        if is_divider(guid):
            result.append(DIVIDER)
            continue
        canonical = known.get(guid.lower())
        if canonical and canonical not in result:
            result.append(canonical)
    for package in packages:
        if package.guid not in result:
            result.append(package.guid)
    return result


def with_brand_divider(order):
    """The order with a divider first, so the maxpkg button stands apart from the packages."""
    order = list(order)
    if not order or not is_divider(order[0]):
        order.insert(0, DIVIDER)
    return order


def merge_visible_order(saved_order, visible_new_order, visible_guids):
    """Apply a reordering of the visible subset while keeping hidden packages in their slots.

    Dividers move with the new order when it contains them (the toolbar); otherwise (the Manager, which never
    shows dividers) they keep their slots like hidden packages.
    """
    visible = {guid.lower() for guid in visible_guids}
    dividers_move = any(is_divider(entry) for entry in visible_new_order)
    queue = list(visible_new_order)
    merged = []
    for guid in saved_order:
        if guid.lower() in visible or (dividers_move and is_divider(guid)):
            if queue:
                merged.append(queue.pop(0))
        else:
            merged.append(guid)
    merged.extend(queue)
    return merged


def toolbar_entries(packages, order, is_hidden):
    """The toolbar line: visible packages (Package objects) and dividers (DIVIDER) in saved order, then visible
    packages missing from the order."""
    visible = ordered_for_toolbar(packages, order, is_hidden)
    by_guid = {package.guid.lower(): package for package in visible}
    entries, placed = [], set()
    for entry in order:
        if is_divider(entry):
            entries.append(DIVIDER)
        elif entry.lower() in by_guid and entry.lower() not in placed:
            entries.append(by_guid[entry.lower()])
            placed.add(entry.lower())
    entries.extend(package for package in visible if package.guid.lower() not in placed)
    return entries


def compact_number(value):
    """1139 -> '1.1K', 2500000 -> '2.5M' (one decimal, dropped when zero)."""
    value = max(0, int(value or 0))
    thousands = round(value / 100.0) / 10.0
    if value >= 1000000 or thousands >= 1000:  # 999950 rounds to 1000K: show it as 1M
        return "{:g}M".format(round(value / 100000.0) / 10.0)
    if value >= 1000:
        return "{:g}K".format(thousands)
    return str(value)


__all__ = ["Package", "ChangelogEntry", "Screenshot", "scan", "read_manifest", "read_mzp_manifest", "is_newer", "compatible",
           "supported_versions", "incompatibility", "ordered_for_toolbar", "normalized_order", "with_brand_divider", "merge_visible_order", "compact_number", "to_float", "DIVIDER",
           "is_divider", "toolbar_entries"]
