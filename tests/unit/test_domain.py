"""Pure tests for domain/ (no Qt, no pymxs). Run with tests/run_unit.py (works inside or outside Max)."""

import os
import shutil
import tempfile
import unittest
import zipfile

from maxpkg_runtime.domain import api, markdown
from maxpkg_runtime.domain.messages import without_links
from maxpkg_runtime.domain.ini import IniDocument
from maxpkg_runtime.domain.packages import (DIVIDER, ChangelogEntry, Package, changelog_versions, compact_number,
                                            compatible, incompatibility, is_newer,
                                            merge_visible_order, normalized_order, ordered_for_toolbar,
                                            read_mzp_manifest, scan, supported_versions, toolbar_entries,
                                            with_brand_divider)
from maxpkg_runtime.domain.settings import Settings, load_or_migrate, normalize_endpoint


class IniTests(unittest.TestCase):
    def test_case_insensitive_and_first_key_wins(self):
        document = IniDocument.parse("[Toolbar]\nVisible=true\nvisible=false\n[toolbar]\nOrder=a|b\n")
        self.assertEqual(document.get("TOOLBAR", "visible"), "true")
        self.assertEqual(document.get("toolbar", "ORDER"), "a|b")

    def test_utf16_round_trip(self):
        folder = tempfile.mkdtemp()
        try:
            path = os.path.join(folder, "settings.ini")
            document = IniDocument()
            document.set("General", "Language", "Français ✓")  # non-ASCII must survive UTF-16
            document.save(path)
            with open(path, "rb") as stream:
                self.assertTrue(stream.read(2) in (b"\xff\xfe", b"\xfe\xff"))
            self.assertEqual(IniDocument.load(path).get("general", "language"), "Français ✓")
        finally:
            shutil.rmtree(folder)


class SettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.folder)

    def test_defaults_and_normalization(self):
        path = os.path.join(self.folder, "settings.ini")
        with open(path, "w", encoding="utf-16") as stream:
            stream.write("[Toolbar]\nDockPosition=TopCompact\nButtonSize=huge\n[Updates]\nFrequencyHours=5\n"
                         "[Manager]\nSortVersion=2\nSort=name\n")
        settings = Settings.load(path)
        self.assertEqual(settings.toolbar_dock_position, "top")
        self.assertEqual(settings.toolbar_density, "compact")
        self.assertEqual(settings.toolbar_button_size, "icon")  # an unknown value falls back to the default
        self.assertEqual(settings.update_frequency_hours, 24)
        self.assertEqual(settings.manager_sort, "name")
        self.assertTrue(settings.toolbar_visible)

    def test_migration_copies_legacy_values(self):
        legacy = os.path.join(self.folder, "legacy.ini")
        with open(legacy, "w", encoding="utf-16") as stream:
            stream.write("[Toolbar]\nOrder=G1|G2\nHidden=G3\n[General]\nManagerTheme=forest-green\n")
        target = os.path.join(self.folder, "new", "settings.ini")
        settings, migrated = load_or_migrate(target, legacy)
        self.assertTrue(migrated)
        self.assertEqual(settings.toolbar_order, ["G1", "G2"])
        self.assertTrue(settings.is_hidden("g3"))
        self.assertEqual(Settings.load(target).manager_theme, "forest-green")

    def test_new_toolbar_defaults(self):
        # Top, regular spacing, large icons, icons only.
        settings = Settings.load(os.path.join(self.folder, "missing.ini"))
        self.assertEqual((settings.toolbar_dock_position, settings.toolbar_density, settings.toolbar_icon_size,
                          settings.toolbar_button_size), ("top", "regular", "large", "icon"))

    def test_endpoint(self):
        self.assertEqual(normalize_endpoint(" https://example.test/api "), "https://example.test/api/")
        self.assertEqual(normalize_endpoint("ftp://x"), "")


