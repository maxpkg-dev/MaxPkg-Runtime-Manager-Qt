# Pitfalls

Real traps hit while building this Runtime (3ds Max 2027, PySide6 6.8.3, Python 3.13), and the
MaxScript Runtime problems it replaces. Read before changing lifecycle, threading, Qt widgets or the API.

## 3ds Max / threading

- **Never run MaxScript or pymxs outside the main thread.** The HTML Runtime ran MaxScript inside
  `CSharpUtilities.SynchronizingBackgroundWorker.DoWork` (update checks, self-update). That is the most likely
  cause of "MAXScript Garbage Collection Error". Workers here receive plain data and return plain data;
  `services/max_api.py` is the only pymxs boundary.
- **Never block the main thread on the network.** The HTML Manager froze Max ~22 s when opening Details.
  All HTTP runs through `QNetworkAccessManager` (`NetworkService`): it is asynchronous on the main thread.
  Python worker threads starve in 3ds Max 2022 (the GIL is rarely released there), so the catalog never
  loaded while HTTP ran in a thread pool.
- Render SVG (`QSvgRenderer`) on the main thread only: several renderers in pool threads made icons fail.
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
- Translucent (`WA_TranslucentBackground`) windows get **no Windows shadow**. On Windows 11 keep frameless
  windows opaque and let DWM round them and draw the shadow (`frame.apply_native_frame`: extend frame by
  1 px, `DWMWA_WINDOW_CORNER_PREFERENCE`, `DWMWA_BORDER_COLOR`). Only older Windows paints the rounded
  shape itself. Keep overlays inside `content_rect()`. `grab()` screenshots never show the DWM shadow
  (check it with `QScreen.grabWindow(0, ...)` around the window).
- DWM shadows only windows with a frame style: `apply_native_frame` adds `WS_THICKFRAME | WS_CAPTION`, and
  every such window must forward `nativeEvent` to `frame.native_event`, which answers `WM_NCCALCSIZE` so no
  Windows border appears (and insets a maximised window by the resize border).
- `sys.getwindowsversion()` inside 3ds Max reports build 9200 (the Max manifest declares no Windows 10/11
  support), which silently disabled every Windows 11 path. `frame._windows_build` uses `RtlGetVersion`.
- A window-wide `QShortcut` (Esc) fires before a child overlay's `keyPressEvent`: the Manager's Esc handler
  closes the screenshot lightbox first.
- **Never use `QMessageBox`/`QInputDialog` inside the Manager.** They inherit the Manager stylesheet (light
  text) but keep native white buttons: the buttons look empty. Use `ui/dialogs.confirm`.

## QSS / painting

- QSS alpha is 0..255, theme INI alpha is 0..1 — always convert with `theme.css_color`.
- A comment like `@tokens` in QSS is replaced like a token; unknown tokens must be left untouched.
- `%`-formatting CSS (`150%`) breaks: use `str.format` with doubled braces.
- `QComboBox` needs its own view (`QListView`) to make the popup stylable; arrow drawn by an IconLabel.
- **Qt 5 (3ds Max 2022) drops `border-radius` completely when two radii do not fit the height** — even when
  they are exactly equal to it (16 px tall, 8 px radius = square). Qt 6 only shrinks them, so 2027 looks fine.
  Give pills an explicit `min-height`/`max-height` and a radius strictly below half the total height.
- The base rule is a bare `QWidget {...}`: a `#Window QWidget` rule outranks `#Title` and breaks styling.
- Word-wrapped labels in a layout item with an alignment flag get too little height and are cut: add them
  full width and align the text instead.
- Button icons: `ThemeService` pads icons of buttons with text (gap on the text side, 1 px lower). Buttons
  whose text or layout direction change must re-apply the icon (`Button` does it; `ThemeService.reapply`).
- `version.ini` may be UTF-16 (MaxScript `setINISetting`, the old Runtime's format): read it with
  `IniDocument`, never `configparser(encoding="utf-8")` — that crashed the launcher.

## API

- The API rejects unknown channels with HTTP 400. The package channel sent to the API (`api_channel`,
  "stable") is not the Runtime build channel from `version.ini` ("preview").
- INI values are single lines: `FullDescription` contains a literal `\n` that must become a line break.
- Responses may describe packages for newer Max releases: filter by `Min3dsMax` on the client.
- Category/collection icons come from the API as names; only known Lucide names are used.

## Compatibility

- **The `MaxPkg` global is required.** Package installers made by MaxPkg Packager install silently only when
  `MaxPkg` exists (otherwise they open their own "Install Package" window) and then call
  `MaxPkg.packageInstalled guid`; the maxpkg.dev one-click installer calls `isStarted`/`start`/`install` and
  offers the *old* Runtime when `MaxPkg` is missing. `max_api.define_facade` creates a MaxScript struct with the
  old public API whose calls go to `Controller.maxscript_call`; it is defined even when start-with-Max is off.
- The facade instance must survive `MaxPkg.start()`: that call launches a new Controller while the same
  instance waits for its reply, so `define_facade` keeps an instance of the same version.
- **Never start our Python with `python.ExecuteFile`.** Run while Python is already on the stack (a package
  installed by the Manager calling `MaxPkg.start()`, a Max action clicked during a nested event loop) it keeps the
  caller's `__file__`: `bootstrap.py` then stopped the running Manager and failed to load from the caller's
  folder. `StartMaxPkg.ms`, the startup script, the MacroScript, `install.ms`, `uninstall.ms` and the facade use
  `python.Execute "import runpy; runpy.run_path('<absolute path>', run_name='__main__')"` (forward slashes,
  `'` escaped).
- 3ds Max accelerators take Esc and the arrow keys before Qt: overlays that need them call
  `qt_compat.disable_max_accelerators` and keep their buttons `NoFocus`.
- `MaxPkg` is the MaxScript global of the old Runtime. Do not define it while the old Runtime runs
  (preview builds run side by side). `install.ms` removes the old Runtime first (`MaxPkg.shutdown()`, its
  startup script and MacroScripts, its program files in `#temp\MaxPkg-Runtime-Manager\`); it moves
  `settings.ini` into the new data folder and keeps `data\packages\` because installed packages point there.
- Keep Python 3.7 syntax for 3ds Max 2022 (no walrus, no `list[str]` annotations, no `match`).
- `settings.ini` is UTF-16 LE (written by MaxScript `setINISetting`); manifests are UTF-8.
