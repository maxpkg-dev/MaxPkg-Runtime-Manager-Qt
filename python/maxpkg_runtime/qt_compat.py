"""The only module that picks the Qt binding and hides PySide2/PySide6 differences.

3ds Max 2022-2024 ship PySide2 (Qt 5), 3ds Max 2025+ ship PySide6 (Qt 6). Everything else in the
package imports Qt names from here. Short enum spellings (``Qt.AlignCenter``) work in both.
"""

import importlib

BINDING = None
QtCore = QtGui = QtWidgets = QtSvg = shiboken = None

for _name, _shiboken in (("PySide6", "shiboken6"), ("PySide2", "shiboken2")):
    try:
        importlib.import_module(_name)
    except ImportError:
        continue
    # The binding exists: from here on a failure is a real error, never a reason to mix families.
    QtCore = importlib.import_module(_name + ".QtCore")
    QtGui = importlib.import_module(_name + ".QtGui")
    QtWidgets = importlib.import_module(_name + ".QtWidgets")
    QtSvg = importlib.import_module(_name + ".QtSvg")
    shiboken = importlib.import_module(_shiboken)
    BINDING = _name
    break

if BINDING is None:
    raise ImportError("Neither PySide6 nor PySide2 is available in this Python runtime")

IS_QT6 = BINDING == "PySide6"
Qt = QtCore.Qt
Signal = QtCore.Signal
Slot = QtCore.Slot
QAction = QtGui.QAction if IS_QT6 else QtWidgets.QAction
QShortcut = QtGui.QShortcut if IS_QT6 else QtWidgets.QShortcut


def is_valid(qobject):
    """True when the C++ object behind a Python wrapper still exists."""
    return qobject is not None and shiboken.isValid(qobject)


def binding_info():
    module = importlib.import_module(BINDING)
    return "{} {} / Qt {}".format(BINDING, module.__version__, QtCore.qVersion())


def application():
    """Max's QApplication. Never create a second one inside Max."""
    return QtWidgets.QApplication.instance()


def max_main_window():
    """3ds Max main window (a QMainWindow) for parenting, or None outside Max."""
    try:
        import qtmax
        return qtmax.GetQMaxMainWindow()
    except (ImportError, AttributeError):
        return None


def disable_max_accelerators(widget):
    """Let a text field receive keys that are also 3ds Max shortcuts while it has focus."""
    try:
        import qtmax
        qtmax.DisableMaxAcceleratorsOnFocus(widget, True)
    except (ImportError, AttributeError, TypeError):
        pass


def exec_menu(menu, global_pos):
    return menu.exec_(global_pos) if hasattr(menu, "exec_") else menu.exec(global_pos)


def event_global_pos(event):
    """QPoint of a mouse event in screen coordinates (Qt 6 renamed the accessor)."""
    if hasattr(event, "globalPosition"):
        return event.globalPosition().toPoint()
    return event.globalPos()


def event_pos(event):
    if hasattr(event, "position"):
        return event.position().toPoint()
    return event.pos()


def screen_at(point):
    app = application()
    if hasattr(app, "screenAt"):
        screen = app.screenAt(point)
        if screen is not None:
            return screen
    return app.primaryScreen()
