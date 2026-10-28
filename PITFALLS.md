# Pitfalls

Real traps hit while building this Runtime (3ds Max 2027, PySide6 6.8.3, Python 3.13), and the
MaxScript Runtime problems it replaces. Read before changing lifecycle, threading, Qt widgets or the API.

## 3ds Max / threading

- **Never run MaxScript or pymxs outside the main thread.** The HTML Runtime ran MaxScript inside
  `CSharpUtilities.SynchronizingBackgroundWorker.DoWork` (update checks, self-update). That is the most likely
  cause of "MAXScript Garbage Collection Error". Workers here receive plain data and return plain data;
  `services/max_api.py` is the only pymxs boundary.
- **Never block the main thread on the network.** The HTML Manager froze Max ~22 s when opening Details.
  All HTTP runs in `NetworkService` (Qt global thread pool).
- `python.ExecuteFile` runs the file as `__main__`; `bootstrap.py` launches only under that guard.
- Text fields must call `qt_compat.disable_max_accelerators(widget)`, otherwise Max shortcuts eat keys.
- Max's main window is a `QMainWindow`; its toolbars are `QToolBar`s, so ours can dock natively.

## Qt lifetime

- `deleteLater()` runs only when control returns to the **outer** event loop. Inside a long script or a
  restart loop, deleted widgets still exist (`findChildren` still sees them). Detach first
  (`removeToolBar` + `setParent(None)`), and **hide before deleteLater**, or ghosts stay painted.
- Do not own a `QThreadPool`: destroying it waits for every running request (up to the HTTP timeout).
  Use `QThreadPool.globalInstance()`; keep the result relay object parentless and referenced by the tasks.
- `processEvents()` once is not enough before `grab()` — nested layouts settle over several loop turns.
  Tests use `ui_driver.pump()`.
- Qt can call `eventFilter` **while** `installEventFilter`/`setWidget` run: every attribute the filter reads
  must already exist (`QScrollArea.setWidget` → `InstalledPage.eventFilter`; `WindowChrome` mini bar).
- Never name methods or attributes like QWidget API: `update(guid)` shadowed `QWidget.update()`,
  `self.window = ...` shadows `QWidget.window()`. Use `update_package`, `manager_window`.
- `widget.style()` can return a wrapper whose C++ style was deleted (another tool replaced the app style);
  `widgets.repolish` falls back to re-setting the widget's own sheet.
- Frameless + rounded windows need `WA_TranslucentBackground` and our own paint; keep overlays inside
  `content_rect()` so they stay within the rounded shape.

## QSS / painting

- QSS alpha is 0..255, theme INI alpha is 0..1 — always convert with `theme.css_color`.
- A comment like `@tokens` in QSS is replaced like a token; unknown tokens must be left untouched.
- `%`-formatting CSS (`150%`) breaks: use `str.format` with doubled braces.
- `QComboBox` needs its own view (`QListView`) to make the popup stylable; arrow drawn by an IconLabel.

## API

- The API rejects unknown channels with HTTP 400. The package channel sent to the API (`api_channel`,
  "stable") is not the Runtime build channel from `version.ini` ("preview").
- INI values are single lines: `FullDescription` contains a literal `\n` that must become a line break.
- Responses may describe packages for newer Max releases: filter by `Min3dsMax` on the client.
- Category/collection icons come from the API as names; only known Lucide names are used.

## Compatibility

- `MaxPkg` is the MaxScript global of the old Runtime. Do not define it while the old Runtime runs
  (preview builds run side by side). A compatible facade is planned for the switch-over.
- Keep Python 3.7 syntax for 3ds Max 2022 (no walrus, no `list[str]` annotations, no `match`).
- `settings.ini` is UTF-16 LE (written by MaxScript `setINISetting`); manifests are UTF-8.
