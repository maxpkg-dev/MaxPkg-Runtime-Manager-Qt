"""The only boundary to 3ds Max (pymxs). Call these functions on the main thread only.

Outside Max (unit tests) every function degrades to a harmless fallback.
"""

import os
import sys
import webbrowser

try:
    from pymxs import runtime as rt
except ImportError:  # pragma: no cover - outside 3ds Max
    rt = None

from . import log


def in_max():
    return rt is not None


def max_year():
    """Product year, e.g. 2027 (maxVersion()[8] exists since 3ds Max 2017)."""
    if rt is None:
        return 2027
    try:
        return int(rt.maxVersion()[7])
    except (IndexError, TypeError, ValueError):
        return 2000 + int(rt.maxVersion()[0]) // 1000 - 2


def get_dir(name):
    """getDir #name as a path without a trailing separator, or '' outside Max."""
    if rt is None:
        return ""
    try:
        return str(rt.getDir(rt.Name(name))).rstrip("\\/")
    except Exception:  # noqa: BLE001 - unknown directory names are not fatal
        return ""


_MISSING = object()


class _OwnFile(object):
    """Lets 3ds Max give each script it runs its own __file__.

    python.ExecuteFile runs the file in __main__. 3ds Max 2027 then sets __file__ only when __main__ has none
    (3ds Max 2022 always sets it).
    Started from Python (our toolbar, the Manager), __main__ still holds the caller's __file__, so a package that
    finds its folder through __file__ looks next to the caller. The same happens to python.ExecuteFile inside a
    MaxScript that we fileIn. __main__.__file__ is removed for the call and restored afterwards."""

    def __enter__(self):
        self._main = sys.modules.get("__main__")
        self._saved = getattr(self._main, "__dict__", {}).pop("__file__", _MISSING)
        return self

    def __exit__(self, *_exception):
        if self._main is None:
            return False
        if self._saved is _MISSING:
            self._main.__dict__.pop("__file__", None)
        else:
            self._main.__dict__["__file__"] = self._saved
        return False


def error_text(error):
    """The MaxScript or Python error without pymxs' "MAXScript exception raised." first line."""
    text = str(error).strip()
    first, _, rest = text.partition("\n")
    if first.strip().rstrip(".").lower() == "maxscript exception raised" and rest.strip():
        text = rest.strip()
    return text or error.__class__.__name__


def _to_listener(title, error):
    """pymxs turns a MaxScript error into a Python exception, and the Listener never sees it: print it there."""
    print("-- MaxPkg: " + title + " stopped with an error:\n" + error_text(error))


def run_package(package):
    """Run the package entry exactly like core/launcher.ms. Returns (ok, message): the message is for the user (no
    paths); the details go to the Listener and the log."""
    entry_path = os.path.join(package.install_path, package.entry)
    if not os.path.isfile(entry_path):
        log.error("launcher", package.guid + ": entry file not found: " + entry_path)
        return False, "Its start file is missing. Install it again from Discover."
    if rt is None:
        return False, "3ds Max is not available."
    try:
        with _OwnFile():
            if package.runtime.lower() == "python" or entry_path.lower().endswith(".py"):
                rt.python.ExecuteFile(entry_path)
            else:
                rt.fileIn(entry_path)
    except Exception as error:  # noqa: BLE001 - a failing package must not break the Runtime
        log.error("launcher", package.guid + ": " + error_text(error))
        _to_listener(package.display_name, error)
        return False, "The script stopped with an error. The MaxScript Listener shows the details."
    log.info("launcher", "Ran " + package.guid)
    return True, ""


def file_in(path):
    """fileIn a MaxScript or MZP file. Raises on MaxScript errors, after printing them to the Listener."""
    if rt is None:
        raise RuntimeError("3ds Max is not available")
    try:
        with _OwnFile():
            rt.fileIn(path)
    except Exception as error:
        _to_listener(os.path.basename(path), error)
        raise


def execute(source):
    if rt is None:
        raise RuntimeError("3ds Max is not available")
    return rt.execute(source)


