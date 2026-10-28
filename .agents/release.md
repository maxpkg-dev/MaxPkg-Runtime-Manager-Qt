# Release

A release is prepared only when the owner asks. Agents prepare files; the owner reviews, commits, pushes
and publishes.

1. Version in `version.ini` (`major.minor.patch`, minor and patch 0–9, carry like digits; large update →
   minor +1, otherwise patch +1). `Channel` is the Runtime build channel (`preview` until the Qt Runtime
   replaces the MaxScript one, then `stable`).
2. Newest entry on top of `CHANGELOG.md`, grouped `Added`, `Fixed`, `Changed`, `Improved`, `Removed`;
   short, factual, for 3D artists.
3. Run all checks from `coding-rules.md` and report results.
4. Package with the official MaxPkg Packager (`maxpkg-dev/max-dev-tool`, pinned commit) through
   `MaxPkgPackerApi` in Max; entry = `StartMaxPkg.ms`, `compileEntry=false`; runtime allowlist:
   `StartMaxPkg.ms`, `version.ini`, `python/`, `assets/`. Never ship `tests/`, `docs/`, `logs/`, `.agents/`.
5. Verify the archive (manifest, version, inventory, checksum) before reporting it built.
6. Stop without committing, tagging or pushing.

Open question before the first release: how the Qt Runtime replaces the MaxScript Runtime on users'
machines (MaxScript `MaxPkg` facade, startup shim, migration of the toolbar). See README "Status".
