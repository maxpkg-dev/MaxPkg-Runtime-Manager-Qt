"""Pure tests for domain/ (no Qt, no pymxs). Run with tests/run_unit.py (works inside or outside Max)."""

import os
import shutil
import tempfile
import unittest

from maxpkg_runtime.domain import api, markdown
from maxpkg_runtime.domain.ini import IniDocument
from maxpkg_runtime.domain.packages import (Package, compact_number, is_newer, merge_visible_order,
                                            normalized_order, ordered_for_toolbar, scan)
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
        self.assertEqual(settings.toolbar_button_size, "medium")
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

    def test_toolbar_order(self):
        packages = [Package(guid="A", name="a"), Package(guid="B", name="b"), Package(guid="C", name="c")]
        self.assertEqual(normalized_order(packages, ["c", "x"]), ["C", "A", "B"])
        ordered = ordered_for_toolbar(packages, ["C", "A", "B"], lambda guid: guid == "A")
        self.assertEqual([package.guid for package in ordered], ["C", "B"])
        self.assertEqual(merge_visible_order(["C", "A", "B"], ["B", "C"], ["C", "B"]), ["B", "A", "C"])


class ApiTests(unittest.TestCase):
    CATALOG = ("[catalog]\nPage=1\nTotalPages=2\nTotal=30\nTotalPackages=21\n"
               "[g1]\nName=Prune Scene\nVersion=3.7\nMin3dsMax=2020\nRating=5\nDownloadCount=1100\n"
               "[g2]\nName=Future\nVersion=1\nMin3dsMax=2099\n")

    def test_catalog_filters_incompatible(self):
        page = api.parse_catalog(self.CATALOG, 2027)
        self.assertEqual([package.guid for package in page.packages], ["g1"])
        self.assertEqual(page.total, 29)
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


if __name__ == "__main__":
    unittest.main()
