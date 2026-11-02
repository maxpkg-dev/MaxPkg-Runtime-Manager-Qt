"""Pure tests for domain/self_update.py. Run with tests/run_unit.py."""

import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from maxpkg_runtime.domain import self_update as su

HASH = "a" * 64


def release(tag, prerelease=False, draft=False, assets=(su.PACKAGE_ASSET, su.HASH_ASSET)):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft, "body": "notes of " + tag,
            "assets": [{"name": name, "browser_download_url": "https://example.test/" + tag + "/" + name}
                       for name in assets]}


class ReleaseSelectionTests(unittest.TestCase):
    def releases(self, *entries):
        return su.parse_releases(json.dumps(list(entries)))

    def test_newest_release_above_current_is_chosen(self):
        found = su.select_update(self.releases(release("v2.0.1", True), release("v2.0.9", True), release("v2.0.3", True)),
                                 "2.0.2", "preview")
        self.assertEqual(found.version, "2.0.9")
        self.assertEqual(found.package_url, "https://example.test/v2.0.9/" + su.PACKAGE_ASSET)

    def test_versions_compare_numerically(self):
        found = su.select_update(self.releases(release("v2.0.10", True), release("v2.0.9", True)), "2.0.8", "preview")
        self.assertEqual(found.version, "2.0.10")

    def test_no_update_when_current_or_newer(self):
        releases = self.releases(release("v2.0.8", True))
        self.assertIsNone(su.select_update(releases, "2.0.8", "preview"))
        self.assertIsNone(su.select_update(releases, "2.1.0", "preview"))

    def test_stable_channel_ignores_prereleases(self):
        releases = self.releases(release("v2.1.0", True), release("v2.0.5", False))
        self.assertEqual(su.select_update(releases, "2.0.0", "stable").version, "2.0.5")
        self.assertEqual(su.select_update(releases, "2.0.0", "preview").version, "2.1.0")

    def test_drafts_and_releases_without_both_assets_are_skipped(self):
        releases = self.releases(release("v3.0.0", draft=True), release("v2.9.0", assets=(su.PACKAGE_ASSET,)),
                                 release("v2.8.0", assets=(su.HASH_ASSET,)), release("v2.0.4"))
        self.assertEqual(su.select_update(releases, "2.0.0", "preview").version, "2.0.4")

    def test_odd_tags_and_bad_json(self):
        self.assertEqual(self.releases(release("nightly"), release("v2.0.1-rc1")), [])
        with self.assertRaises(su.UpdateError):
            su.parse_releases("not json")
        with self.assertRaises(su.UpdateError):
            su.parse_releases('{"message": "rate limit"}')


class HashTextTests(unittest.TestCase):
    def test_sha256sum_line(self):
        self.assertEqual(su.parse_sha256(HASH.upper() + "  " + su.PACKAGE_ASSET + "\n"), HASH)

    def test_binary_marker_and_bare_hash(self):
        self.assertEqual(su.parse_sha256(HASH + " *" + su.PACKAGE_ASSET), HASH)
        self.assertEqual(su.parse_sha256(HASH + "\n"), HASH)

    def test_wrong_file_name_or_garbage(self):
        self.assertEqual(su.parse_sha256(HASH + "  other.mzp"), "")
        self.assertEqual(su.parse_sha256("zz" * 32 + "  " + su.PACKAGE_ASSET), "")
        self.assertEqual(su.parse_sha256(""), "")


