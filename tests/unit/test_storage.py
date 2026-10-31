"""Pure tests for domain/storage.py. Run with tests/run_unit.py."""

import os
import shutil
import tempfile
import unittest

from maxpkg_runtime.domain import storage


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxpkg-storage-")
        for name, size in (("a.png", 1000), ("b.svg", 24)):
            with open(os.path.join(self.folder, name), "wb") as stream:
                stream.write(b"x" * size)
        os.mkdir(os.path.join(self.folder, "nested"))

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_usage_counts_files_only(self):
        self.assertEqual(storage.folder_usage(self.folder), (2, 1024))

    def test_clear_removes_files_and_keeps_folders(self):
        self.assertEqual(storage.clear_folder(self.folder), (2, 1024))
        self.assertEqual(os.listdir(self.folder), ["nested"])
        self.assertEqual(storage.folder_usage(self.folder), (0, 0))

    def test_missing_folder(self):
        missing = os.path.join(self.folder, "missing")
        self.assertEqual(storage.folder_usage(missing), (0, 0))
        self.assertEqual(storage.clear_folder(missing), (0, 0))

    def test_size_text(self):
        self.assertEqual(storage.size_text(0), "0 KB")
        self.assertEqual(storage.size_text(340 * 1024), "340 KB")
        self.assertEqual(storage.size_text(int(16.4 * 1024 * 1024)), "16.4 MB")
        self.assertEqual(storage.size_text(int(1.2 * 1024 ** 3)), "1.2 GB")


if __name__ == "__main__":
    unittest.main()
