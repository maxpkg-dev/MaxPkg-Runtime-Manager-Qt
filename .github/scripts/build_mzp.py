#!/usr/bin/env python3
"""Build and validate the public MaxPkg Runtime (Qt) MZP package (same flow as the MaxScript Runtime)."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path, PurePosixPath


REQUIRED_ENTRIES = {
    "mzp.run",
    "install.ms",
    "uninstall.ms",
    "StartMaxPkg.ms",
    "version.ini",
    "python/bootstrap.py",
    "python/entry.py",
    "python/startup.py",
    "python/open.py",
    "python/welcome.py",
    "python/stop.py",
    "python/maxpkg_runtime/controller.py",
    "assets/manager.qss",
    "assets/icons/maxpkg-logo.svg",
    "assets/themes/manager/default.ini",
    "assets/themes/toolbar/default.ini",
}

FORBIDDEN_FILES = {
    "settings.ini",
    "publish-release.bat",
}

FORBIDDEN_PREFIXES = (
    ".git/",
    ".github/",
    ".agents/",
    ".claude/",
    ".codex/",
    "docs/",
    "logs/",
    "tests/",
    "dist/",
)

SKIPPED_PARTS = ("__pycache__",)
SKIPPED_SUFFIXES = (".pyc", ".pyo", ".tmp", ".part")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version", help="Expected Runtime version")
    parser.add_argument("--notes-output", type=Path)
    parser.add_argument("--changelog", type=Path)
    return parser.parse_args()


def is_inside_root(file_path: Path, root_path: Path) -> bool:
    try:
        file_path.relative_to(root_path)
        return True
    except ValueError:
        return False


def read_manifest(manifest_path: Path) -> list[str]:
    entries = []
    for raw_line in manifest_path.read_text(encoding="utf-8").splitlines():
        manifest_entry = raw_line.strip()
        if manifest_entry and not manifest_entry.startswith("#"):
            entries.append(manifest_entry)

    if not entries:
        raise RuntimeError("The MZP file list is empty.")

    return entries


def collect_files(root_path: Path, manifest_path: Path) -> list[tuple[Path, str]]:
    collected = {}

    for manifest_entry in read_manifest(manifest_path):
        relative_path = Path(*PurePosixPath(manifest_entry).parts)
        source_path = (root_path / relative_path).resolve()

        if not is_inside_root(source_path, root_path):
            raise RuntimeError(f"MZP entry escapes the repository root: {manifest_entry}")
        if not source_path.exists():
            raise RuntimeError(f"MZP entry does not exist: {manifest_entry}")

        source_files = source_path.rglob("*") if source_path.is_dir() else [source_path]
        for file_path in source_files:
            if file_path.is_symlink():
                raise RuntimeError(f"Symbolic links are not allowed in the MZP: {file_path}")
            if not file_path.is_file():
                continue
            if any(part in SKIPPED_PARTS for part in file_path.parts) or file_path.suffix.lower() in SKIPPED_SUFFIXES:
                continue

            archive_path = PurePosixPath(file_path.relative_to(root_path)).as_posix()
            if archive_path in collected:
                raise RuntimeError(f"Duplicate MZP entry: {archive_path}")
            collected[archive_path] = file_path

    return [(file_path, archive_path) for archive_path, file_path in sorted(collected.items())]


def validate_archive_entries(archive_entries: set[str]) -> None:
    missing_entries = sorted(REQUIRED_ENTRIES - archive_entries)
    if missing_entries:
        raise RuntimeError("Required MZP entries are missing: " + ", ".join(missing_entries))

    forbidden_entries = []
    for archive_entry in archive_entries:
        if archive_entry in FORBIDDEN_FILES:
            forbidden_entries.append(archive_entry)
        if any(archive_entry.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            forbidden_entries.append(archive_entry)

    if forbidden_entries:
        raise RuntimeError(
            "Forbidden entries found in the MZP: " + ", ".join(sorted(set(forbidden_entries)))
        )


def read_runtime_version(version_path: Path) -> str:
    version_bytes = version_path.read_bytes()
    if version_bytes.startswith((b"\xff\xfe", b"\xfe\xff")):
        version_content = version_bytes.decode("utf-16")
    else:
        version_content = version_bytes.decode("utf-8-sig")
    version_match = re.search(r"(?m)^Version=(\d+\.\d+\.\d+)\s*$", version_content)
    if version_match is None:
        raise RuntimeError("Version was not found in version.ini.")

    runtime_version = version_match.group(1)
    version_parts = [int(part) for part in runtime_version.split(".")]
    if any(part > 9 for part in version_parts[1:]):
        raise RuntimeError("Minor and patch version components must be between 0 and 9.")

    return runtime_version


def extract_release_notes(changelog_path: Path, runtime_version: str) -> str:
    changelog_content = changelog_path.read_text(encoding="utf-8")
    latest_version_match = re.search(r"(?m)^## (\d+\.\d+\.\d+)\s*$", changelog_content)
    if latest_version_match is None:
        raise RuntimeError("CHANGELOG.md has no version sections.")
    if latest_version_match.group(1) != runtime_version:
        raise RuntimeError(
            "The latest CHANGELOG.md version does not match version.ini "
            f"({latest_version_match.group(1)} != {runtime_version})."
        )

    section_pattern = re.compile(
        rf"(?ms)^## {re.escape(runtime_version)}\s*\n(?P<notes>.*?)(?=^## |\Z)"
    )
    section_match = section_pattern.search(changelog_content)
    if section_match is None:
        raise RuntimeError(f"CHANGELOG.md has no section for {runtime_version}.")

    release_notes = section_match.group("notes").strip()
    if not release_notes:
        raise RuntimeError(f"CHANGELOG.md section {runtime_version} is empty.")

    return release_notes + "\n"


def write_checksum(output_path: Path) -> Path:
    checksum = hashlib.sha256(output_path.read_bytes()).hexdigest()
    checksum_path = output_path.with_suffix(".sha256")
    checksum_path.write_text(f"{checksum}  {output_path.name}\n", encoding="ascii")
    return checksum_path


def build_package(root_path: Path, manifest_path: Path, output_path: Path) -> Path:
    package_files = collect_files(root_path, manifest_path)
    archive_entries = {archive_path for _, archive_path in package_files}
    validate_archive_entries(archive_entries)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file_path, archive_path in package_files:
            archive.write(file_path, archive_path)

    with zipfile.ZipFile(output_path, "r") as archive:
        packaged_entries = set(archive.namelist())
        validate_archive_entries(packaged_entries)
        bad_entry = archive.testzip()
        if bad_entry is not None:
            raise RuntimeError(f"The MZP archive is corrupt at: {bad_entry}")

    return write_checksum(output_path)


def main() -> int:
    arguments = parse_arguments()
    root_path = arguments.root.resolve()
    manifest_path = arguments.manifest.resolve()
    output_path = arguments.output.resolve()

    runtime_version = read_runtime_version(root_path / "version.ini")
    if arguments.version and arguments.version != runtime_version:
        raise RuntimeError(
            f"Requested version {arguments.version} does not match version.ini ({runtime_version})."
        )

    if arguments.notes_output:
        if arguments.changelog is None:
            raise RuntimeError("--changelog is required with --notes-output.")
        release_notes = extract_release_notes(arguments.changelog.resolve(), runtime_version)
        arguments.notes_output.resolve().parent.mkdir(parents=True, exist_ok=True)
        arguments.notes_output.resolve().write_text(release_notes, encoding="utf-8")

    checksum_path = build_package(root_path, manifest_path, output_path)
    print(f"Built {output_path}")
    print(f"Built {checksum_path}")
    print(f"Runtime version: {runtime_version}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, RuntimeError, zipfile.BadZipFile) as error:
        print(f"Release build failed: {error}", file=sys.stderr)
        sys.exit(1)
