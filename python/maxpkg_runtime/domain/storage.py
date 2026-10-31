"""Local folders the Package Manager fills by itself, such as the image cache: how much they hold and emptying them."""

import os


def folder_usage(folder):
    """(files, bytes) of the files directly inside `folder`; (0, 0) when it does not exist."""
    files = 0
    total = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0, 0
    for name in names:
        file_path = os.path.join(folder, name)
        try:
            if os.path.isfile(file_path):
                total += os.path.getsize(file_path)
                files += 1
        except OSError:
            pass
    return files, total


def clear_folder(folder):
    """Remove the files directly inside `folder` (subfolders stay). Returns (removed, bytes freed).

    A file that cannot be removed (still being written, locked) is skipped.
    """
    removed = 0
    freed = 0
    try:
        names = os.listdir(folder)
    except OSError:
        return 0, 0
    for name in names:
        file_path = os.path.join(folder, name)
        try:
            if not os.path.isfile(file_path):
                continue
            size = os.path.getsize(file_path)
            os.remove(file_path)
        except OSError:
            continue
        removed += 1
        freed += size
    return removed, freed


def size_text(size):
    """'0 KB', '340 KB', '16.4 MB', '1.2 GB'."""
    if size < 1024 * 1024:
        return "{} KB".format(int(round(size / 1024.0)))
    if size < 1024 * 1024 * 1024:
        return "{:.1f} MB".format(size / (1024.0 * 1024))
    return "{:.1f} GB".format(size / (1024.0 * 1024 * 1024))


__all__ = ["clear_folder", "folder_usage", "size_text"]
