"""MaxPkg service API: form fields and INI response parsing (port of core/repository.ms).

All endpoints are POST application/x-www-form-urlencoded; responses are INI text.
"""

import re

try:
    from urllib.parse import urlencode
except ImportError:  # pragma: no cover
    from urllib import urlencode

from .ini import IniDocument, to_float, to_int
from .packages import ChangelogEntry, Package, Screenshot, compatible, incompatibility

SORT_MODES = ("popular", "newest", "rating", "downloads", "name")
PAGE_SIZE = 24
_RESERVED = ("error", "meta", "catalog", "response", "changelog", "screenshots")


class ApiError(Exception):
    def __init__(self, code, message, request_id=""):
        Exception.__init__(self, message)
        self.code = code
        self.message = message
        self.request_id = request_id


class Collection:
    __slots__ = ("slug", "name", "description", "icon", "accent_color", "count")

    def __init__(self, slug, name, description="", icon="package", accent_color="", count=0):
        self.slug, self.name, self.description = slug, name, description
        self.icon, self.accent_color, self.count = icon or "package", accent_color, count


class Category:
    __slots__ = ("slug", "name", "description", "count")

    def __init__(self, slug, name, description="", count=0):
        self.slug, self.name, self.description, self.count = slug, name, description, count


class CatalogPage:
    def __init__(self):
        self.packages = []
        self.page = 1
        self.page_size = PAGE_SIZE
        self.total = 0
        self.total_pages = 0
        self.total_packages = -1  # all public packages, when the server reports it


class Request:
    """One API call: action name + form fields. `body()` is the urlencoded payload."""

    def __init__(self, action, fields):
        self.action = action
        self.fields = fields

    def url(self, endpoint):
        return endpoint.rstrip("/") + "/" + self.action

    def body(self):
        return urlencode(self.fields).encode("utf-8")


def _common(max_year, runtime_version, channel):
    return [("max3dsMax", str(max_year)), ("runtimeVersion", runtime_version), ("channel", channel)]


def catalog_request(max_year, runtime_version, channel="stable", query="", category="", sort="popular",
                    page=1, featured=False, collection=""):
    fields = [("query", query), ("category", "" if featured or collection else category),
              ("sort", sort if sort in SORT_MODES else "popular"), ("page", str(max(1, page))),
              ("pageSize", str(PAGE_SIZE))]
    if featured:
        fields.append(("featured", "true"))
    elif collection:
        fields.append(("collection", collection))
    return Request("catalog", fields + _common(max_year, runtime_version, channel))


def collections_request(max_year, runtime_version, channel="stable"):
    return Request("collections", _common(max_year, runtime_version, channel))


def categories_request(max_year, runtime_version, channel="stable"):
    return Request("categories", _common(max_year, runtime_version, channel))


def details_request(reference, max_year, runtime_version, channel="stable"):
    return Request("packages/details", [("package", reference)] + _common(max_year, runtime_version, channel))


def split_references(text):
    """Package references of one MaxPkg.installMany call: GUIDs, ids or links separated by ';', ',' or white space,
    without repeats. A MaxScript array that arrives as '#("a", "b")' loses its quotes and brackets too."""
    references = []
    for part in re.split(r'[;,\s"()#]+', text or ""):
        if part and part.lower() not in (known.lower() for known in references):
            references.append(part)
    return references


def resolve_request(reference, max_year, runtime_version, channel="stable"):
    return Request("packages/resolve", [("package", reference)] + _common(max_year, runtime_version, channel))


def updates_request(installed, max_year, runtime_version, channel="stable"):
    versions = ",".join(package.guid + "@" + package.version for package in installed)
    return Request("updates", [("packages", versions)] + _common(max_year, runtime_version, channel))


def _document(text):
    document = IniDocument.parse(text or "")
    code = document.get("error", "Code")
    message = document.get("error", "Message")
    if code or message:
        raise ApiError(code or "API_ERROR", message or "The MaxPkg service returned an error.",
                       document.get("error", "RequestId"))
    return document


def _changelog_items(document, section):
    entries = []
    for index in range(1, 201):
        prefix = str(index)
        text = document.get(section, prefix + "_text")
        if not text:
            break
        entries.append(ChangelogEntry(document.get(section, prefix + "_type", "Changed"), text))
    return entries


def _versioned_changelog(document):
    entries = []
    for index in range(1, to_int(document.get("changelog", "Count", "0")) + 1):
        group = "changelog_" + str(index)
        version = document.get_any(group, ("Version", "version"))
        date = document.get_any(group, ("ReleaseDate", "releaseDate"))
        for item in range(1, to_int(document.get(group, "Count", "0")) + 1):
            item_section = group + "_item_" + str(item)
            text = document.get_any(item_section, ("Text", "text", "Message", "message"))
            if text:
                kind = document.get_any(item_section, ("Type", "type", "ChangeType"), "Changed")
                entries.append(ChangelogEntry(kind, text, version, date))
    return entries


def _screenshots(document):
    shots = []
    for index in range(1, to_int(document.get("screenshots", "Count", "0")) + 1):
        section = "screenshot_" + str(index)
        url = document.get_any(section, ("Url", "url", "ImageUrl", "imageUrl"))
        if url:
            shots.append(Screenshot(url, document.get_any(section, ("ThumbnailUrl", "thumbnailUrl", "Thumbnail")),
                                    document.get_any(section, ("Title", "title")) or "Screenshot " + str(index),
                                    document.get_any(section, ("Caption", "caption")),
                                    to_int(document.get_any(section, ("SortOrder", "sortOrder"), "0"))))
    shots.sort(key=lambda shot: shot.sort_order)
    return shots


