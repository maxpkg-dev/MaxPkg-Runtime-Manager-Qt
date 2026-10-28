# Release rules

Same flow as the MaxScript Runtime (`maxpkg-dev/MaxPkg-Runtime-Manager`). A release is prepared only when
the owner asks for it.

## Ownership

- The agent prepares the release files (version, changelog, checks). The owner reviews, commits and pushes.
- Publishing is started only when the owner explicitly asks to publish the reviewed release.
- Do not change the version during ordinary work.

## Version

- `version.ini` → `[Runtime] Version=major.minor.patch`, `Channel=<preview|stable>`.
- Minor and patch stay within 0–9 and carry like digits (`1.0.9` → `1.1.0`, `2.9.9` → `3.0.0`).
- Large update: minor +1, patch 0. Everything else: patch +1. Major only on request or minor overflow.

## Changelog

- `CHANGELOG.md`, newest version on top as `## <major.minor.patch>` (exactly this heading — the build reads it).
- One short, factual, user-facing entry per change, prefixed with its type, ordered `Added`, `Fixed`,
  `Changed`, `Improved`, `Removed`. Never rewrite older versions.

## Package

- `mzp.run` → `install.ms`. The archive contains only what `.github/mzp-files.txt` lists
  (`mzp.run`, `install.ms`, `uninstall.ms`, `StartMaxPkg.ms`, `version.ini`, `python/`, `assets/`).
- `.github/scripts/build_mzp.py` builds `dist/MaxPkg-Runtime-Manager-Qt.mzp`, checks required and forbidden
  entries, skips `__pycache__`/`*.pyc`, verifies the version against `CHANGELOG.md`, writes the release notes
  and the `.sha256` file. Local build:

  ```bat
  python .github\scripts\build_mzp.py --root . --manifest .github\mzp-files.txt --output dist\MaxPkg-Runtime-Manager-Qt.mzp --changelog CHANGELOG.md --notes-output dist\release-notes.md
  ```

  Without a system Python, run it with 3ds Max's interpreter (see `.agents/testing.md`).
- Never ship `tests/`, `docs/`, `logs/`, `.agents/`, `.claude/`, `.github/`, `publish-release.bat`, settings.

## Preparation sequence

1. Review the changes since the previous release; decide large or regular update.
2. Update `version.ini`, then add the version section to `CHANGELOG.md`; both versions must match.
3. Run the checks from `coding-rules.md` and report the results.
4. Show the prepared version and changelog summary to the owner and stop (no commit, tag or push).

## Publishing

1. The owner commits and pushes the release to `main`.
2. The owner runs `publish-release.bat` from the repository root. It reads the version, checks that the tree is
   clean, pushed and that the tag and release do not exist yet, asks Y/N and starts the GitHub Actions workflow
   `publish-runtime.yml`.
3. The workflow builds and validates the MZP on GitHub, creates tag `v<version>` and the GitHub Release
   (marked pre-release while `Channel=preview`) and uploads the MZP and its SHA-256 checksum.

First-time setup: `winget install --id GitHub.cli`, then `gh auth login`.