class FileTests(unittest.TestCase):
    def setUp(self):
        self.base = Path(tempfile.mkdtemp(prefix="maxpkg-selfupdate-"))

    def tearDown(self):
        shutil.rmtree(str(self.base), ignore_errors=True)

    def make_program(self, folder, marker):
        folder = Path(folder)
        (folder / "python" / "maxpkg_runtime").mkdir(parents=True)
        (folder / "assets").mkdir()
        (folder / "python" / "bootstrap.py").write_text("# " + marker, encoding="utf-8")
        (folder / "python" / "maxpkg_runtime" / "__init__.py").write_text(marker, encoding="utf-8")
        (folder / "assets" / "icon.svg").write_text(marker, encoding="utf-8")
        (folder / "StartMaxPkg.ms").write_text(marker, encoding="utf-8")
        (folder / "uninstall.ms").write_text(marker, encoding="utf-8")
        (folder / "version.ini").write_text("[Runtime]\nVersion=" + marker + "\nChannel=preview\n", encoding="utf-8")
        return folder

    def zip_of(self, folder, target, extra=None):
        with zipfile.ZipFile(str(target), "w") as archive:
            for path in Path(folder).rglob("*"):
                if path.is_file():
                    archive.write(str(path), path.relative_to(folder).as_posix())
            for name, data in (extra or {}).items():
                archive.writestr(name, data)
        return target

    def test_extract_and_find_root(self):
        program = self.make_program(self.base / "src", "2.0.9")
        archive = self.zip_of(program, self.base / "release.mzp")
        out = self.base / "out"
        su.safe_extract(archive, out)
        root = su.find_package_root(out)
        self.assertEqual(su.read_version_ini(root), ("2.0.9", "preview"))

    def test_root_in_a_single_subfolder(self):
        program = self.make_program(self.base / "src" / "MaxPkg", "2.0.9")
        archive = self.zip_of(self.base / "src", self.base / "release.mzp")
        out = self.base / "out"
        su.safe_extract(archive, out)
        self.assertEqual(su.find_package_root(out).name, "MaxPkg")

    def test_archive_without_the_program_is_refused(self):
        archive = self.zip_of(self.base, self.base / "junk.mzp", {"readme.txt": "hi"})
        out = self.base / "out2"
        su.safe_extract(archive, out)
        with self.assertRaises(su.UpdateError):
            su.find_package_root(out)

    def test_zip_slip_is_refused(self):
        archive = self.base / "evil.mzp"
        with zipfile.ZipFile(str(archive), "w") as handle:
            handle.writestr("../escaped.txt", "x")
        with self.assertRaises(su.UpdateError):
            su.safe_extract(archive, self.base / "out3")
        self.assertFalse((self.base / "escaped.txt").exists())

    def test_not_a_zip(self):
        bad = self.base / "bad.mzp"
        bad.write_bytes(b"this is not a zip file")
        with self.assertRaises(su.UpdateError):
            su.safe_extract(bad, self.base / "out4")

    def test_install_replaces_program_and_keeps_user_data(self):
        installed = self.make_program(self.base / "installed", "1.0.0")
        (installed / "settings.ini").write_text("keep", encoding="utf-8")
        (installed / "logs").mkdir()
        staged = self.make_program(self.base / "staged", "2.0.0")
        swap = su.install_staged(installed, staged)
        self.assertEqual((installed / "python" / "maxpkg_runtime" / "__init__.py").read_text(encoding="utf-8"), "2.0.0")
        self.assertEqual((installed / "assets" / "icon.svg").read_text(encoding="utf-8"), "2.0.0")
        self.assertEqual(su.read_version_ini(installed)[0], "2.0.0")
        self.assertEqual((installed / "settings.ini").read_text(encoding="utf-8"), "keep")
        self.assertTrue((installed / "logs").is_dir())
        self.assertTrue((installed / "python.old").is_dir())  # kept for a rollback until cleanup
        swap.rollback()
        self.assertEqual(su.read_version_ini(installed)[0], "1.0.0")
        self.assertEqual((installed / "assets" / "icon.svg").read_text(encoding="utf-8"), "1.0.0")
        self.assertFalse((installed / "python.old").exists())

    def test_failed_swap_restores_everything(self):
        installed = self.make_program(self.base / "installed", "1.0.0")
        staged = self.make_program(self.base / "staged", "2.0.0")
        (installed / "uninstall.ms.new" / "block").mkdir(parents=True)  # copying onto a folder fails after the swap
        with self.assertRaises(OSError):
            su.install_staged(installed, staged)
        self.assertEqual((installed / "assets" / "icon.svg").read_text(encoding="utf-8"), "1.0.0")
        self.assertEqual((installed / "python" / "maxpkg_runtime" / "__init__.py").read_text(encoding="utf-8"), "1.0.0")
        self.assertEqual(su.read_version_ini(installed)[0], "1.0.0")

    def test_incomplete_stage_changes_nothing(self):
        installed = self.make_program(self.base / "installed", "1.0.0")
        staged = self.make_program(self.base / "staged", "2.0.0")
        shutil.rmtree(str(staged / "assets"))
        with self.assertRaises(su.UpdateError):
            su.install_staged(installed, staged)
        self.assertEqual(su.read_version_ini(installed)[0], "1.0.0")
        self.assertFalse((installed / "python.old").exists())

    def test_cleanup_backups(self):
        installed = self.make_program(self.base / "installed", "1.0.0")
        su.install_staged(installed, self.make_program(self.base / "staged", "2.0.0"))
        self.assertGreater(su.cleanup_backups(installed), 0)
        self.assertFalse((installed / "python.old").exists())
        self.assertFalse((installed / "version.ini.old").exists())

    def test_source_checkout_detection(self):
        self.assertFalse(su.is_source_checkout(self.base))
        (self.base / ".git").mkdir()
        self.assertTrue(su.is_source_checkout(self.base))


if __name__ == "__main__":
    unittest.main()
