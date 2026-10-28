"""Runtime settings in the exact settings.ini format of the MaxScript Runtime (same sections and keys).

Every field has a safe default; invalid values are normalized instead of failing. Saving is
atomic and immediate, like the original (no Save/Cancel anywhere in the UI).
"""

import os

from .ini import IniDocument, to_bool, to_int

UPDATE_FREQUENCIES = (1, 6, 12, 24, 48, 168)
DOCK_POSITIONS = ("top", "bottom", "left", "right", "floatinghorizontal", "floatingvertical")
DEFAULT_ENDPOINT = "https://maxpkg.dev/api/runtime/v1/"

# attribute, section, key, kind, default, allowed values (for "choice")
_FIELDS = (
    ("package_roots", "Packages", "Roots", "list", (), None),
    ("hidden_packages", "Toolbar", "Hidden", "list", (), None),
    ("toolbar_order", "Toolbar", "Order", "list", (), None),
    ("toolbar_visible", "Toolbar", "Visible", "bool", True, None),
    ("toolbar_title_mode", "Toolbar", "TitleMode", "choice", "packageName", ("packageName", "buttonName")),
    ("toolbar_subtitle_mode", "Toolbar", "SubtitleMode", "choice", "version", ("none", "version", "developer")),
    ("toolbar_button_size", "Toolbar", "ButtonSize", "choice", "medium", ("icon", "small", "medium", "large")),
    ("toolbar_dock_position", "Toolbar", "DockPosition", "choice", "top", DOCK_POSITIONS),
    ("toolbar_density", "Toolbar", "Density", "choice", "regular", ("regular", "compact")),
    ("toolbar_icon_size", "Toolbar", "IconSize", "choice", "large", ("small", "medium", "large")),
    ("floating_horizontal_x", "Toolbar", "FloatingHorizontalX", "int", -1, None),
    ("floating_horizontal_y", "Toolbar", "FloatingHorizontalY", "int", -1, None),
    ("floating_vertical_x", "Toolbar", "FloatingVerticalX", "int", -1, None),
    ("floating_vertical_y", "Toolbar", "FloatingVerticalY", "int", -1, None),
    ("toolbar_theme", "Toolbar", "Theme", "str", "default", None),
    ("update_frequency_hours", "Updates", "FrequencyHours", "frequency", 24, None),
    ("notifications", "Updates", "Notifications", "bool", True, None),
    ("auto_check_packages", "Updates", "AutoCheckPackages", "bool", True, None),
    ("auto_check_runtime", "Updates", "AutoCheckRuntime", "bool", True, None),
    ("download_automatically", "Updates", "DownloadAutomatically", "bool", False, None),
    ("last_package_check_utc", "Updates", "LastPackageCheckUtc", "str", "", None),
    ("package_update_cache", "Updates", "PackageCache", "list", (), None),
    ("manager_last_selection", "Manager", "LastSelection", "str", "", None),
    ("manager_last_tab", "Manager", "LastTab", "choice", "installed", ("discover", "installed", "updates")),
    ("manager_first_open_completed", "Manager", "FirstOpenCompleted", "bool", False, None),
    ("manager_sort", "Manager", "Sort", "choice", "toolbar", ("toolbar", "name", "developer", "version")),
    ("manager_filter", "Manager", "Filter", "choice", "all", ("all", "toolbar", "hidden")),
    ("manager_full_cards", "Manager", "FullCards", "bool", False, None),
    ("manager_position_x", "Manager", "PositionX", "int", -1, None),
    ("manager_position_y", "Manager", "PositionY", "int", -1, None),
    ("manager_width", "Manager", "Width", "int", 900, None),
    ("manager_height", "Manager", "Height", "int", 650, None),
    ("manager_maximized", "Manager", "Maximized", "bool", False, None),
    ("manager_mini_x", "Manager", "MiniX", "int", -1, None),
    ("manager_mini_y", "Manager", "MiniY", "int", -1, None),
    ("settings_x", "Manager", "SettingsX", "int", -1, None),
    ("settings_y", "Manager", "SettingsY", "int", -1, None),
    ("settings_width", "Manager", "SettingsWidth", "int", 0, None),
    ("settings_height", "Manager", "SettingsHeight", "int", 0, None),
    ("settings_page", "Manager", "SettingsPage", "choice", "general",
     ("general", "updates", "toolbar", "themes", "developer", "endpoint", "about", "uninstall")),
    ("language", "General", "Language", "str", "English", None),
    ("manager_theme", "General", "ManagerTheme", "str", "default", None),
    ("auto_start", "General", "AutoStart", "bool", True, None),
    ("open_manager_on_startup", "General", "OpenManagerOnStartup", "bool", False, None),
    ("developer_mode", "Developer", "Enabled", "bool", False, None),
    ("debug_logging", "Developer", "DebugLogging", "bool", False, None),
    ("api_endpoint", "Endpoint", "apiEndpoint", "endpoint", "", None),
)