def _package(document, section, details=False):
    read = lambda *keys: document.get_any(section, keys)  # noqa: E731
    package = Package(is_remote=True, details_loaded=details)
    package.guid = read("Guid", "PackageGuid", "packageGuid", "guid")
    if not package.guid and section.lower() not in ("package", "details"):
        package.guid = section
    package.slug = read("Slug", "PackageSlug", "slug")
    package.name = read("Name", "PackageName", "name")
    package.button_name = read("ButtonName", "buttonName") or package.name
    package.version = read("Version", "LatestVersion", "version")
    package.latest_version = package.version
    package.developer = read("Developer", "DeveloperName", "developerName", "developer")
    package.description = read("Description", "description")
    # INI values are single lines: the server escapes line breaks as a literal backslash-n.
    package.full_description = read("FullDescription", "fullDescription", "FullText", "fullText").replace("\\n", "\n")
    package.category = read("Category", "category")
    package.documentation_url = read("Documentation", "DocumentationUrl", "documentation", "documentationUrl", "HelpUrl")
    package.homepage_url = read("Homepage", "HomepageUrl", "homepage", "homepageUrl")
    package.support_url = read("Support", "SupportUrl", "support", "supportUrl")
    package.purchase_url = read("PurchaseUrl", "purchaseUrl", "Purchase", "purchase")
    package.purchase_button_label = read("PurchaseButtonLabel", "purchaseButtonLabel")
    package.license_type = read("License", "LicenseType", "license")
    package.license_url = read("LicenseUrl", "licenseUrl")
    package.release_channel = read("Channel", "ReleaseChannel", "releaseChannel") or "stable"
    package.release_date = read("ReleaseDate", "releaseDate")
    package.min_max_version = read("Min3dsMax", "Minimum3dsMax", "min3dsMax")
    package.max_max_version = read("Max3dsMax", "Maximum3dsMax", "max3dsMax")
    package.packager_name = read("Packager", "packager")
    package.packager_version = read("PackagerVersion", "packagerVersion")
    package.runtime = read("Runtime", "runtime")
    package.entry = read("Entry", "entry")
    package.icon_url = read("PackageIconUrl", "packageIconUrl") or read("IconUrl", "iconUrl", "Icon")
    package.cover_image_url = read("CoverImageUrl", "coverImageUrl")
    package.download_url = read("DownloadUrl", "downloadUrl")
    package.rating = to_float(read("Rating", "rating") or "0")
    package.review_count = to_int(read("ReviewCount", "reviewCount") or "0")
    package.download_count = to_int(read("DownloadCount", "downloadCount") or "0")
    package.changelog = _changelog_items(document, section + ".changelog")
    if not package.changelog and details:
        package.changelog = _changelog_items(document, "changelog") or _versioned_changelog(document)
    for entry in package.changelog:
        entry.version = entry.version or package.version
        entry.release_date = entry.release_date or package.release_date
    if details:
        package.screenshots = _screenshots(document)
    return package


def _packages(document, details=False, require_name=True):
    found = []
    for section in document.sections():
        lowered = section.lower()
        if lowered in _RESERVED or lowered.startswith(("changelog_", "screenshot_")) or lowered.endswith(".changelog"):
            continue
        package = _package(document, section, details)
        if package.guid and (package.name or not require_name):
            found.append(package)
    return found


def parse_catalog(text, max_year):
    document = _document(text)
    page = CatalogPage()
    every = _packages(document)
    page.packages = [package for package in every if compatible(package, max_year)]
    meta = "catalog" if document.has_section("catalog") else "meta"
    page.page = to_int(document.get(meta, "Page", "1"), 1)
    page.page_size = to_int(document.get(meta, "PageSize", str(PAGE_SIZE)), PAGE_SIZE)
    page.total = max(0, to_int(document.get_any(meta, ("Total", "TotalItems", "Count"), str(len(every))), len(every))
                     - (len(every) - len(page.packages)))
    page.total_pages = to_int(document.get(meta, "TotalPages", "0"), 0)
    page.total_packages = to_int(document.get(meta, "TotalPackages", "-1"), -1)
    return page


def parse_collections(text):
    document = _document(text)
    collections = []
    for index in range(1, to_int(document.get("meta", "Count", "0")) + 1):
        section = "collection_" + str(index)
        slug = document.get_any(section, ("Slug", "slug"))
        name = document.get_any(section, ("Name", "name"))
        if slug and name:
            collections.append(Collection(slug, name, document.get_any(section, ("Description", "description")),
                                          document.get_any(section, ("Icon", "icon")),
                                          document.get_any(section, ("AccentColor", "accentColor")),
                                          to_int(document.get_any(section, ("Count", "count"), "0"))))
    return to_int(document.get("meta", "FeaturedCount", "0")), collections


def parse_categories(text):
    document = _document(text)
    categories = []
    for section in document.sections():
        if section.lower().startswith("category_"):
            slug = document.get_any(section, ("Slug", "slug"))
            name = document.get_any(section, ("Name", "name"))
            count = to_int(document.get_any(section, ("Count", "count"), "0"))
            if slug and name and count > 0:
                categories.append(Category(slug, name, document.get_any(section, ("Description", "description")), count))
    return categories


def parse_details(text, max_year):
    """The single package of a details/resolve response, or ApiError."""
    document = _document(text)
    packages = _packages(document, details=True)
    if not packages:
        raise ApiError("PACKAGE_NOT_FOUND", "The requested package could not be found.")
    package = packages[0]
    if not compatible(package, max_year):
        raise ApiError("INCOMPATIBLE_3DS_MAX", "This package does not run here. " + incompatibility(package, max_year))
    return package


def parse_updates(text, max_year):
    """{guid_lower: remote package} for every compatible package the server reports."""
    document = _document(text)
    return {package.guid.lower(): package for package in _packages(document, require_name=False)
            if compatible(package, max_year)}
