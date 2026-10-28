# Architecture

```
StartMaxPkg.ms ──python.ExecuteFile──▶ python/bootstrap.py ──▶ maxpkg_runtime.controller.Controller
                                       (stable anchor _maxpkg_runtime_session: stop old owner, reload package)
Controller
 ├─ ui.theme.ThemeService          Manager + toolbar themes (assets/themes/*/*.ini → assets/manager.qss)
 ├─ services.runtime.Runtime       state + operations (Python counterpart of the MaxScript MaxPkg facade)
 │   ├─ domain.settings            settings.ini, same keys as the MaxScript Runtime (UTF-16)
 │   ├─ domain.packages            manifest scanner, toolbar order, versions
 │   ├─ domain.api                 request fields + INI response parsing
 │   ├─ services.network           background HTTP (global QThreadPool), results on the main thread
 │   └─ services.max_api           the only pymxs boundary (run, fileIn, getDir) — main thread only
 ├─ services.images.ImageService   icons/screenshots: disk cache + decoded QImage in workers
 ├─ ui.toolbar.ToolbarController   native QToolBar in Max's main window or floating host
 └─ ui.manager_window.ManagerWindow (created on demand, destroyed on close)
     ├─ ui.frame.WindowChrome      own chrome: drag, resize, collapse to a mini bar
     ├─ ui.pages                   Discover, Installed/Updates
     ├─ ui.details                 Details (Description / Screenshots / Changelog / information)
     └─ ui.settings_panel          floating Settings window
```

## Layers and rules

| Layer | May import | Never |
|---|---|---|
| `domain/` | stdlib | Qt, pymxs |
| `services/` | domain, `qt_compat` (QtCore) | widgets; pymxs outside `max_api.py` |
| `ui/` | everything above | network or pymxs directly (go through `Runtime`) |

## Lifecycle

1. `bootstrap.launch()` sets a transition guard, stops the previous owner (raises and keeps it if cleanup
   fails), removes only `maxpkg_runtime*` modules, imports fresh code and starts a passive `Controller`.
2. `Controller.start()` loads settings (first run: imports the MaxScript Runtime's `settings.ini`), scans
   packages, builds the toolbar, schedules the update check and opens the Manager.
3. `Controller.stop()` stops timers, saves and destroys the window, removes the toolbar from Max's window,
   detaches from running network workers (late results are dropped) and releases services.

Closing the Manager destroys only the window. The Runtime keeps the toolbar and update checks.

## Data locations (per 3ds Max version, like the MaxScript Runtime)

| What | Where |
|---|---|
| Settings | `(getDir #temp)\MaxPkg-Runtime-Manager-Qt\settings.ini` |
| Logs | `…\MaxPkg-Runtime-Manager-Qt\logs\runtime-YYYY-MM-DD.log` |
| Image cache | `…\MaxPkg-Runtime-Manager-Qt\cache\images` (400 newest files) |
| Downloads | `…\MaxPkg-Runtime-Manager-Qt\downloads` (removed after install) |
| Packages | `(getDir #temp)\<guid>\`, `MaxPkg-Runtime-Manager\data\packages`, settings roots |

## Critical operations

Install, update, update-all and uninstall run through `Runtime._begin/_finish` (one at a time). Network
parts (resolve, download) run in workers; `fileIn` of the package MZP and uninstall hooks run on the main
thread; afterwards the Runtime rescans and verifies the GUID. Uninstall uses the same order and safety
checks as `core/uninstaller.ms`.
