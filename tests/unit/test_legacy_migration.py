"""What carries over from the MaxScript Runtime 1.x: its settings.ini and its packages. Run with tests/run_unit.py."""

import os
import shutil
import tempfile
import unittest

from maxpkg_runtime.domain.packages import scan
from maxpkg_runtime.domain.settings import load_or_migrate

GUID_A = "29f8c475-803a-4ddf-892c-9c9a9fa59d1f"
GUID_B = "4442c4f9-33c1-4c23-83a4-0db11ee5bab4"
GUID_C = "647fbcec-f70e-4305-92df-4f545e13354b"
# As Runtime 1.2.0 writes it (setINISetting: UTF-16 with a byte order mark).
LEGACY_SETTINGS = """[Packages]
Roots=D:\\MyScripts
[Toolbar]
Hidden={b}
Order={a}|{b}|{c}
Visible=false
TitleMode=buttonName
SubtitleMode=developer
ButtonSize=small
DockPosition=floatingvertical
Density=compact
IconSize=medium
FloatingHorizontalX=120
FloatingHorizontalY=240
FloatingVerticalX=300
FloatingVerticalY=400
Theme=forest-green
[Updates]
FrequencyHours=168
Notifications=false
AutoCheckPackages=false
AutoCheckRuntime=false
DownloadAutomatically=true
LastPackageCheckUtc=2026-10-20T10:00:00.0000000Z
PackageCache={a}@9.9.9
[Manager]
LastSelection={a}
LastTab=discover
FirstOpenCompleted=true
Sort=developer
SortVersion=2
Filter=hidden
FullCards=true
PositionX=50
PositionY=60
Width=1234
Height=777
[General]
Language=English
ManagerTheme=midnight-blue
AutoStart=false
OpenManagerOnStartup=true
[Developer]
Enabled=true
DebugLogging=true
[Endpoint]
apiEndpoint=https://dev.maxpkg.dev/api/runtime/v1/
""".format(a=GUID_A, b=GUID_B, c=GUID_C)
MANIFEST = """[Package]
Guid={guid}
Name={name}
Version=1.0.0
Runtime=MaxScript
Entry=run.ms
"""


class LegacyMigrationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxpkg-legacy-")
        self.legacy = os.path.join(self.folder, "legacy-settings.ini")
        with open(self.legacy, "w", encoding="utf-16") as stream:
            stream.write(LEGACY_SETTINGS)
        self.target = os.path.join(self.folder, "new", "settings.ini")
        os.makedirs(os.path.dirname(self.target))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_every_setting_carries_over(self):
        settings, migrated = load_or_migrate(self.target, self.legacy)
        self.assertTrue(migrated)
        expected = {
            "package_roots": ["D:\\MyScripts"], "hidden_packages": [GUID_B], "toolbar_order": [GUID_A, GUID_B, GUID_C],
            "toolbar_visible": False, "toolbar_title_mode": "buttonName", "toolbar_subtitle_mode": "developer",
            "toolbar_button_size": "small", "toolbar_dock_position": "floatingvertical", "toolbar_density": "compact",
            "toolbar_icon_size": "medium", "floating_horizontal_x": 120, "floating_horizontal_y": 240,
            "floating_vertical_x": 300, "floating_vertical_y": 400, "toolbar_theme": "forest-green",
            "update_frequency_hours": 168, "notifications": False, "auto_check_packages": False,
            "auto_check_runtime": False, "download_automatically": True,
            "last_package_check_utc": "2026-10-20T10:00:00.0000000Z", "package_update_cache": [GUID_A + "@9.9.9"],
            "manager_last_selection": GUID_A, "manager_last_tab": "discover", "manager_first_open_completed": True,
            "manager_sort": "developer", "manager_filter": "hidden", "manager_full_cards": True,
            "manager_position_x": 50, "manager_position_y": 60, "manager_width": 1234, "manager_height": 777,
            "manager_theme": "midnight-blue", "auto_start": False, "open_manager_on_startup": True,
            "developer_mode": True, "debug_logging": True,
            "api_endpoint": "https://dev.maxpkg.dev/api/runtime/v1/"}
        for name, value in expected.items():
            found = getattr(settings, name)
            self.assertEqual(list(found) if isinstance(found, (list, tuple)) else found, value, name)
        self.assertTrue(os.path.isfile(self.target))

    def test_settings_survive_the_first_save(self):
        settings, _migrated = load_or_migrate(self.target, self.legacy)
        settings.save()
        again, migrated = load_or_migrate(self.target, self.legacy)
        self.assertFalse(migrated)
        self.assertEqual(list(again.toolbar_order), [GUID_A, GUID_B, GUID_C])
        self.assertEqual(list(again.hidden_packages), [GUID_B])
        self.assertEqual(again.toolbar_theme, "forest-green")
        self.assertEqual(again.manager_theme, "midnight-blue")

    def test_existing_settings_are_not_overwritten(self):
        with open(self.target, "w", encoding="utf-8") as stream:
            stream.write("[General]\nManagerTheme=light-studio\n")
        settings, migrated = load_or_migrate(self.target, self.legacy)
        self.assertFalse(migrated)
        self.assertEqual(settings.manager_theme, "light-studio")

    def test_old_compact_dock_positions(self):
        with open(self.legacy, "w", encoding="utf-16") as stream:
            stream.write("[Toolbar]\nDockPosition=topcompact\nButtonSize=medium\n")
        settings, _migrated = load_or_migrate(self.target, self.legacy)
        self.assertEqual((settings.toolbar_dock_position, settings.toolbar_density), ("top", "compact"))

    def test_packages_are_found_where_the_old_runtime_installed_them(self):
        packages_root = os.path.join(self.folder, "MaxPkg-Runtime-Manager", "data", "packages")
        for guid, name in ((GUID_A, "One"), (GUID_B, "Two")):
            folder = os.path.join(packages_root, name)
            os.makedirs(folder)
            with open(os.path.join(folder, "manifest.ini"), "w", encoding="utf-8") as stream:
                stream.write(MANIFEST.format(guid=guid, name=name))
        found = scan([packages_root], lambda _message: None)
        self.assertEqual(sorted(package.guid for package in found), sorted([GUID_A, GUID_B]))


if __name__ == "__main__":
    unittest.main()