def normalize_endpoint(text):
    """'' (use the built-in endpoint) or an http(s) URL ending with '/'."""
    endpoint = (text or "").strip()
    if not endpoint:
        return ""
    if not endpoint.lower().startswith(("http://", "https://")):
        return ""
    return endpoint if endpoint.endswith("/") else endpoint + "/"


def _choice(text, allowed, default):
    lowered = str(text).strip().lower()
    if lowered in ("topcompact",):
        return "top"
    if lowered in ("bottomcompact",):
        return "bottom"
    for option in allowed:
        if option.lower() == lowered:
            return option
    return default


class Settings:
    """Plain attributes named after the original fields (snake_case)."""

    def __init__(self, path=""):
        self.path = str(path)
        for attribute, _section, _key, _kind, default, _allowed in _FIELDS:
            setattr(self, attribute, list(default) if isinstance(default, tuple) else default)

    @property
    def effective_endpoint(self):
        return self.api_endpoint or DEFAULT_ENDPOINT

    @classmethod
    def load(cls, path):
        settings = cls(path)
        document = IniDocument.load(path)
        for attribute, section, key, kind, default, allowed in _FIELDS:
            raw = document.get(section, key, None)
            if raw is None:
                continue
            setattr(settings, attribute, _read(kind, raw, default, allowed))
        if document.get("Manager", "SortVersion", "1") in ("", "1") and document.has_section("Manager"):
            settings.manager_sort = "toolbar"  # same one-time migration as the MaxScript Runtime
        if not document.get("Toolbar", "Density", ""):
            raw_position = document.get("Toolbar", "DockPosition", "").lower()
            if raw_position in ("topcompact", "bottomcompact") or document.get("Toolbar", "ButtonSize", "") == "icon":
                settings.toolbar_density = "compact"
        return settings

    def save(self):
        document = IniDocument.load(self.path)
        for attribute, section, key, kind, default, allowed in _FIELDS:
            document.set(section, key, _write(kind, getattr(self, attribute), default, allowed))
        document.set("Manager", "SortVersion", "2")
        document.save(self.path)

    def is_hidden(self, guid):
        lowered = guid.lower()
        return any(hidden.lower() == lowered for hidden in self.hidden_packages)

    def set_hidden(self, guid, hidden):
        lowered = guid.lower()
        self.hidden_packages = [entry for entry in self.hidden_packages if entry.lower() != lowered]
        if hidden:
            self.hidden_packages.append(guid)


def _read(kind, raw, default, allowed):
    if kind == "list":
        return [part for part in raw.split("|") if part.strip()]
    if kind == "bool":
        return to_bool(raw, default)
    if kind == "int":
        return to_int(raw, default)
    if kind == "frequency":
        value = to_int(raw, default)
        return value if value in UPDATE_FREQUENCIES else 24
    if kind == "choice":
        return _choice(raw, allowed, default)
    if kind == "endpoint":
        return normalize_endpoint(raw)
    return raw


def _write(kind, value, default, allowed):
    if kind == "list":
        return "|".join(value)
    if kind == "bool":
        return "true" if value else "false"
    if kind == "frequency":
        return str(value if value in UPDATE_FREQUENCIES else 24)
    if kind == "choice":
        return _choice(value, allowed, default)
    if kind == "endpoint":
        return normalize_endpoint(value)
    return str(value)


def load_or_migrate(path, legacy_path=""):
    """Load settings; on first run copy them from the MaxScript Runtime's settings.ini."""
    if not os.path.isfile(str(path)) and legacy_path and os.path.isfile(str(legacy_path)):
        settings = Settings.load(legacy_path)
        settings.path = str(path)
        settings.save()
        return settings, True
    return Settings.load(path), False
