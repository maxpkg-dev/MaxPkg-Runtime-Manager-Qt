"""What one Check Updates tells the user: the package check and the Package Manager's own check in one message.

Check Updates (the Manager's header button and the toolbar menu) asks maxpkg.dev about the packages and GitHub about
the Package Manager at the same time. When both have answered, `summarize` turns the two results into one notice:
the most important news is its first line, the other result follows, and a failed check never hides the other one.
Check Manager Updates (the toolbar menu) asks only about the Package Manager: its packages result is PACKAGES_SKIPPED.
Pure Python: services/runtime.py turns the action names into toast buttons.
"""

# PackagesResult.status
PACKAGES_CHECKED = "checked"   # the service answered; `pending` lists the packages with a newer version
PACKAGES_FAILED = "failed"     # the service could not be asked; the previous result is kept
PACKAGES_NONE = "none"         # no installed packages: nothing to ask
PACKAGES_SKIPPED = "skipped"   # not asked: Check Manager Updates looks at the Package Manager alone

# ManagerResult.status
MANAGER_CURRENT = "current"    # `version` (the running one) is the newest release
MANAGER_INSTALL = "install"    # `version` is being installed now; the Package Manager restarts on it
MANAGER_WAIT = "wait"          # `version` is installed when the running package operation ends
MANAGER_SOURCE = "source"      # `version` is newer, but this copy runs from a source folder (git updates it)
MANAGER_FAILED = "failed"      # the release list could not be read
MANAGER_SKIPPED = "skipped"    # a Package Manager update already runs: nothing to say about it

# Notice.actions
UPDATE = "update"              # update the one package with a newer version
UPDATE_ALL = "update_all"      # update every package with a newer version
RETRY = "retry"                # run Check Updates again


class PackagesResult:
    """The package check. `pending`: (name, installed version, newer version) of each package with an update."""

    def __init__(self, status, pending=()):
        self.status = status
        self.pending = list(pending) if status == PACKAGES_CHECKED else []


class ManagerResult:
    """The Package Manager's own check. `version`: the running version when current, else the newer one."""

    def __init__(self, status, version=""):
        self.status = status
        self.version = version


class Notice:
    """One message: `text` (first line = title), `kind` (success/info/warning/error) and action names, main first."""

    def __init__(self, title, lines, kind, actions=()):
        self.text = "\n".join([title] + [line for line in lines if line])
        self.kind = kind
        self.actions = list(actions)

    def __repr__(self):
        return "Notice({!r}, {!r}, {!r})".format(self.text, self.kind, self.actions)


def _names(pending):
    names = ", ".join(name for name, _version, _latest in pending[:3])
    return names + (" and {} more".format(len(pending) - 3) if len(pending) > 3 else "")


def _offer(pending):
    """(title, detail, actions) of the package updates: the same words as the packages-only check."""
    if len(pending) == 1:
        name, version, latest = pending[0]
        return "An update is available.", "{} {} → {}".format(name, version, latest), [UPDATE]
    return "{} updates are available.".format(len(pending)), _names(pending), [UPDATE_ALL]


def _packages_line(packages):
    """The package result as a line under another title ('' when there is nothing to add)."""
    if packages.status == PACKAGES_FAILED:
        return "The package update check failed."
    if packages.status != PACKAGES_CHECKED:
        return ""
    pending = packages.pending
    if not pending:
        return "All packages are up to date."
    if len(pending) == 1:
        return "An update for {} is available too.".format(pending[0][0])
    return "{} package updates are available too.".format(len(pending))


def _manager_line(manager):
    """The Package Manager result as a line under a package title ('' when there is nothing to add)."""
    version = manager.version
    return {MANAGER_CURRENT: "Package Manager {} is up to date.".format(version),
            MANAGER_WAIT: "Package Manager {} will be installed when the current package operation ends.".format(
                version),
            MANAGER_SOURCE: "Package Manager {} is available: this copy runs from a source folder, update it with "
                            "git.".format(version),
            MANAGER_FAILED: "The Package Manager update check failed."}.get(manager.status, "")


def summarize(packages, manager):
    """The one notice of a Check Updates. Order of importance: a Package Manager that installs itself now (it restarts,
    and the new copy names the package updates again), package updates, other Package Manager news, failed checks,
    and last 'everything is up to date'."""
    version = manager.version
    if manager.status == MANAGER_INSTALL:
        # No Try Again or Update here: the Package Manager restarts in a moment.
        return Notice("Package Manager {} is available.".format(version),
                      ["Installing it now.", _packages_line(packages)], "info")
    if packages.pending:
        title, detail, actions = _offer(packages.pending)
        return Notice(title, [detail, _manager_line(manager)], "info",
                      actions + ([RETRY] if manager.status == MANAGER_FAILED else []))
    if manager.status in (MANAGER_WAIT, MANAGER_SOURCE):
        detail = ("It will be installed when the current package operation ends." if manager.status == MANAGER_WAIT
                  else "This copy runs from a source folder: update it with git.")
        return Notice("Package Manager {} is available.".format(version), [detail, _packages_line(packages)], "info",
                      [RETRY] if packages.status == PACKAGES_FAILED else [])
    packages_failed = packages.status == PACKAGES_FAILED
    manager_failed = manager.status == MANAGER_FAILED
    if packages_failed and manager_failed:
        return Notice("The update check failed.", ["Neither the packages nor the Package Manager could be checked.",
                                                   "The previous result is still available."], "error", [RETRY])
    if packages_failed:
        return Notice("The package update check failed.",
                      ["The previous result is still available.", _manager_line(manager)], "error", [RETRY])
    if manager_failed:
        return Notice("The Package Manager update check failed.",
                      ["The MaxPkg release list could not be read.", _packages_line(packages)], "error", [RETRY])
    if packages.status == PACKAGES_SKIPPED and manager.status == MANAGER_CURRENT:
        return Notice("Package Manager {} is up to date.".format(version), [], "success")
    if packages.status == PACKAGES_NONE:
        if manager.status == MANAGER_CURRENT:
            return Notice("Package Manager {} is up to date.".format(version), ["No installed packages to check."],
                          "success")
        return Notice("No installed packages to check.", [], "info")
    if manager.status == MANAGER_CURRENT:
        return Notice("Everything is up to date.",
                      ["All packages and Package Manager {} are the latest versions.".format(version)], "success")
    return Notice("All packages are up to date.", [], "success")


def updated_notice(version, pending):
    """After the Package Manager restarted on a new version: say so, and offer the package updates the last check
    found (Check Updates installs the Package Manager first and leaves them for the new version)."""
    if not pending:
        return Notice("Package Manager updated to {}.".format(version), [], "success")
    if len(pending) == 1:
        name, installed, latest = pending[0]
        return Notice("Package Manager updated to {}.".format(version),
                      ["An update is available for {}: {} → {}.".format(name, installed, latest)], "success", [UPDATE])
    return Notice("Package Manager updated to {}.".format(version),
                  ["{} package updates are available: {}.".format(len(pending), _names(pending))], "success",
                  [UPDATE_ALL])


__all__ = ["PackagesResult", "ManagerResult", "Notice", "summarize", "updated_notice"]
