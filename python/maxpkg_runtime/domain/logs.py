"""The daily log files for the log viewer: which days exist, their records, level filters and counts.

A record line is `HH:MM:SS [LEVEL] area: message` (services/log.py); lines without that header, such as a
traceback, belong to the record above them.
"""

import datetime
import os
import re

FILE_PATTERN = re.compile(r"^runtime-(\d{4})-(\d\d)-(\d\d)\.log$")
RECORD_PATTERN = re.compile(r"^(\d\d:\d\d:\d\d) \[([A-Z]+)\] ([^:\s]+): ?(.*)$")
LEVELS = {"DEBUG": "debug", "INFO": "info", "SUCCESS": "success", "WARN": "warning", "WARNING": "warning",
          "ERROR": "error"}
LEVEL_LABELS = {"debug": "DEBUG", "info": "INFO", "success": "SUCCESS", "warning": "WARNING", "error": "ERROR"}
FILTERS = (("all", "All"), ("warnings", "Warnings"), ("errors", "Errors"))
FILTER_LEVELS = {"all": ("debug", "info", "success", "warning", "error"), "warnings": ("warning", "error"),
                 "errors": ("error",)}
SESSION_PREFIX = "MaxPkg Runtime (Qt) "
READ_LIMIT = 2 * 1024 * 1024  # a day's log larger than this is shown from its last 2 MB
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


class LogDay(object):
    __slots__ = ("date", "file_path", "size")

    def __init__(self, date, file_path, size):
        self.date = date
        self.file_path = file_path
        self.size = size


class LogRecord(object):
    __slots__ = ("time", "level", "area", "message", "extra")

    def __init__(self, time, level, area, message, extra=None):
        self.time = time
        self.level = level
        self.area = area
        self.message = message
        self.extra = extra if extra is not None else []

    @property
    def session_start(self):
        return self.area == "startup" and self.message.startswith(SESSION_PREFIX)

    def text(self):
        """The record as it stands in the file."""
        lines = ["{} [{}] {}: {}".format(self.time, LEVEL_LABELS[self.level], self.area, self.message)]
        return "\n".join(lines + self.extra)


def log_days(folder):
    """[LogDay] of the folder's daily logs, newest first."""
    days = []
    try:
        names = os.listdir(folder)
    except OSError:
        return days
    for name in names:
        match = FILE_PATTERN.match(name)
        if not match:
            continue
        try:
            date = datetime.date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            file_path = os.path.join(folder, name)
            days.append(LogDay(date, file_path, os.path.getsize(file_path)))
        except (ValueError, OSError):
            continue
    days.sort(key=lambda day: day.date, reverse=True)
    return days


def day_label(date, today=None):
    """'Today', 'Yesterday' or 'Thu 29 Oct 2026' (English, whatever the Windows language)."""
    today = today or datetime.date.today()
    if date == today:
        return "Today"
    if date == today - datetime.timedelta(days=1):
        return "Yesterday"
    return "{} {} {} {}".format(WEEKDAYS[date.weekday()], date.day, MONTHS[date.month - 1], date.year)


def read_records(file_path, limit=READ_LIMIT):
    """Records of one day's file; a file over `limit` is read from its end (the cut first line is dropped)."""
    try:
        with open(file_path, "rb") as stream:
            stream.seek(0, os.SEEK_END)
            size = stream.tell()
            stream.seek(max(0, size - limit))
            data = stream.read()
    except OSError:
        return []
    text = data.decode("utf-8", errors="replace")
    if size > limit:
        text = text.split("\n", 1)[-1]
    return parse_records(text)


def parse_records(text):
    """[LogRecord] from log text. Unknown levels read as INFO; text before the first record is dropped."""
    records = []
    for line in text.splitlines():
        match = RECORD_PATTERN.match(line)
        if match:
            time, level, area, message = match.groups()
            records.append(LogRecord(time, LEVELS.get(level, "info"), area, message))
        elif records and line.strip():
            records[-1].extra.append(line.rstrip())
    return records


def filter_records(records, level_filter="all", query=""):
    """Records of the chosen levels whose area, message or extra lines contain `query` (any case)."""
    levels = FILTER_LEVELS.get(level_filter, FILTER_LEVELS["all"])
    needle = query.strip().lower()
    shown = []
    for record in records:
        if record.level not in levels:
            continue
        if needle and needle not in " ".join([record.area, record.message] + record.extra).lower():
            continue
        shown.append(record)
    return shown


def summary_text(records):
    """'35 records · 1 warning · 2 errors' (warnings and errors only when there are any)."""
    warnings = sum(1 for record in records if record.level == "warning")
    errors = sum(1 for record in records if record.level == "error")
    parts = [_count(len(records), "record")]
    if warnings:
        parts.append(_count(warnings, "warning"))
    if errors:
        parts.append(_count(errors, "error"))
    return " · ".join(parts)


def _count(number, noun):
    return "{} {}{}".format(number, noun, "" if number == 1 else "s")


__all__ = ["FILTERS", "LEVEL_LABELS", "LogDay", "LogRecord", "day_label", "filter_records", "log_days",
           "parse_records", "read_records", "summary_text"]
