# Changelog

## 2.0.2

- Fixed: On 3ds Max older than 2022 the installer says which version is needed and changes nothing; earlier tools and the previous MaxPkg Runtime keep working.
- Changed: The Default toolbar theme takes its colors from 3ds Max, so the toolbar matches light, dark and custom Max colors; it replaces the separate 3ds Max (native) theme.
- Changed: The maxpkg.dev link at the bottom of the Manager opens the catalog.

## 2.0.1

- Fixed: The Screenshots and Changelog counts in package details sit right after their tab titles, under the same underline.
- Changed: A new toolbar starts at the top with large icons only; Reset toolbar defaults returns to this look.

## 2.0.0

- Added: The Manager, toolbar and Settings run on the Qt and Python that ship with 3ds Max, without the embedded web browser.
- Added: The window has its own rounded frame: drag the header to move it, double-click to maximise, collapse it to a small bar and open it again with one click.
- Added: The window remembers its place, size and maximised state, and returns to 3ds Max when its last place is no longer on screen.
- Added: Settings open in a separate window that stays above the Manager and remembers its place and last page.
- Added: Keyboard shortcuts: Ctrl+F search, Esc back or clear, F5 refresh, Ctrl+1/2/3 tabs, Ctrl+, Settings.
- Added: Toolbar buttons can be moved and hidden from their right-click menu; the MaxPkg button offers Open Manager, Check Updates and position choices.
- Added: The 3ds Max (native) toolbar theme follows the colors of 3ds Max.
- Added: Toolbar buttons and dividers are arranged by dragging; Lock Toolbar keeps them in place.
- Added: Toolbar dividers: add any number from a button's menu; one follows the MaxPkg button by default.
- Added: The MaxPkg button menu sets the toolbar look: position, spacing, icon size, button style and second line.
- Added: A red Uninstall item in a toolbar button's menu, and Browse More Scripts to open Discover.
- Added: Right-click a package card for its menu: Install or Run, Update and What's new, Details, Help, Package page and Copy link.
- Added: Package details show the rating and downloads first, and a Package page link to maxpkg.dev.
- Added: Notifications offer the next step, such as Run after an install, Try Again or Undo.
- Added: Support MaxPkg: the heart button in the header explains how donations keep MaxPkg running.
- Added: A Warm Graphite theme for the Manager and the toolbar.
- Added: When 3ds Max cannot reach the internet directly, requests use the Windows proxy and Windows curl.
- Fixed: Loading the catalog, package details and images no longer freezes 3ds Max.
- Fixed: Update marks on small toolbars no longer cover the icons.
- Fixed: Package descriptions keep their line breaks as on maxpkg.dev.
- Fixed: The MaxPkg page link opens the package page.
- Fixed: The resize cursor no longer stays on the header after leaving the window edge.
- Changed: The toolbar docks like other 3ds Max toolbars; buttons that do not fit open from the » menu.
- Changed: Package cards adapt their columns to the window width, and the whole card opens Details.
- Changed: Package screenshots open in a full-window preview with arrow-key navigation.
- Changed: The screenshot preview shows the window blurred behind the image and closes when the image is dragged away.
- Changed: Install, Run and Uninstall sit next to the package name in Details.
- Improved: Download counts are shortened (1.1K, 2.5M) and the rating is shown with stars.
- Improved: Close buttons turn red on hover.
