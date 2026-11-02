"""SHA-256 check of a downloaded package against the hash the MaxPkg service published for it.

The moderator reviews one exact .mzp file; the hash in the API response that gave the download link proves the
downloaded file is that file (no swap in storage, no damage in transfer). It does not protect against a compromised
site, which would publish a matching hash: that needs a signature.
"""

import hashlib
import re

MATCH = "match"              # the file is the published one
MISMATCH = "mismatch"        # different file, or a published value that is not a SHA-256
UNPUBLISHED = "unpublished"  # the service has no hash for this version yet (versions imported before hashes)
UNREADABLE = "unreadable"    # the file could not be read to compute its hash

SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
CHUNK = 1024 * 1024


def file_sha256(file_path):
    """Lower-case hex SHA-256 of a file, read in chunks (a package is never loaded whole). Raises OSError."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as stream:
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(file_path, expected):
    """(result, actual hash) of a downloaded file against the published `expected` value.

    `expected` is compared without regard to case or surrounding spaces; an empty value is UNPUBLISHED, any other
    value that is not 64 hex characters is a MISMATCH. `actual` is '' when the file could not be read.
    """
    try:
        actual = file_sha256(file_path)
    except OSError:
        return UNREADABLE, ""
    published = (expected or "").strip().lower()
    if not published:
        return UNPUBLISHED, actual
    if not SHA256_PATTERN.match(published) or published != actual:
        return MISMATCH, actual
    return MATCH, actual


__all__ = ["MATCH", "MISMATCH", "UNPUBLISHED", "UNREADABLE", "file_sha256", "verify_file"]
