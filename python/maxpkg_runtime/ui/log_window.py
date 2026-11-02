"""Logs window: the Package Manager's daily log files, a day picker, level filters and a search, with each level
in its colour (info, success, warning, error). It has the Settings window's own chrome and stays above the Manager."""

import os

from ..domain.logs import FILTERS, LEVEL_LABELS, day_label, filter_records, log_days, read_records, summary_text
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, disable_max_accelerators
from .frame import (EDGE, WindowChrome, apply_native_frame, bounded_position, glass_border, native_event,
                    paint_window_shape, prepare_window)
from .settings_panel import Segments
from .widgets import Button, Dropdown, IconLabel, SearchBox, Switch, hbox, label, vbox

AREA_WIDTH = 12
SHOWN_LIMIT = 4000  # the newest records of a filtered day; the rest stay in the file
LIVE_INTERVAL = 2000
LINE_HEIGHT = 135  # percent
PROPORTIONAL_HEIGHT = 1  # QTextBlockFormat.ProportionalHeight (an int in both Qt bindings)
FONT_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")
# Each level keeps its own hue in every theme (grey, blue, green, amber, red); theme accents vary too much
# (some themes have a teal accent next to a teal success). level: (pill dark, text dark, pill light, text light)
LEVEL_COLORS = {"debug": ("#3a3f47", "#a7adb7", "#e3e6ea", "#4d5560"),
                "info": ("#1d3a5f", "#8ec5ff", "#dbeafe", "#1d4ed8"),
                "success": ("#16432b", "#6ee7a0", "#dcfce7", "#15803d"),
                "warning": ("#4a3a12", "#fbbf24", "#fef3c7", "#b45309"),
                "error": ("#4c1d1d", "#f87171", "#fee2e2", "#b91c1c")}


def level_colors(level, light):
    """(pill, text) QColors of a level for a dark or light theme."""
    colors = LEVEL_COLORS[level]
    return (QtGui.QColor(colors[2]), QtGui.QColor(colors[3])) if light else (QtGui.QColor(colors[0]),
                                                                           QtGui.QColor(colors[1]))


def _monospace_font(size):
    font = QtGui.QFont()
    font.setStyleHint(QtGui.QFont.TypeWriter)
    try:
        families = set(QtGui.QFontDatabase.families())  # Qt 6: static
    except TypeError:
        families = set(QtGui.QFontDatabase().families())  # Qt 5 (3ds Max 2022-2024): an instance method
    for family in FONT_FAMILIES:
        if family in families:
            font.setFamily(family)
            break
    font.setPointSizeF(size)
    return font


def _text_x(line, position):
    """QTextLine.cursorToX: a number in Qt, an (x, position) pair in some Qt for Python versions."""
    x = line.cursorToX(position)
    return x[0] if isinstance(x, tuple) else x


