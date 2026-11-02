"""Pure tests for domain/logs.py. Run with tests/run_unit.py."""

import datetime
import os
import shutil
import tempfile
import unittest

from maxpkg_runtime.domain import logs

SAMPLE = """22:18:46 [INFO] scanner: Discovered 7 package(s)
22:18:46 [INFO] startup: MaxPkg Runtime (Qt) 2.0.3 on 3ds Max 2027
22:18:47 [SUCCESS] startup: Runtime started (PySide6 6.8.3 / Qt 6.8.3)
22:19:02 [WARN] network: Qt request failed (Host maxpkg.dev not found); trying curl
22:20:13 [ERROR] launcher: abc: MAXScript exception raised.
-- Runtime error:
Traceback (most recent call last):

22:21:00 [DEBUG] images: cached
"""


class ParseTests(unittest.TestCase):
    def test_levels_areas_and_extra_lines(self):
        records = logs.parse_records(SAMPLE)
        self.assertEqual([record.level for record in records],
                         ["info", "info", "success", "warning", "error", "debug"])
        self.assertEqual(records[3].area, "network")
        self.assertEqual(records[4].extra, ["-- Runtime error:", "Traceback (most recent call last):"])
        self.assertTrue(records[1].session_start)
        self.assertFalse(records[2].session_start)

    def test_text_before_the_first_record_is_dropped(self):
        records = logs.parse_records("cut line\n10:00:00 [INFO] scanner: ok\n")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].extra, [])

    def test_record_text_round_trip(self):
        record = logs.parse_records(SAMPLE)[3]
        self.assertEqual(record.text(), "22:19:02 [WARNING] network: Qt request failed (Host maxpkg.dev not found); "
                                        "trying curl")


class FilterTests(unittest.TestCase):
    def setUp(self):
        self.records = logs.parse_records(SAMPLE)

    def test_levels(self):
        self.assertEqual(len(logs.filter_records(self.records, "all")), 6)
        self.assertEqual([record.level for record in logs.filter_records(self.records, "warnings")],
                         ["warning", "error"])
        self.assertEqual(len(logs.filter_records(self.records, "errors")), 1)

    def test_query_searches_extra_lines_in_any_case(self):
        self.assertEqual(len(logs.filter_records(self.records, "all", "TRACEBACK")), 1)
        self.assertEqual(len(logs.filter_records(self.records, "all", "curl")), 1)
        self.assertEqual(logs.filter_records(self.records, "errors", "curl"), [])

    def test_summary(self):
        self.assertEqual(logs.summary_text(self.records), "6 records · 1 warning · 1 error")
        self.assertEqual(logs.summary_text(self.records[:1]), "1 record")


class DayTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.mkdtemp(prefix="maxpkg-logs-")
        for name in ("runtime-2026-10-30.log", "runtime-2026-11-02.log", "runtime-2026-02-30.log", "other.log"):
            with open(os.path.join(self.folder, name), "w", encoding="utf-8") as stream:
                stream.write(SAMPLE)

    def tearDown(self):
        shutil.rmtree(self.folder, ignore_errors=True)

    def test_days_newest_first_and_invalid_names_skipped(self):
        days = logs.log_days(self.folder)
        self.assertEqual([day.date for day in days], [datetime.date(2026, 11, 2), datetime.date(2026, 10, 30)])
        self.assertGreater(days[0].size, 0)
        self.assertEqual(logs.log_days(os.path.join(self.folder, "missing")), [])

    def test_labels(self):
        today = datetime.date(2026, 11, 2)
        self.assertEqual(logs.day_label(today, today), "Today")
        self.assertEqual(logs.day_label(datetime.date(2026, 11, 1), today), "Yesterday")
        self.assertEqual(logs.day_label(datetime.date(2026, 10, 29), today), "Thu 29 Oct 2026")

    def test_clear_removes_daily_logs_only(self):
        sizes = sum(day.size for day in logs.log_days(self.folder))
        removed, freed = logs.clear_logs(self.folder)
        self.assertEqual(removed, 2)
        self.assertEqual(freed, sizes)
        self.assertEqual(sorted(os.listdir(self.folder)), ["other.log", "runtime-2026-02-30.log"])
        self.assertEqual(logs.clear_logs(os.path.join(self.folder, "missing")), (0, 0))

    def test_large_file_is_read_from_its_end(self):
        file_path = logs.log_days(self.folder)[0].file_path
        records = logs.read_records(file_path, limit=60)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].level, "debug")


if __name__ == "__main__":
    unittest.main()
