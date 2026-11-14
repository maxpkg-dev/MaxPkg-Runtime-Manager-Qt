# Changelog

## 2.1.5

- Changed: A new install updates scripts automatically: Download updates automatically is on by default, and the welcome window starts with Automatically chosen. If you already chose, your choice stays.
- Fixed: Download updates automatically now installs the updates the automatic check finds, one after another, each with its own message. Before, it only found them.

## 2.1.4

- Added: A favorite collection arranged as a toolbar on maxpkg.dev installs with the same order and dividers. Your other toolbar buttons keep their places and the collection follows them after a divider; on a toolbar with no other buttons it is set up exactly as on the site. Scripts already installed are not installed again, only moved into place, and installing the collection again gives the same toolbar.
- Changed: Buttons of the collection you had hidden show again; a locked toolbar keeps its order and says so.

## 2.1.3

- Added: Dragging a script on the toolbar lifts it and lets it follow the cursor while the other buttons step aside to show where it will land; on release it settles in with a small bounce and a ring.
- Added: On a locked toolbar a dragged button shakes, next to the tip that the toolbar is locked.
- Fixed: The rings around a newly installed script and around a dropped button are no longer cut off at the toolbar's edges.

## 2.1.2

- Added: Check Updates also checks the Package Manager itself and installs a newer version right away, or as soon as a running package operation ends. One message tells both results, and a failed check never hides the other one.
- Added: The toolbar's MaxPkg menu has Check Manager Updates, which checks and installs only the Package Manager.
- Added: When the Package Manager cannot update itself, its message offers Download manually, which opens the latest release on GitHub.
- Fixed: When the Package Manager's update check could not reach GitHub, nothing was said.
- Fixed: Notifications with two buttons could cut off their text; a button that does not fit now goes to the next line.
- Fixed: Notifications in the screen corner had an empty strip under two or three lines of text.
- Changed: A script removed from the toolbar fades while a glowing line wipes it away from right to left, and its place closes smoothly.

## 2.1.1

- Fixed: In 3ds Max 2025 and newer, the Package Manager could not update itself: GitHub serves release files through a redirect that was not followed, so the download came back empty. Versions 2.0.9 and 2.1.0 on these 3ds Max versions need this release installed by hand once.

## 2.1.0

- Added: The toolbar lights up when it appears, moves or changes its look, so it is easy to find. A newly installed script's button gets rings around it, and a removed one shrinks away before its place closes.
- Fixed: On screens with display scaling above 100%, icons on buttons with text were too small.

## 2.0.9

- Fixed: Installing over the previous MaxPkg Runtime removes it only after the Package Manager has started; if it does not start, the previous Runtime keeps working.
- Fixed: When several 3ds Max versions share a scripts or macros folder, installing no longer removes the previous Runtime that an older 3ds Max still uses.
- Fixed: The Package Manager's startup script and action do nothing on 3ds Max older than 2022, and each 3ds Max version uses its own copy.
- Changed: The Package Manager updates itself only from the releases of its own repository.

## 2.0.8

- Added: The Package Manager updates itself from its GitHub releases: the download is checked against the published SHA-256, and if the new version does not start, the previous one comes back. Versions older than this one still need a manual install once.
- Fixed: Pictures in a package description are shown as pictures instead of links, as on maxpkg.dev: pictures on consecutive lines form a gallery, others sit in the text, and a click enlarges them. Pictures load only from the maxpkg.dev content server.
- Improved: The large icons of loading and empty pages are animated like the other Manager icons, and Everything is up to date shows a check mark.

## 2.0.7

- Added: Package details have a Videos tab with the package's videos from maxpkg.dev; a click opens the video in the browser.

## 2.0.6

- Added: A downloaded package is checked against the SHA-256 published by maxpkg.dev before it is installed; a file that does not match is deleted and not installed.
- Added: After installing several packages at once, such as a collection, a summary names the packages that were not installed.

## 2.0.5

- Fixed: On some computers (seen in 3ds Max 2025) the screenshot viewer did not open.

## 2.0.4

- Added: View Logs at the bottom left opens the log of any day, with info, success, warning and error records in their colours, a level filter, search and live updates.
- Added: In the logs, a click, Shift, Ctrl or a drag selects whole records; the right-click menu copies, exports or jumps to the latest record (Ctrl+C, Ctrl+E, Ctrl+F).
- Added: Clear Logs deletes the log files of every day after a confirmation.
- Added: Installs, updates and removals are written to the log as successes or errors.
- Fixed: A collection installer from maxpkg.dev installs every package: packages asked for while another one installs wait their turn instead of failing.

## 2.0.3

- Added: The Updates tab count turns red while updates are pending.
- Added: Settings > Storage shows how much the image cache takes and lets you open its folder or clear it.
- Fixed: The Changelog tab in package details counts versions, not single changes.
- Fixed: A screenshot that cannot be loaded shows a message instead of an endless spinner and is tried again when the viewer opens.
- Changed: The screenshot viewer closes on a click beside the screenshot, and its close button matches the Manager window's.
- Fixed: In 3ds Max 2027, scripts started from MaxPkg can find their own files.
- Fixed: Script errors are shown in the MAXScript Listener and the log, not only in a notification.
- Fixed: Scripts made for other 3ds Max versions are not started or installed, including an MZP downloaded by hand; package details show the supported versions.
- Fixed: The » button of the toolbar opens a menu of the buttons that do not fit.
- Fixed: Compact spacing no longer shrinks toolbar icons; only Icon size sets their size.
- Fixed: Update notifications name the package instead of showing the download address.
- Fixed: Notifications no longer show links, file paths or error internals; the full text stays in the log.

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
