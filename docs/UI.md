# UI

Baseline: the HTML Manager 1.2.0 (see `ORIGINAL-SPEC.md` and `original/`). Screens, texts, order of
elements and breakpoints are kept. Current screenshots: `screenshots/qt-*.png`.

## Design system

- Colors: semantic tokens from `assets/themes/manager/*.ini` (same files as the MaxScript Runtime),
  rendered into `assets/manager.qss` (`@token`). Default theme: **Default** (the original look), six themes.
- Toolbar colors: `assets/themes/toolbar/*.ini` plus **3ds Max (native)**, built from Max's own palette.
- Icons: Lucide SVG in `assets/icons`, recolored per theme and rendered at the device pixel ratio.
- Shared controls live in `ui/widgets.py` (Button variants, IconButton, Badge, SearchBox, Dropdown,
  ClearableDropdown, Switch, ElidedLabel, ElidedText, StatePanel, ResponsiveGrid, FlowRow, menus).
  Dialogs compose them; no per-dialog restyling.
- Typography: Segoe UI 13 px (titles 14–18 px bold, meta 11 px), like the HTML Manager.
- Scrollbars: thin pills (4 px, 6 px on hover), no arrows.

## Responsive rules

| Width | Behaviour |
|---|---|
| ≥ 1200 | Discover categories in the left panel |
| < 1200 | Categories in a dropdown beside search |
| < 900 | Details in one column |
| < 800 | Header buttons icon-only (720 in HTML; the header also holds window buttons) |
| < 760 | Toolbar Configurator labels above their buttons (Settings width) |
| 680 | Minimum width |

Card grids compute their column count from the width (1–4) instead of the fixed 3 columns.

## Improvements over the HTML Manager

| Area | Change | Why |
|---|---|---|
| Window | Own chrome: rounded frameless window, header is the title bar, collapse to a mini bar (TerraScoop behaviour), edges resize | Consistent with MaxPkg tools, no duplicated title |
| Window | Remembers place, size, maximised state, collapsed-bar position; off-screen places fall back to the Max centre | Owner request |
| Settings | Separate floating window (stays above the Manager), remembers place, size and last page, icons in navigation | Watch the toolbar/theme change live; nothing is blocked |
| Loading | Catalog loads asynchronously; only install/uninstall show the blocking overlay | HTML blocked Max during every request |
| Cards | Whole card opens Details | Larger target |
| Search | Clear button, Esc clears, Ctrl+F focuses | Speed |
| Keyboard | Esc back from Details, F5 refresh, Ctrl+1/2/3 tabs, Ctrl+, Settings | Speed |
| Details | Screenshot viewer with full-window preview (← → Esc) | — |
| Toolbar | See below | — |

## Toolbar

- Docked: native `QToolBar` in Max's main window, one `QWidgetAction` per button, so Qt's chevron `»`
  shows the buttons that do not fit. Drag its handle to another edge: the position is saved.
- Floating: frameless tool window with the dotted grip of the HTML toolbar; clamped to the work area.
- Never rebuilt: buttons are added, removed, reordered and restyled individually.
- Buttons paint icon, name, version/developer line, update dot; `maxpkg` button shows the update count.
- Alt + drag reorders (live in floating mode; insertion line when docked). Right click: Run, Details,
  Update, Move Left/Right, Hide from Toolbar, Toolbar settings; on `maxpkg`: Open Manager, Check Updates,
  Position, Hide toolbar.
- Never takes keyboard focus (Max shortcuts keep working).
