"""Text shown to users in notifications: never a raw web address.

Network errors (Qt, curl) and service answers can carry the request URL; a notification names the package and the
problem instead. The full text stays in the log.
"""

import re

# An address stops before brackets and does not take the sentence's closing punctuation with it.
_LINK = re.compile(r"(?:https?://|www\.)[^\s<>\"'()\[\]{}]*[^\s<>\"'()\[\]{}.,;:!?]", re.IGNORECASE)
_EMPTY_BRACKETS = re.compile(r"[(\[{<]\s*[)\]}>]")
_SPACES = re.compile(r"[ \t]{2,}")
_SPACE_BEFORE_PUNCTUATION = re.compile(r"\s+([.,;:!?])")
_DANGLING = re.compile(r"(?:\s*[-:,]\s*)+$")


def without_links(text):
    """`text` with every http(s):// or www. address removed; lines left empty are dropped."""
    if not text:
        return text or ""
    lines = []
    for line in str(text).split("\n"):
        if not _LINK.search(line):
            lines.append(line)
            continue
        cleaned = _LINK.sub("", line)
        cleaned = _EMPTY_BRACKETS.sub("", cleaned)
        cleaned = _SPACE_BEFORE_PUNCTUATION.sub(r"\1", _SPACES.sub(" ", cleaned))
        cleaned = _DANGLING.sub("", cleaned).strip()
        if cleaned and cleaned not in (".", ",", ":", ";", "-"):
            lines.append(cleaned)
        elif lines and lines[-1].rstrip().endswith(":"):  # "Download from:" lost what it introduced
            lines[-1] = lines[-1].rstrip()[:-1]
    return "\n".join(lines).strip()


__all__ = ["without_links"]
