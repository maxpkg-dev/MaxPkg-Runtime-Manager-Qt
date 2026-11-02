# Upgrading from MaxPkg Runtime 1.x

How `install.ms` replaces the MaxScript Runtime, and what the user keeps. Runtime 1.2.1 starts this installer itself
(its `[manager2]` section in `version.ini`); dragging the MZP into a viewport runs the same code.

## Installer contract

Runtime 1.2.1 relies on this. Do not change it without changing that Runtime:

- The release asset is named `MaxPkg-Runtime-Manager-Qt.mzp`.
- `install.ms` returns nothing through `fileIn`. After a success the global `MaxPkg` belongs to 2.0 (`isPackageManager`),
  and `MaxPkg-Runtime-Manager-Qt\python\startup.py`, `MaxPkg-Runtime-Manager-Qt\version.ini` and the startup script
  `maxpkg-runtime-qt-startup.ms` exist.

## Order of the steps

1. Stop a running 2.0, copy the program and write the MacroScript. A failure here leaves 1.x running and untouched.
2. Write `version.ini` and the startup script. From here on 1.x no longer starts (1.2.1 checks for them).
3. Stop 1.x in this session, which frees the `MaxPkg` global, and copy its `settings.ini`.
4. Start 2.0. If it does not start, the startup script and `version.ini` are taken back and 1.x starts again.
5. Delete the 1.x files. A failure here is only logged: 2.0 already runs.

## Folders shared with another 3ds Max

The startup, macro and temp folders count as this 3ds Max's own when they are inside `getDir #maxData`
(`...\2024 - 64bit\ENU\`). A folder set up by hand may be shared, so if any of the three is elsewhere, nothing of 1.x is
deleted: an older 3ds Max may still use it, and the 1.x startup script loads the program files by a fixed path.
A kept `startup.ms` older than 1.2.1 has no check for 2.0, so it moves to `startup-1x.ms` behind a small one that has.

The 2.0 startup script and action do nothing on 3ds Max older than 2022, and look the program up in the temp folder of
the 3ds Max running them, never by a fixed path. Installations that reach a new version by self-update keep the startup
script they already have: self-update does not rewrite it.

## What carries over

- **Installed packages** stay in `MaxPkg-Runtime-Manager\data\packages\`, because their own scripts point there.
  2.0 keeps that folder in its package roots. Package roots added by the user carry over too.
- **`settings.ini`**, same sections and keys: toolbar order, hidden buttons, visibility, position, floating places, button
  and icon size, density, second line and theme; Manager theme, sort, filter, card style, last tab, window place and size;
  update frequency, notifications, automatic checks and downloads, and the known updates; start with 3ds Max; developer
  options and the service address.

Covered by `tests/unit/test_legacy_migration.py`.

## What does not carry over

| Item | What happens |
|---|---|
| The `MaxPkg_Manager` action placed on a user's own toolbar, menu or hotkey | Its button stops working. 2.0's action is `MaxPkg_Qt_Manager` (category `MaxPkg`), and the user has to add it again. |
| 1.x logs (`logs\`) | Deleted with the program; 2.0 starts its own log. |
| Image cache | Not moved; 2.0 downloads pictures again when needed. |
| `Endpoint.BaseUrl`, `Updates.BatchUrl`, `Updates.RuntimeUrl` | Not read. These keys are from before 1.x moved them to `Endpoint.apiEndpoint`, which it does on its first start. |
| The look of the toolbar | The settings carry over, but it is a new toolbar with its own drawing. One divider is added after the MaxPkg button. |
| Automatic Runtime updates turned off in 1.x | Stay off: `AutoCheckRuntime` is the same setting, so such a user gets no 2.0 self-updates until it is turned on. |

Uninstalling 2.0 does not bring 1.x back.
