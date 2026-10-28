# CLAUDE.md

MaxPkg Runtime Manager on **Python + Qt** for 3ds Max 2022–2027+. Rewrite of the MaxScript + HTML
(dotNet WebBrowser) Runtime, repository `maxpkg-dev/MaxPkg-Runtime-Manager` (read only — never modify it).
Owner: Lukianenko Vasyl (3DGROUND). Everything in this repository is written in English only.

Read first:

- `.agents/coding-rules.md` — targets, layers, lifecycle and style rules.
- `.agents/testing.md` — how to run tests and take screenshots in Max through Max Ultra MCP.
- `.agents/release.md` — release preparation (only when asked).
- `.agents/pitfalls.md` — traps already hit; check before touching lifecycle, threads, Qt widgets or the API.
- `docs/ARCHITECTURE.md`, `docs/UI.md`, `docs/ORIGINAL-SPEC.md` (+ `docs/original/` screenshots).

Key decisions

- UI/UX follows the HTML Manager 1.2.0; documented improvements are listed in `docs/UI.md`.
- Own window chrome like TerraScoop (rounded, header = title bar, collapse to a mini bar, remembered geometry).
- `pymxs` only in `services/max_api.py`, only on the main thread; workers are pure Python.
- Settings stay in the MaxScript Runtime's `settings.ini` format; first run imports the old file.
- Packaging and releases follow the MaxScript Runtime: `mzp.run` → `install.ms`, `.github/mzp-files.txt`,
  `.github/scripts/build_mzp.py`, GitHub Actions `publish-runtime.yml` started by `publish-release.bat`.
- No personal data in the repository: no user names, machine paths, e-mail addresses or tokens.

Do not commit, push or publish unless the owner asks.
