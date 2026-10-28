"""Windows-style INI files: case-insensitive sections/keys, UTF-16 or UTF-8, tolerant of junk.

The MaxScript Runtime writes settings.ini with ``setINISetting`` (UTF-16 LE with BOM) and package
manifests are UTF-8. API responses are INI text too.
"""

import os


def decode(data):
    if data.startswith(b"\xff\xfe") or data.startswith(b"\xfe\xff"):
        return data.decode("utf-16")
    if data.startswith(b"\xef\xbb\xbf"):
        return data[3:].decode("utf-8")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


class IniDocument:
    """Ordered sections of ordered keys. Lookups ignore case; the first spelling wins on write."""

    def __init__(self):
        self._sections = []  # [(name, [(key, value)])]

    @classmethod
    def parse(cls, text):
        document = cls()
        current = None
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line or line.startswith(";") or line.startswith("#"):
                continue
            if line.startswith("[") and line.endswith("]"):
                current = document._section(line[1:-1].strip(), create=True)
                continue
            if current is None or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key and _find(current[1], key) is None:
                current[1].append((key, value.strip()))
        return document

    @classmethod
    def load(cls, path):
        if not os.path.isfile(str(path)):
            return cls()
        with open(str(path), "rb") as stream:
            return cls.parse(decode(stream.read()))

    def _section(self, name, create=False):
        lowered = name.lower()
        for section in self._sections:
            if section[0].lower() == lowered:
                return section
        if not create:
            return None
        section = (name, [])
        self._sections.append(section)
        return section

    def sections(self):
        return [name for name, _ in self._sections]

    def has_section(self, name):
        return self._section(name) is not None

    def keys(self, section_name):
        section = self._section(section_name)
        return [key for key, _ in section[1]] if section else []

    def get(self, section_name, key, default=""):
        section = self._section(section_name)
        if section is None:
            return default
        index = _find(section[1], key)
        return section[1][index][1] if index is not None else default

    def get_any(self, section_name, keys, default=""):
        """First non-empty value among alias keys."""
        for key in keys:
            found = self.get(section_name, key, "")
            if found != "":
                return found
        return default

    def set(self, section_name, key, value):
        section = self._section(section_name, create=True)
        index = _find(section[1], key)
        if index is None:
            section[1].append((key, str(value)))
        else:
            section[1][index] = (section[1][index][0], str(value))

    def to_text(self):
        lines = []
        for name, entries in self._sections:
            lines.append("[" + name + "]")
            lines.extend(key + "=" + value for key, value in entries)
        return "\r\n".join(lines) + "\r\n"

    def save(self, path, encoding="utf-16"):
        """Atomic write. UTF-16 keeps the file readable by MaxScript getINISetting."""
        path = str(path)
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding=encoding, newline="") as stream:
            stream.write(self.to_text())
        os.replace(temporary, path)


def _find(entries, key):
    lowered = key.lower()
    for index, (existing, _) in enumerate(entries):
        if existing.lower() == lowered:
            return index
    return None


def to_bool(text, default=False):
    lowered = str(text).strip().lower()
    if lowered in ("true", "1", "yes", "on"):
        return True
    if lowered in ("false", "0", "no", "off"):
        return False
    return default


def to_int(text, default=0):
    try:
        return int(float(str(text).strip()))
    except (TypeError, ValueError):
        return default


def to_float(text, default=0.0):
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return default
