"""Pure tests for domain/integrity.py. Run with tests/run_unit.py."""

import hashlib
import os
import shutil
import tempfile
import unittest

from maxpkg_runtime.domain import integrity


class IntegrityTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxpkg-integrity-")
        self.file_path = os.path.join(self.folder, "package.mzp")
        self.data = b"PK\x03\x04" + os.urandom(3 * integrity.CHUNK + 17)  # several chunks and a remainder
        with open(self.file_path, "wb") as stream:
            stream.write(self.data)
        self.sha = hashlib.sha256(self.data).hexdigest()

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_streamed_hash_matches_whole_file_hash(self):
        self.assertEqual(integrity.file_sha256(self.file_path), self.sha)

    def test_match_ignores_case_and_spaces(self):
        self.assertEqual(integrity.verify_file(self.file_path, "  " + self.sha.upper() + " \n"),
                         (integrity.MATCH, self.sha))

    def test_other_hash_is_a_mismatch(self):
        other = hashlib.sha256(b"other").hexdigest()
        self.assertEqual(integrity.verify_file(self.file_path, other), (integrity.MISMATCH, self.sha))

    def test_malformed_value_is_a_mismatch(self):
        for value in (self.sha[:-1], self.sha + "0", "z" * 64, "sha256:" + self.sha):
            self.assertEqual(integrity.verify_file(self.file_path, value)[0], integrity.MISMATCH, value)

    def test_empty_value_is_unpublished(self):
        self.assertEqual(integrity.verify_file(self.file_path, ""), (integrity.UNPUBLISHED, self.sha))
        self.assertEqual(integrity.verify_file(self.file_path, None)[0], integrity.UNPUBLISHED)

    def test_missing_file_is_unreadable(self):
        missing = os.path.join(self.folder, "missing.mzp")
        self.assertEqual(integrity.verify_file(missing, self.sha), (integrity.UNREADABLE, ""))


if __name__ == "__main__":
    unittest.main()