# MaxScript `MaxPkg` global with the old Runtime's public API. Package installers made by MaxPkg Packager install
# silently only when `MaxPkg` exists, then report `MaxPkg.packageInstalled guid`; the maxpkg.dev one-click and
# collection installers call `isStarted`, `start`, `install`, `installMany` and `installLayout`. Each call hands its
# command to the Python Controller.
_FACADE_SOURCE = r'''(
    struct MaxPkgPackageManagerResultData (success = false, message = "", errorCode = "")
    struct MaxPkgPackageManagerFacade (
        isPackageManager = true,
        version = "@VERSION@",
        root = @"@ROOT@",
        bridgeCommand = "",
        bridgeArgument = "",
        bridgeResult = undefined,
        fn call commandName argumentText:"" = (
            bridgeCommand = commandName
            bridgeArgument = argumentText as string
            bridgeResult = undefined
            python.Execute "getattr(getattr(__import__('sys').modules.get('_maxpkg_runtime_session'), 'owner', None), 'maxscript_call', lambda: None)()"
            return bridgeResult
        ),
        fn isStarted = (
            return (call "isStarted") == true
        ),
        fn start = (
            -- Not python.ExecuteFile: run from inside Python (a package installed by the Manager) it keeps
            -- the caller's __file__, so the entry is addressed by its absolute path.
            if (not (isStarted())) do (
                local entryPath = substituteString (substituteString (root + "python/entry.py") "\\" "/") "'" "\\'"
                python.Execute ("import runpy; runpy.run_path('" + entryPath + "', run_name='maxpkg_entry')['run']('start')")
            )
            return isStarted()
        ),
        fn shutdown = (
            call "shutdown"
            return true
        ),
        fn openManager = (
            if (not (start())) do return false
            return (call "openManager") == true
        ),
        fn showOnboarding = (
            if (not (start())) do return false
            return (call "welcome") == true
        ),
        fn scan = (
            return (call "scan") == true
        ),
        fn packageInstalled packageGuid = (
            return (call "packageInstalled" argumentText:packageGuid) == true
        ),
        fn packageRemoved packageGuid = (
            return (call "packageRemoved" argumentText:packageGuid) == true
        ),
        fn install packageReference = (
            if (not (start())) do return MaxPkgPackageManagerResultData message:"MaxPkg Package Manager could not be started."
            local reply = call "install" argumentText:packageReference
            if (reply == true) do return MaxPkgPackageManagerResultData success:true message:"Installing in MaxPkg Package Manager."
            return MaxPkgPackageManagerResultData message:(if (reply == undefined) then "The package could not be installed." else reply as string)
        ),
        -- Several packages in one call: GUIDs separated by ";" (or an array). The Manager installs them one after
        -- another and reports each one; the caller does not wait.
        fn installMany packageReferences = (
            if (not (start())) do return MaxPkgPackageManagerResultData message:"MaxPkg Package Manager could not be started."
            local referencesText = ""
            if (classOf packageReferences == Array) then (
                for reference in packageReferences do referencesText += (reference as string) + ";"
            ) else (
                referencesText = packageReferences as string
            )
            local reply = call "installMany" argumentText:referencesText
            if (reply == true) do return MaxPkgPackageManagerResultData success:true message:"Installing in MaxPkg Package Manager."
            return MaxPkgPackageManagerResultData message:(if (reply == undefined) then "The packages could not be installed." else reply as string)
        ),
        -- A favorite collection arranged as a toolbar on maxpkg.dev: package GUIDs and the word "divider", separated
        -- by ";", in the owner's order. Installs what is missing like installMany, then gives the toolbar the same
        -- order and dividers; the caller does not wait.
        fn installLayout layoutText = (
            if (not (start())) do return MaxPkgPackageManagerResultData message:"MaxPkg Package Manager could not be started."
            local entriesText = ""
            if (classOf layoutText == Array) then (
                for layoutEntry in layoutText do entriesText += (layoutEntry as string) + ";"
            ) else (
                entriesText = layoutText as string
            )
            local reply = call "installLayout" argumentText:entriesText
            if (reply == true) do return MaxPkgPackageManagerResultData success:true message:"Installing in MaxPkg Package Manager."
            return MaxPkgPackageManagerResultData message:(if (reply == undefined) then "The collection could not be installed." else reply as string)
        ),
        fn uninstall packageReference showNotification:true = (
            if (not (start())) do return false
            return (call "uninstall" argumentText:packageReference) == true
        )
    )
    global MaxPkg
    -- MaxPkg.start() launches a new Controller while that same instance waits for the reply: keep it unless
    -- the installed version changed (then nothing of the old version is running any more).
    if (MaxPkg != undefined and (isProperty MaxPkg #isPackageManager) and MaxPkg.version == "@VERSION@") then (
        MaxPkg.root = @"@ROOT@"
        true
    ) else if (MaxPkg == undefined or (isProperty MaxPkg #isPackageManager)) then (
        MaxPkg = MaxPkgPackageManagerFacade()
        true
    ) else (
        false
    )
)'''


def define_facade(root, version):
    """Create the `MaxPkg` global. False when the old MaxScript Runtime still owns it."""
    if rt is None:
        return False
    folder = str(root).rstrip("\\/") + "\\"
    source = _FACADE_SOURCE.replace("@ROOT@", folder.replace('"', "")).replace("@VERSION@", version.replace('"', ""))
    try:
        return rt.execute(source) is True
    except Exception as error:  # noqa: BLE001 - packages then show their own installer
        log.error("facade", "MaxPkg global could not be created: " + str(error))
        return False


def facade_request():
    """(command, argument) of the MaxPkg call being handled."""
    facade = rt.MaxPkg
    return str(facade.bridgeCommand), str(facade.bridgeArgument)


def facade_reply(value):
    rt.MaxPkg.bridgeResult = value


def open_folder(path):
    if path and os.path.isdir(path):
        os.startfile(path)  # noqa: S606 - explorer on a known package folder
        return True
    return False


def open_url(url):
    if url and url.lower().startswith(("http://", "https://")):
        webbrowser.open(url)
        return True
    return False
