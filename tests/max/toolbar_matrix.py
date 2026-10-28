"""Render the docked toolbar for every icon size / density / second line and at 2x pixel ratio.

Writes docs/screenshots/qt-toolbar-matrix.png and restores the toolbar settings afterwards. The 2x column
is a layout check only: true 200% rendering needs a 200% monitor (icons follow the screen's pixel ratio).
"""

import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
driver = runpy.run_path(str(ROOT / "tests" / "max" / "ui_driver.py"))


def main():
    from maxpkg_runtime.qt_compat import QtCore, QtGui, Qt
    owner = sys.modules["_maxpkg_runtime_session"].owner
    settings = owner.runtime.settings
    keys = ("toolbar_dock_position", "toolbar_icon_size", "toolbar_density", "toolbar_button_size",
            "toolbar_subtitle_mode")
    saved = {key: getattr(settings, key) for key in keys}
    rows = []
    try:
        for density in ("regular", "compact"):
            for icon_size in ("small", "medium", "large"):
                for subtitle in ("version", "none"):
                    settings.toolbar_dock_position = "top"
                    settings.toolbar_density, settings.toolbar_icon_size = density, icon_size
                    settings.toolbar_button_size, settings.toolbar_subtitle_mode = "medium", subtitle
                    owner.runtime.save_settings("toolbar")
                    driver["pump"](0.25)
                    bar = owner.toolbar.toolbar
                    width = min(bar.width(), 620)
                    one = bar.grab(QtCore.QRect(0, 0, width, bar.height()))
                    two = QtGui.QPixmap(width * 2, bar.height() * 2)
                    two.setDevicePixelRatio(2.0)
                    two.fill(Qt.transparent)
                    painter = QtGui.QPainter(two)
                    bar.render(painter, QtCore.QPoint(0, 0), QtGui.QRegion(0, 0, width, bar.height()))
                    painter.end()
                    rows.append(("{} / {} / {}".format(density, icon_size, subtitle), one, two))
    finally:
        for key, value in saved.items():
            setattr(settings, key, value)
        owner.runtime.save_settings("toolbar")
    label_width = 170
    total_width = label_width + max(row[1].width() + row[2].width() // 2 * 2 for row in rows) + 40
    total_height = sum(max(row[1].height(), row[2].height() // 2 * 2) + 12 for row in rows) + 12
    sheet = QtGui.QPixmap(total_width, total_height)
    sheet.fill(QtGui.QColor("#202020"))
    painter = QtGui.QPainter(sheet)
    painter.setPen(QtGui.QColor("#d0d0d0"))
    y = 12
    for text, one, two in rows:
        painter.drawText(10, y + 16, text)
        painter.drawPixmap(label_width, y, one)
        two_logical = QtGui.QPixmap(two)
        two_logical.setDevicePixelRatio(1.0)
        painter.drawPixmap(label_width + one.width() + 20, y, two_logical)
        y += max(one.height(), two.height()) + 12
    painter.end()
    path = ROOT / "docs" / "screenshots" / "qt-toolbar-matrix.png"
    sheet.save(str(path))
    driver["log"]("toolbar matrix " + str(path))


main()