class LogView(QtWidgets.QTextEdit):
    """Read-only log text. Level badges are pills (fully rounded ends), which a character background cannot draw,
    so the view paints them under the text: `pills` maps a line (block number) to (start, length, colour)."""

    def __init__(self, parent=None):
        QtWidgets.QTextEdit.__init__(self, parent)
        self.pills = {}

    def paintEvent(self, event):
        if self.pills:
            document = self.document()
            layout = document.documentLayout()
            offset = QtCore.QPointF(-self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
            area = event.rect()
            first = self.cursorForPosition(QtCore.QPoint(0, area.top())).blockNumber()
            last = self.cursorForPosition(QtCore.QPoint(0, area.bottom())).blockNumber()
            painter = QtGui.QPainter(self.viewport())
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            for number in range(first, last + 1):
                pill = self.pills.get(number)
                if pill is None:
                    continue
                start, length, color = pill
                block = document.findBlockByNumber(number)
                line = block.layout().lineForTextPosition(start)
                if not line.isValid():
                    continue
                origin = layout.blockBoundingRect(block).topLeft() + offset
                left = _text_x(line, start)
                right = _text_x(line, start + length)
                height = line.ascent() + line.descent() + 2
                rect = QtCore.QRectF(origin.x() + left, origin.y() + line.y() - 1, right - left, height)
                painter.setBrush(color)
                painter.drawRoundedRect(rect, height / 2.0, height / 2.0)
            painter.end()
        QtWidgets.QTextEdit.paintEvent(self, event)


class LogWindow(QtWidgets.QWidget):
    """`open_window()` shows it with today's log; the instance is kept, so its place and choices stay while
    3ds Max runs."""

    def __init__(self, window, parent):
        QtWidgets.QWidget.__init__(self, parent)
        self.setObjectName("SettingsWindow")
        self.setWindowTitle("MaxPkg Logs")
        prepare_window(self)
        self.manager_window = window
        self.runtime = window.runtime
        self.themes = window.themes
        self.folder = self.runtime.paths.logs
        self.days = []
        self.records = []
        self._stamp = None  # (size, mtime) of the shown file, for Live
        self._placed = False
        self.chrome = WindowChrome(self, "Logs", self.themes, collapsible=False, flags=Qt.Tool)
        self.setMinimumSize(640, 380)
        body = QtWidgets.QFrame(self)
        body.setObjectName("SettingsBody")

        header = QtWidgets.QFrame()
        header.setObjectName("ModalHeader")
        header.setFixedHeight(54)
        title_icon = IconLabel("logs", self.themes, "iconAccent", 18)
        title_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        title = label("Logs", "ModalTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        close = self.chrome.window_buttons("Close Logs")[0]
        header.setLayout(hbox(title_icon, title, None, close, spacing=10, margins=(16, 0, 10, 0)))
        self.chrome.attach_title_bar(header)

        self.day = Dropdown(self.themes)
        self.day.setToolTip("Each day of 3ds Max work has its own log file")
        self.day.setMinimumWidth(150)
        self.level = Segments(FILTERS)
        self.level.setToolTip("Show every record, or only warnings and errors")
        self.level.set_value("all")
        self.level.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.search = SearchBox(self.themes, "Filter messages")
        self.summary = label("", "LogSummary")
        filters = hbox(self.day, self.level, self.search, self.summary, spacing=10, margins=(16, 12, 16, 10))
        filters.setStretch(2, 1)

        self.view = LogView()
        self.view.setObjectName("LogView")
        self.view.setReadOnly(True)
        self.view.setUndoRedoEnabled(False)
        self.view.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.view.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.TextSelectableByKeyboard)
        self.view.document().setDocumentMargin(10)
        self.log_font = _monospace_font(9)  # set on every run: the style sheet gives the view Segoe UI
        frame = QtWidgets.QFrame()
        frame.setObjectName("LogFrame")
        frame.setLayout(vbox(self.view, margins=(1, 1, 1, 1)))

        self.refresh_button = Button("Refresh", "refresh-cw", themes=self.themes, tooltip="Read the log again (F5)")
        self.live = Switch("Live", self.themes)
        self.live.setToolTip("Show new records as they are written")
        self.copy_button = Button("Copy", "copy", themes=self.themes, tooltip="Copy the shown records")
        self.folder_button = Button("Open Folder", "folder-open", themes=self.themes,
                                    tooltip="Open the folder with the log files")
        actions = hbox(self.refresh_button, self.live, None, self.copy_button, self.folder_button,
                       spacing=10, margins=(16, 10, 16, 14))

        content = vbox(header, filters, vbox(frame, margins=(16, 0, 16, 0)), actions, spacing=0)
        content.setStretch(2, 1)
        body.setLayout(content)
        self.setLayout(vbox(body, margins=(EDGE, EDGE, EDGE, EDGE)))

        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setInterval(LIVE_INTERVAL)
        self._live_timer.timeout.connect(self._poll)
        self._copied_timer = QtCore.QTimer(self)
        self._copied_timer.setSingleShot(True)
        self._copied_timer.setInterval(2000)
        self._copied_timer.timeout.connect(lambda: self.copy_button.set_label("Copy"))
        self.day.currentIndexChanged.connect(lambda _index: self._load(to_end=True))
        self.level.changed.connect(lambda _value: self._render(to_end=True))
        self.search.textChanged.connect(lambda _text: self._render(to_end=True))
        self.refresh_button.clicked.connect(self.reload)
        self.live.toggled.connect(self._set_live)
        self.copy_button.clicked.connect(self._copy)
        self.folder_button.clicked.connect(self.runtime.open_logs)
        self.themes.manager_changed.connect(self._on_theme)
        disable_max_accelerators(self)  # Esc, F5 and Ctrl+F reach the window, not 3ds Max
        self.hide()

    # --- shell ----------------------------------------------------------------------
    def open_window(self):
        self._list_days(select_newest=not self.isVisible())
        self._load(to_end=True)
        if not self._placed:
            self._place()
            self._placed = True
        self.show()
        self.raise_()
        self.activateWindow()
        if self.live.isChecked():
            self._live_timer.start()

    def _place(self):
        """First time centred over the Manager, 85% of its size (at least 760 x 480)."""
        manager = self.manager_window.frameGeometry()
        self.resize(max(760, min(1100, int(manager.width() * 0.85))), max(480, int(manager.height() * 0.85)))
        point = manager.center() - QtCore.QPoint(self.width() // 2, self.height() // 2)
        self.move(bounded_position(point, self.size()))

    def close_window(self):
        self._live_timer.stop()
        self.hide()

    def dispose(self):
        try:
            self.themes.manager_changed.disconnect(self._on_theme)
        except (RuntimeError, TypeError):
            pass
        self._live_timer.stop()

    def closeEvent(self, event):
        event.ignore()  # Alt+F4 or the close button: hide, the window is reused
        self.close_window()

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        paint_window_shape(self, painter, theme.color("surfacePrimary"), glass_border(theme.color("surfacePrimary")))
        painter.end()

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QWidget.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        apply_native_frame(self, glass_border(self.themes.color("surfacePrimary")))

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QWidget.mouseReleaseEvent(self, event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self.close_window()
            return
        if event.key() == Qt.Key_F5:
            self.reload()
            return
        if event.key() == Qt.Key_F and event.modifiers() & Qt.ControlModifier:
            self.search.setFocus()
            self.search.selectAll()
            return
        QtWidgets.QWidget.keyPressEvent(self, event)

    # --- data -----------------------------------------------------------------------
    def reload(self):
        self._list_days(select_newest=False)
        self._load(to_end=False)

    def _list_days(self, select_newest):
        """Fill the day picker; keeps the chosen day unless `select_newest` (a fresh open shows today)."""
        self.days = log_days(self.folder)
        current = None if select_newest else self.day.value()
        choices = [(day.file_path, day_label(day.date)) for day in self.days] or [("", "No logs yet")]
        self.day.blockSignals(True)
        self.day.set_choices(choices, current if current else choices[0][0])
        self.day.blockSignals(False)
        self.day.setEnabled(bool(self.days))

    def _file_stamp(self, file_path):
        try:
            status = os.stat(file_path)
        except OSError:
            return None
        return status.st_size, status.st_mtime

    def _load(self, to_end):
        file_path = self.day.value() or ""
        self.records = read_records(file_path) if file_path else []
        self._stamp = self._file_stamp(file_path) if file_path else None
        self._render(to_end)

    def _poll(self):
        """Live: a new day file or new lines in the shown one are read again; the view follows the end only when
        it was already there."""
        if not self.isVisible():
            return
        if [day.file_path for day in log_days(self.folder)] != [day.file_path for day in self.days]:
            newest = self.days and self.day.value() == self.days[0].file_path
            self._list_days(select_newest=bool(newest))
            self._load(to_end=False)
        elif self.day.value() and self._file_stamp(self.day.value()) != self._stamp:
            self._load(to_end=False)

    def _set_live(self, checked):
        if checked and self.isVisible():
            self._poll()
            self._live_timer.start()
        else:
            self._live_timer.stop()

    def _shown(self):
        return filter_records(self.records, self.level.current, self.search.text())

    def _copy(self):
        text = "\n".join(record.text() for record in self._shown()[-SHOWN_LIMIT:])
        QtWidgets.QApplication.clipboard().setText(text)
        self.copy_button.set_label("Copied")
        self._copied_timer.start()

    def _on_theme(self):
        self.update()
        if self.isVisible():
            self._render(to_end=False)

    # --- view -----------------------------------------------------------------------
    def _render(self, to_end):
        vertical = self.view.verticalScrollBar()
        at_end = to_end or vertical.value() >= vertical.maximum() - 4
        position = vertical.value()
        shown = self._shown()
        self.summary.setText(summary_text(shown) if self.records else "")
        theme = self.themes.manager
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        self.view.pills = {}
        cursor = QtGui.QTextCursor(self.view.document())
        cursor.beginEditBlock()
        block = QtGui.QTextBlockFormat()
        block.setLineHeight(LINE_HEIGHT, PROPORTIONAL_HEIGHT)
        cursor.setBlockFormat(block)
        writer = _Writer(cursor, block, theme, self.log_font, self.view.pills)
        if not shown:
            if not self.days:
                text = "Nothing has been logged yet."
            elif not self.records:
                text = "This day's log is empty."
            else:
                text = "No records match the filter."
            writer.run(text, "textMuted")
        hidden = len(shown) - SHOWN_LIMIT
        if hidden > 0:
            writer.run("{} older records are not shown. Open Folder has the whole file.".format(hidden), "textMuted")
            writer.line()
            shown = shown[-SHOWN_LIMIT:]
        indent = " " * (8 + 2 + 9 + 2 + AREA_WIDTH + 2)
        for record in shown:
            if record.session_start:
                if not writer.empty:
                    writer.line()
                writer.run("Session started {}  ·  {}".format(record.time, record.message), "accent", bold=True)
                writer.line()
                continue
            pill, badge = level_colors(record.level, theme.is_light)
            message = {"info": "textPrimary", "debug": "textMuted"}.get(record.level, badge)
            writer.run(record.time, "textMuted")
            writer.run("  ")
            writer.run(" {:^7} ".format(LEVEL_LABELS[record.level]), badge, bold=True, pill=pill)
            writer.run("  ")
            area = record.area if len(record.area) <= AREA_WIDTH else record.area[:AREA_WIDTH - 1] + "…"
            writer.run(area.ljust(AREA_WIDTH), "changed")
            writer.run("  ")
            writer.run(record.message, message)
            writer.line()
            for extra in record.extra:
                writer.run(indent + extra, message if record.level in ("warning", "error") else "textMuted")
                writer.line()
        cursor.endEditBlock()
        self.view.setUpdatesEnabled(True)
        vertical.setValue(vertical.maximum() if at_end else min(position, vertical.maximum()))


class _Writer(object):
    """Appends coloured runs and lines to the log document."""

    def __init__(self, cursor, block, theme, font, pills):
        self.cursor = cursor
        self.block = block
        self.theme = theme
        self.font = font
        self.pills = pills
        self.empty = True

    def run(self, text, color="textPrimary", bold=False, pill=None):
        """`color`: a theme token or a QColor. `pill`: a colour the view paints as a rounded pill behind this run
        (one per line)."""
        character = QtGui.QTextCharFormat()
        character.setFont(self.font)
        character.setForeground(self.theme.color(color) if isinstance(color, str) else color)
        if bold:
            character.setFontWeight(QtGui.QFont.Bold)
        if pill is not None:
            self.pills[self.cursor.blockNumber()] = (self.cursor.positionInBlock(), len(text), pill)
        self.cursor.insertText(text, character)
        self.empty = False

    def line(self):
        self.cursor.insertBlock(self.block)
