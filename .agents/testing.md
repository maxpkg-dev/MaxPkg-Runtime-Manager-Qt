# Testing

There is no system Python on the development machine: all Python runs in 3ds Max's embedded interpreter.
Use Max Ultra MCP (`max_list_instances` → `max_select_instance` → `max_run_script`) or the Listener.

| What | Command (MaxScript) | Result |
|---|---|---|
| Compile + unit tests | `python.ExecuteFile @"<repo>\tests\run_unit.py"` | `logs/unit.txt` |
| Start / restart Runtime | `python.ExecuteFile @"<repo>\tests\max\launch.py"` | `logs/launch.txt` |
| Lifecycle stress (40 restarts + `gc()`) | `python.ExecuteFile @"<repo>\tests\max\stress.py"` | `logs/stress.txt` |
| Screenshots / driving | see `tests/max/ui_driver.py` | `docs/screenshots/*.png`, `logs/driver.txt` |

Driver example (python.execute inside MaxScript):

```python
import runpy
d = runpy.run_path(r"<repo>\tests\max\ui_driver.py")
d["call"]('w.show_tab("discover")')     # o = Controller, w = ManagerWindow
d["pump"](3.0)                           # let network results and layouts settle
d["grab_window"]("qt-discover-1000", 1000, 700)
d["grab_settings"]("qt-settings-toolbar", "toolbar")
d["grab_toolbar"]("qt-toolbar-top")
```

Rules

- Do not touch the user's scene; the Runtime never needs one.
- Do not install/uninstall real packages without the owner's consent (they change the Max profile).
- Toolbar position/theme changed by a test must be restored (stress.py does).
- Record what was not covered: PySide2 (Max 2022–2024), high DPI, multi-monitor, install/uninstall.
- `QWidget.grab()` works while Max is behind other windows; screen capture does not.
