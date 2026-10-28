"""Executed by StartMaxPkg.ms. Owns the stable session anchor and restarts the Runtime cleanly.

The anchor module `_maxpkg_runtime_session` lives outside the reloadable package. A new launch
stops the previous owner first (keeping it if cleanup fails), evicts only this package's modules,
imports fresh code from this folder and starts one new Controller.
"""


def launch(root, open_manager=True, **start_options):
    import importlib
    import importlib.util
    import sys
    import types

    package_name = "maxpkg_runtime"
    state = sys.modules.setdefault("_maxpkg_runtime_session", types.ModuleType("_maxpkg_runtime_session"))
    if getattr(state, "transitioning", False):
        return getattr(state, "owner", None)
    state.transitioning = True
    candidate = None
    try:
        previous = getattr(state, "owner", None)
        if previous is not None:
            previous.stop()  # raises if cleanup is incomplete; the owner stays in the anchor
            state.owner = None
        for name in list(sys.modules):
            if name == package_name or name.startswith(package_name + "."):
                del sys.modules[name]
        importlib.invalidate_caches()
        folder = root / "python" / package_name
        spec = importlib.util.spec_from_file_location(package_name, str(folder / "__init__.py"),
                                                      submodule_search_locations=[str(folder)])
        if spec is None or spec.loader is None:
            raise RuntimeError("Cannot load the maxpkg_runtime package from " + str(folder))
        package = importlib.util.module_from_spec(spec)
        sys.modules[package_name] = package
        spec.loader.exec_module(package)
        controller = importlib.import_module(package_name + ".controller")
        candidate = controller.Controller(root)
        state.owner = candidate
        candidate.start(open_manager=open_manager, **start_options)
        return candidate
    except Exception:
        if candidate is not None:
            candidate.stop()
            state.owner = None
        raise
    finally:
        state.transitioning = False


if __name__ == "__main__":  # python.ExecuteFile runs the file as __main__
    from pathlib import Path

    launch(Path(__file__).resolve().parent.parent)