class PackageTests(unittest.TestCase):
    def test_scan_skips_broken_and_duplicates(self):
        folder = tempfile.mkdtemp()
        try:
            for name, body in (("a", "[package]\npackageGuid=G1\nname=Alpha\nversion=1.0\nentry=a.ms\n"),
                               ("b", "[package]\npackageGuid=g1\nname=Dup\nversion=1.0\nentry=b.ms\n"),
                               ("c", "[package]\nname=Broken\n")):
                os.makedirs(os.path.join(folder, name))
                with open(os.path.join(folder, name, "manifest.ini"), "w", encoding="utf-8") as stream:
                    stream.write(body)
            packages = scan([folder])
            self.assertEqual([package.name for package in packages], ["Alpha"])
            self.assertEqual(packages[0].runtime, "MaxScript")
        finally:
            shutil.rmtree(folder)

    def test_versions(self):
        self.assertTrue(is_newer("1.10.0", "1.9.9"))
        self.assertFalse(is_newer("1.0", "1.0.0"))
        self.assertEqual(compact_number(10700), "10.7K")
        self.assertEqual(compact_number(796), "796")
        self.assertEqual(compact_number(1000), "1K")
        self.assertEqual(compact_number(1139), "1.1K")
        self.assertEqual(compact_number(999950), "1M")
        self.assertEqual(compact_number(2500000), "2.5M")

    def test_toolbar_order(self):
        packages = [Package(guid="A", name="a"), Package(guid="B", name="b"), Package(guid="C", name="c")]
        self.assertEqual(normalized_order(packages, ["c", "x"]), ["C", "A", "B"])
        ordered = ordered_for_toolbar(packages, ["C", "A", "B"], lambda guid: guid == "A")
        self.assertEqual([package.guid for package in ordered], ["C", "B"])
        self.assertEqual(merge_visible_order(["C", "A", "B"], ["B", "C"], ["C", "B"]), ["B", "A", "C"])

    def test_toolbar_dividers(self):
        packages = [Package(guid="A", name="a"), Package(guid="B", name="b"), Package(guid="C", name="c")]
        saved = normalized_order(packages, ["A", "divider", "x", "B", "Divider", "C"])
        self.assertEqual(saved, ["A", DIVIDER, "B", DIVIDER, "C"])
        # The toolbar moves dividers with the buttons.
        self.assertEqual(merge_visible_order(saved, [DIVIDER, "A", "B", "C", DIVIDER], ["A", "B", "C"]),
                         [DIVIDER, "A", "B", "C", DIVIDER])
        # The Manager never shows dividers: they keep their slots while packages move.
        self.assertEqual(merge_visible_order(saved, ["C", "B", "A"], ["A", "B", "C"]), ["C", DIVIDER, "B", DIVIDER, "A"])
        # A hidden package leaves its divider on the toolbar.
        entries = toolbar_entries(packages, saved, lambda guid: guid == "B")
        self.assertEqual([entry if entry == DIVIDER else entry.guid for entry in entries], ["A", DIVIDER, DIVIDER, "C"])

    def test_brand_divider(self):
        # A divider after the maxpkg button by default, never doubled.
        self.assertEqual(with_brand_divider(["A", "B"]), [DIVIDER, "A", "B"])
        self.assertEqual(with_brand_divider([DIVIDER, "A"]), [DIVIDER, "A"])
        self.assertEqual(with_brand_divider([]), [DIVIDER])


class ChangelogVersionsTests(unittest.TestCase):
    def test_groups_entries_by_release(self):
        package = Package()
        package.version, package.release_date = "1.2.0", "2026-10-01"
        package.changelog = [ChangelogEntry("Added", "A", "1.2.0", "2026-10-01"),
                             ChangelogEntry("Fixed", "B", "1.2.0", "2026-10-01"),
                             ChangelogEntry("Fixed", "C", "1.1.0", "2026-09-01"),
                             ChangelogEntry("Changed", "D")]  # no version: the package's own release
        groups = changelog_versions(package)
        self.assertEqual([key for key, _entries in groups],
                         [("1.2.0", "2026-10-01"), ("1.1.0", "2026-09-01"), ("1.2.0", "2026-10-01")])
        self.assertEqual([len(entries) for _key, entries in groups], [2, 1, 1])
        self.assertEqual(changelog_versions(Package()), [])


