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
- Highlight (ToolbarGlow) when the toolbar appears, moves or changes its look, and softer for a new button (not when
  it comes back with 3ds Max or after a self-update: it is where the user left it): a wash
  and a band sweeping along, only over the stretch with buttons (maxpkg button to the last button or `»`, measured
  every frame), never the empty rest of a docked toolbar. No box around it: two 2 px lines along the toolbar (top and
  bottom; left and right when vertical); the lines, the wash and the band fade out toward both ends.
- Buttons paint icon, name, version/developer line, update dot; `maxpkg` button shows the update count.
- Dragging a button reorders it once the press moves past the drag distance; a press that stays put is a click
  (Alt + drag still starts at once). The button lifts and follows the cursor, the others step aside to show where
  it will land, and on release it settles with a small bounce and a ring (DragStage paints this over the toolbar; the
  real buttons move on release; the ring is a RingBurst, a see-through window of its own that never takes the mouse
  or focus, so the toolbar's edges do not cut it off, the same as the rings around a newly installed script). On a locked toolbar the button shakes and a tooltip says why. Right click: Run, Details,
  Update, Move Left/Right, Hide from Toolbar, Toolbar settings; on `maxpkg`: Open Manager, Check Updates (packages
  and the Package Manager), Check Manager Updates (the Package Manager alone), Position, Hide toolbar.
- Never takes keyboard focus (Max shortcuts keep working).
- A favorite collection arranged as a toolbar on maxpkg.dev (`MaxPkg.installLayout "divider;GUID;GUID;divider;GUID"`,
  called by its Install all scripts installer): the packages not installed yet go through the install queue like
  `installMany`, then the toolbar takes the collection's order and dividers. The user's other buttons keep their
  places and the collection follows them as one block after a divider; a toolbar with no other buttons takes the
  layout as it is (a leading divider follows the maxpkg button). Packages that failed or have no toolbar button are
  left out with no empty divider; buttons of the collection the user had hidden show again; a locked toolbar keeps
  its order. Installing the same collection again gives the same toolbar. Dividers are the `divider` entries of
  `[Toolbar] Order`, like those added by hand.
