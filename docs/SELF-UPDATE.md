# Package Manager self-update

The installed Package Manager updates itself from the GitHub Releases of `maxpkg-dev/MaxPkg-Runtime-Manager-Qt`.
The idea comes from the MaxScript Runtime (`core/self-updater.ms`: compare `version.ini` and channel, download,
copy over the installed folder except the user's data, restart); the weak points were fixed.

| MaxScript Runtime | Package Manager (Qt) |
|---|---|
| Takes the `main` branch archive | Takes a published **release** (`MaxPkg-Runtime-Manager-Qt.mzp`) |
| No integrity check | The MZP must match the published `MaxPkg-Runtime-Manager-Qt.sha256`; no checksum = no update |
| `SynchronizingBackgroundWorker` runs MaxScript off the main thread (likely cause of the GC error) | Qt network in the event loop, no threads; the file swap is a short main-thread step |
| Copies file by file over the running code | Unpacks to a staging folder, checks the layout and version, swaps whole folders |
| A failed copy leaves a half-updated Runtime | `python/` and `assets/` are renamed to `.old`; any failure, or a new version that does not start, restores them |
| Channel `stable`/`preview` must equal the remote one | `stable` takes stable releases only; `preview` takes pre-releases and stable ones; the newest version wins |

## Flow

1. **Check** (`services/self_update.py`): 7 s after every start while *Check Package Manager updates automatically*
   is on (the interval does not apply); or Settings > Updates > *Check for updates*.
   GET `https://api.github.com/repos/.../releases?per_page=15` -> `domain/self_update.parse_releases/select_update`.
2. **Install without asking**: a newer release found by the startup check is installed at once. Only a running
   package operation delays it (retried every 15 s for up to 5 minutes, then a toast with an *Update* button). An
   open Manager is reopened after the restart. A manual *Check for updates* offers the update with a button.
3. **Download + verify**: the `.sha256` file, then the `.mzp` into `downloads/`; SHA-256 must match (`domain/integrity`).
4. **Unpack** safely (`safe_extract` refuses paths outside the folder), find the program root, check that its
   `version.ini` equals the release version.
5. **Swap** (`python/entry.py: apply_update`, outside the reloadable package): stop the running Runtime, replace
   `python/`, `assets/`, `StartMaxPkg.ms`, `version.ini`, `uninstall.ms` (the old ones stay as `*.old`), start the
   new code through `bootstrap.py`. If it does not start, the swap is undone and the old code starts again.
6. The new Runtime says *Package Manager updated to X*, reopens the Manager if it was open and deletes the `.old`
   copies after 30 s. `settings.ini`, `logs/`, `cache/`, `downloads/` are never touched.

A folder with `.git`, `.github` or `tests/` (a source checkout) is never overwritten: it only reports a new version.

## Release rules

- Publish through `publish-release.bat` as before: the workflow attaches both `MaxPkg-Runtime-Manager-Qt.mzp` and
  `MaxPkg-Runtime-Manager-Qt.sha256`. A release missing either file is ignored by the updater.
- The tag is `vX.Y.Z` and must equal `Version=` in the MZP's `version.ini`.
- Updating from a version older than the first one with this feature still needs a manual reinstall.

## Tests

- `tests/unit/test_self_update.py`: release choice, checksum text, unsafe archives, swap and rollback (run with `tests/run_unit.py`).
- `tests/max/self_update_e2e.py` (inside Max): wrong checksum refused, automatic update from a file:// feed, rollback of
  a release that does not start. It backs up and restores the installed copy and restarts the Runtime several times.
- Only this repository's releases are used: both files must come from
  `https://github.com/maxpkg-dev/MaxPkg-Runtime-Manager-Qt/releases/download/`, and nothing in the environment can change
  that. The in-Max test points `releases_url` and `download_prefix` of its own updater object at a local feed.