class CompatibilityTests(unittest.TestCase):
    @staticmethod
    def package(minimum="", maximum=""):
        package = Package()
        package.name = "TopoLandia"
        package.min_max_version = minimum
        package.max_max_version = maximum
        return package

    def test_both_bounds_like_the_api(self):
        ranged = self.package("2024", "2027")
        self.assertFalse(compatible(ranged, 2022))
        self.assertTrue(compatible(ranged, 2024))
        self.assertTrue(compatible(ranged, 2027))
        self.assertFalse(compatible(ranged, 2028))
        self.assertTrue(compatible(self.package(), 2022))
        self.assertTrue(compatible(self.package("0", "0"), 2022))
        self.assertTrue(compatible(self.package("2020"), 2030))
        self.assertFalse(compatible(self.package("", "2025"), 2026))

    def test_range_text_and_reason(self):
        self.assertEqual(supported_versions(self.package("2024", "2027")), "2024–2027")
        self.assertEqual(supported_versions(self.package("2025", "2025")), "2025")
        self.assertEqual(supported_versions(self.package("2024")), "2024 and newer")
        self.assertEqual(supported_versions(self.package("", "2025")), "2025 and older")
        self.assertEqual(supported_versions(self.package()), "")
        self.assertEqual(incompatibility(self.package("2024", "2027"), 2022),
                         "It supports 3ds Max 2024–2027. This is 3ds Max 2022.")
        self.assertEqual(incompatibility(self.package("2024", "2027"), 2025), "")

    def test_manifest_inside_an_mzp(self):
        folder = tempfile.mkdtemp()
        try:
            mzp = os.path.join(folder, "package.mzp")
            with zipfile.ZipFile(mzp, "w") as archive:
                archive.writestr("mzp.run", "run install.ms")
                archive.writestr("docs/manifest.ini", "[package]\nname=Wrong\n")
                archive.writestr("manifest.ini", ("﻿[package]\npackageGuid=g1\nname=TopoLandia\n"
                                                  "min3dsMax=2024\nmax3dsMax=2027\n").encode("utf-8"))
            package = read_mzp_manifest(mzp)
            self.assertEqual((package.guid, package.name), ("g1", "TopoLandia"))
            self.assertEqual(incompatibility(package, 2022), "It supports 3ds Max 2024–2027. This is 3ds Max 2022.")
            plain = os.path.join(folder, "plain.mzp")
            with open(plain, "w") as stream:
                stream.write("not a zip")
            self.assertIsNone(read_mzp_manifest(plain))
            self.assertIsNone(read_mzp_manifest(os.path.join(folder, "missing.mzp")))
        finally:
            shutil.rmtree(folder, ignore_errors=True)


class ApiTests(unittest.TestCase):
    CATALOG = ("[catalog]\nPage=1\nTotalPages=2\nTotal=30\nTotalPackages=21\n"
               "[g1]\nName=Prune Scene\nVersion=3.7\nMin3dsMax=2020\nRating=5\nDownloadCount=1100\n"
               "[g2]\nName=Future\nVersion=1\nMin3dsMax=2099\n"
               "[g3]\nName=Old\nVersion=1\nMin3dsMax=2018\nMax3dsMax=2024\n")

    def test_catalog_filters_incompatible(self):
        page = api.parse_catalog(self.CATALOG, 2027)
        self.assertEqual([package.guid for package in page.packages], ["g1"])
        self.assertEqual(page.total, 28)
        self.assertEqual(page.total_packages, 21)
        self.assertEqual(page.packages[0].download_count, 1100)

    def test_error(self):
        with self.assertRaises(api.ApiError) as context:
            api.parse_catalog("[error]\nCode=BAD\nMessage=Nope\n", 2027)
        self.assertEqual(context.exception.code, "BAD")

    def test_details_with_versioned_changelog_and_screenshots(self):
        text = ("[package]\nGuid=g1\nName=X\nVersion=2\nFullDescription=## A\\n- b\n[changelog]\nCount=1\n"
                "[changelog_1]\nVersion=2\n"
                "ReleaseDate=2026-01-01\nCount=1\n[changelog_1_item_1]\nType=Added\nText=New\n"
                "[screenshots]\nCount=2\n[screenshot_1]\nUrl=https://a/2.png\nSortOrder=2\n"
                "[screenshot_2]\nUrl=https://a/1.png\nSortOrder=1\n")
        package = api.parse_details(text, 2027)
        self.assertEqual(package.full_description, "## A\n- b")
        self.assertEqual(package.changelog[0].change_type, "Added")
        self.assertEqual(package.changelog[0].release_date, "2026-01-01")
        self.assertEqual([shot.url for shot in package.screenshots], ["https://a/1.png", "https://a/2.png"])

    def test_request_fields(self):
        request = api.catalog_request(2027, "2.0.0", featured=True, category="ignored")
        fields = dict(request.fields)
        self.assertEqual(fields["featured"], "true")
        self.assertEqual(fields["category"], "")
        self.assertEqual(request.url("https://maxpkg.dev/api/runtime/v1/"), "https://maxpkg.dev/api/runtime/v1/catalog")


