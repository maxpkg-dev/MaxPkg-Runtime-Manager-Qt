# Coding rules

Applies to everything under `python/`, `assets/`, `tests/` and the `.ms` launcher.

## Targets

- 3ds Max 2022–2027+: Python 3.7–3.13, PySide2 (2022–2024) and PySide6 (2025+).
- Python 3.7 syntax: no walrus, no `match`, no `list[str]`/`X | Y` annotations, no f-string `=`.
- Import Qt only from `maxpkg_runtime.qt_compat`. Use short enum names (`Qt.AlignCenter`) — both bindings
  accept them. Binding differences (QAction/QShortcut location, `exec_`, event positions) live there.
- Only the Qt and Python that ship with Max. Never install packages into Max's Python.

## Structure

- `domain/` is pure Python (stdlib only) and has unit tests.
- `services/max_api.py` is the only module that imports `pymxs`; call it on the main thread only.
- Workers (`NetworkService.submit`) receive and return plain data (str, bytes, `QImage`, domain objects).
  Never touch widgets, `Runtime` state or pymxs in a worker.
- UI talks to `Runtime`; it never calls the network or pymxs directly.
- Importing any module has no side effects (no windows, no scene access, no network).

## Lifecycle

- Everything a lifecycle creates is owned by `Controller` (or a child it owns) and released in `stop()`.
- Long-lived signals (Runtime, ThemeService) are disconnected explicitly when a window is destroyed.
- Hide before `deleteLater()`. Detach toolbars from Max's window immediately (`setParent(None)`).
- Never call `rt.quitMax`, never kill threads or processes, never create a second `QApplication`.
- Settings save immediately after a change; no Save/Cancel.

## Style

- Idiomatic Python, PEP 8, 120 columns, descriptive names. Docstring on every module and public class.
- Do not shadow Qt API names in QWidget subclasses (`update`, `window`, `show`, `close`, `move`...).
- Every color comes from a theme token; every icon is a Lucide SVG from `assets/icons`.
- Shared controls are implemented once in `ui/widgets.py`; dialogs compose them.
- Texts follow the HTML Manager (docs/ORIGINAL-SPEC.md) unless the change is documented in docs/UI.md.

## Compatibility contract

- `settings.ini` sections/keys stay compatible with the MaxScript Runtime (`domain/settings.py`).
- `manifest.ini` is the only package source of truth; keep all documented key aliases.
- The API base is `https://maxpkg.dev/api/runtime/v1/` (override in `[Endpoint] apiEndpoint`).

## Checks before handing work back

1. `tests/run_unit.py` in Max (compile + unit tests) — must be `UNIT OK`.
2. `tests/max/launch.py` — `LAUNCH OK`, one toolbar.
3. `tests/max/stress.py` for lifecycle changes — `STRESS OK`.
4. Screenshots of every changed screen (`tests/max/ui_driver.py`), reviewed visually.
5. No commit or push unless the owner asks.