class MessageTests(unittest.TestCase):
    def test_notifications_have_no_links(self):
        self.assertEqual(without_links("Prune Scene was updated.\n3.7.42 → 3.7.43"), "Prune Scene was updated.\n3.7.42 → 3.7.43")
        self.assertEqual(without_links("Package could not be installed.\nError transferring "
                                       "https://maxpkg.dev/api/runtime/v1/download/package/x/2.2.0 - server replied: Not Found"),
                         "Package could not be installed.\nError transferring - server replied: Not Found")
        self.assertEqual(without_links("https://maxpkg.dev/a/b was updated."), "was updated.")
        self.assertEqual(without_links("Opened the page (www.example.test/x).\nThank you."), "Opened the page.\nThank you.")
        self.assertEqual(without_links("Only a link:\nhttps://a.test/x"), "Only a link")


class MarkdownTests(unittest.TestCase):
    def test_subset(self):
        html = markdown.to_html("# Title\n\nSome **bold** and `code`.\n\n- one\n- two\n\n<script>")
        self.assertIn("<h3>Title</h3>", html)
        self.assertIn("<b>bold</b>", html)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_tables(self):
        html = markdown.to_html("| Format | Extensions |\n| --- | :---: |\n| 3ds Max | `.max` |\n| IGES | `.iges`, `.igs` |\n"
                                "\nMAX files are merged.")
        self.assertIn('<table class="md"', html)
        self.assertIn('<th align="left">Format</th><th align="center">Extensions</th>', html)
        self.assertIn('<td align="left">3ds Max</td><td align="center"><code>.max</code></td>', html)
        self.assertIn("<code>.iges</code>, <code>.igs</code>", html)
        self.assertIn("<p>MAX files are merged.</p>", html)
        self.assertNotIn("| ---", html)

    def test_github_syntax(self):
        html = markdown.to_html("Title\n=====\n\n- [x] done\n- [ ] todo\n  - nested **bold**\n\n3. three\n4. four\n\n"
                                "---\n\n~~old~~ __new__ _soft_ snake_case_name\\* see https://maxpkg.dev/docs.\n\n"
                                "[Docs](/docs) [bad](javascript:alert(1)) ![shot](https://x.test/a.png)\n\n"
                                "> quoted *text*\n\n~~~\n<b>raw</b>\n~~~")
        self.assertIn("<h3>Title</h3>", html)
        self.assertIn("☑ done", html)
        self.assertIn("☐ todo<ul><li>nested <b>bold</b></li></ul>", html)
        self.assertIn('<ol start="3"><li>three</li><li>four</li></ol>', html)
        self.assertIn("<hr>", html)
        self.assertIn("<s>old</s> <b>new</b> <i>soft</i> snake_case_name*", html)
        self.assertIn('<a href="https://maxpkg.dev/docs">https://maxpkg.dev/docs</a>.', html)
        self.assertIn('<a href="https://maxpkg.dev/docs">Docs</a>', html)
        self.assertNotIn("javascript", html)
        self.assertIn('<a href="https://x.test/a.png">shot</a>', html)
        self.assertIn("<blockquote><p>quoted <i>text</i></p></blockquote>", html)
        self.assertIn("<pre>&lt;b&gt;raw&lt;/b&gt;</pre>", html)

    def test_single_newlines_break_lines(self):
        # The runtime API drops blank lines, so each line of a description stays on its own line, as on the site.
        html = markdown.to_html("### Links\n**Website:** [https://a.test/](https://a.test/)\n**Guide:** [Guide](https://b.test/)\n"
                                "### Compatibility\n3ds Max 2020 and newer\nV-Ray 5, 6, and 7\nwrapped with a backslash\\\nend")
        self.assertIn('<p><b>Website:</b> <a href="https://a.test/">https://a.test/</a><br><b>Guide:</b> '
                      '<a href="https://b.test/">Guide</a></p>', html)
        self.assertIn("<p>3ds Max 2020 and newer<br>V-Ray 5, 6, and 7<br>wrapped with a backslash<br>end</p>", html)


if __name__ == "__main__":
    unittest.main()
