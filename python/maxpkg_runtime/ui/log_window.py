"""Logs window: the Package Manager's daily log files, a day picker, level filters and a search, with each level
in its colour (info, success, warning, error). Records are selected as whole rows (click, Shift, Ctrl, drag) and
copied or exported from the context menu. It has the Settings window's own chrome and stays above the Manager."""

import os

from ..domain.logs import (FILTERS, LEVEL_LABELS, clear_logs, day_label, filter_records, log_days, read_records,
                           summary_text)
from ..domain.storage import size_text
from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal, disable_max_accelerators, event_pos, exec_menu
from ..services import log
from .dialogs import confirm
from .frame import (EDGE, WindowChrome, apply_native_frame, bounded_position, glass_border, native_event,
                    paint_window_shape, prepare_window)
from .settings_panel import Segments
from .theme import with_alpha
from .widgets import Button, Dropdown, IconLabel, SearchBox, Switch, add_action, hbox, label, themed_menu, vbox

AREA_WIDTH = 12
MESSAGE_COLUMN = 8 + 2 + 9 + 2 + AREA_WIDTH + 2  # time, level badge and area, each followed by two spaces
SHOWN_LIMIT = 4000  # the newest records of a filtered day; the rest stay in the file
LIVE_INTERVAL = 2000
LINE_HEIGHT = 135  # percent
PROPORTIONAL_HEIGHT = 1  # QTextBlockFormat.ProportionalHeight (an int in both Qt bindings)
FONT_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")
SCROLL_KEYS = (Qt.Key_Up, Qt.Key_Down, Qt.Key_Left, Qt.Key_Right, Qt.Key_PageUp, Qt.Key_PageDown, Qt.Key_Home,
               Qt.Key_End)
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


def _record_keys(records):
    """A key per record that survives a re-read of the file: its text and which repeat of that text it is."""
    seen = {}
    keys = []
    for record in records:
        text = record.text()
        seen[text] = seen.get(text, 0) + 1
        keys.append((text, seen[text]))
    return keys


class LogView(QtWidgets.QTextEdit):
    """Read-only log text with whole-record selection.

    `rows` maps a line (block number) to the index of the record it shows; a click selects that record, Shift adds
    the range from the last click, Ctrl toggles one, a drag selects a range. `pills` maps a line to (start, length,
    colour) of its level badge: a character background cannot have rounded ends, so the view paints pills and the
    selection under the text."""

    selection_changed = Signal()
    menu_requested = Signal(QtCore.QPoint)

    def __init__(self, parent=None):
        QtWidgets.QTextEdit.__init__(self, parent)
        self.pills = {}
        self.rows = {}
        self.count = 0
        self.selected = set()
        self.anchor = None
        self.selection_color = QtGui.QColor(0, 0, 0, 0)
        self._dragging = False
        self.setReadOnly(True)  # before the flags: setReadOnly resets them to mouse text selection
        self.setUndoRedoEnabled(False)
        self.setTextInteractionFlags(Qt.NoTextInteraction)
        self.viewport().setCursor(Qt.ArrowCursor)
        self.setFocusPolicy(Qt.StrongFocus)

    # --- selection ------------------------------------------------------------------
    def row_at(self, point):
        """Index of the record under a viewport point, or -1."""
        cursor = self.cursorForPosition(point)
        block = cursor.block()
        rect = self.document().documentLayout().blockBoundingRect(block)
        top = rect.top() - self.verticalScrollBar().value()
        if not top <= point.y() < top + rect.height():
            return -1
        return self.rows.get(block.blockNumber(), -1)

    def set_selection(self, indices, anchor=None):
        self.selected = set(index for index in indices if 0 <= index < self.count)
        self.anchor = anchor if anchor is not None and 0 <= anchor < self.count else None
        self.viewport().update()
        self.selection_changed.emit()

    def select_all(self):
        self.set_selection(range(self.count), 0 if self.count else None)

    def clear_selection(self):
        self.set_selection(())

    def _click(self, index, modifiers):
        if index < 0:
            if not modifiers & (Qt.ShiftModifier | Qt.ControlModifier):
                self.clear_selection()
            return
        if modifiers & Qt.ShiftModifier and self.anchor is not None:
            low, high = sorted((self.anchor, index))
            span = set(range(low, high + 1))
            self.set_selection(self.selected | span if modifiers & Qt.ControlModifier else span, self.anchor)
        elif modifiers & Qt.ControlModifier:
            self.set_selection(self.selected ^ {index}, index)
        else:
            self.set_selection({index}, index)

    def mousePressEvent(self, event):
        self.setFocus()
        index = self.row_at(event_pos(event))
        if event.button() == Qt.LeftButton:
            self._click(index, event.modifiers())
            self._dragging = index >= 0 and not event.modifiers() & (Qt.ShiftModifier | Qt.ControlModifier)
        elif event.button() == Qt.RightButton and index >= 0 and index not in self.selected:
            self.set_selection({index}, index)  # the menu acts on the row under the cursor
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton and self.anchor is not None:
            point = event_pos(event)
            index = self.row_at(point)
            if index >= 0:
                low, high = sorted((self.anchor, index))
                if self.selected != set(range(low, high + 1)):
                    self.set_selection(range(low, high + 1), self.anchor)
            if point.y() < 0 or point.y() > self.viewport().height():  # keep scrolling while dragging past an edge
                bar = self.verticalScrollBar()
                bar.setValue(bar.value() + (-20 if point.y() < 0 else 20))
        event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        event.accept()

    def mouseDoubleClickEvent(self, event):
        event.accept()

    def contextMenuEvent(self, event):
        self.menu_requested.emit(event.globalPos())
        event.accept()

    def keyPressEvent(self, event):
        """Only scrolling keys are the view's; the window handles Ctrl+C, Ctrl+A, Ctrl+E, Ctrl+F and Esc."""
        if event.key() in SCROLL_KEYS:
            QtWidgets.QTextEdit.keyPressEvent(self, event)
        else:
            event.ignore()

    # --- painting -------------------------------------------------------------------
    def paintEvent(self, event):
        if self.pills or self.selected:
            document = self.document()
            layout = document.documentLayout()
            offset = QtCore.QPointF(-self.horizontalScrollBar().value(), -self.verticalScrollBar().value())
            area = event.rect()
            first = self.cursorForPosition(QtCore.QPoint(0, area.top())).blockNumber()
            last = self.cursorForPosition(QtCore.QPoint(0, area.bottom())).blockNumber()
            painter = QtGui.QPainter(self.viewport())
            painter.setRenderHint(QtGui.QPainter.Antialiasing)
            painter.setPen(Qt.NoPen)
            self._paint_selection(painter, layout, first, last, offset)
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

    def _paint_selection(self, painter, layout, first, last, offset):
        """One rounded band per run of selected lines, across the whole width."""
        if not self.selected:
            return
        document = self.document()
        band = None
        painter.setBrush(self.selection_color)
        for number in range(first, last + 2):
            selected = number <= last and self.rows.get(number, -1) in self.selected
            if selected:
                rect = layout.blockBoundingRect(document.findBlockByNumber(number)).translated(offset)
                band = rect if band is None else band.united(rect)
            elif band is not None:
                painter.drawRoundedRect(QtCore.QRectF(4, band.top() - 1, self.viewport().width() - 8, band.height() + 2), 6, 6)
                band = None


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
        self.view_records = []  # the records the view shows, in order (the selection indexes this list)
        self._stamp = None  # (size, mtime) of the shown file, for Live
        self._placed = False
        self.chrome = WindowChrome(self, "Logs", self.themes, collapsible=False, flags=Qt.Tool)
        self.setMinimumSize(760, 380)
        body = QtWidgets.QFrame(self)
        body.setObjectName("SettingsBody")

        # The filters sit in the title bar: its free part still drags the window.
        header = QtWidgets.QFrame()
        header.setObjectName("ModalHeader")
        header.setFixedHeight(56)
        title_icon = IconLabel("logs", self.themes, "iconAccent", 18)
        title_icon.setAttribute(Qt.WA_TransparentForMouseEvents)
        title = label("Logs", "ModalTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.day = Dropdown(self.themes)
        self.day.setToolTip("Each day of 3ds Max work has its own log file")
        self.day.setMinimumWidth(150)
        self.level = Segments(FILTERS)
        self.level.setToolTip("Show every record, or only warnings and errors")
        self.level.set_value("all")
        self.level.setSizePolicy(QtWidgets.QSizePolicy.Maximum, QtWidgets.QSizePolicy.Fixed)
        self.search = SearchBox(self.themes, "Filter messages")
        self.search.setMinimumWidth(160)
        close = self.chrome.window_buttons("Close Logs")[0]
        header_row = hbox(title_icon, title, 18, self.day, self.level, self.search, 10, close, spacing=10,
                          margins=(16, 0, 10, 0))
        header_row.setStretch(5, 1)
        header.setLayout(header_row)
        self.chrome.attach_title_bar(header)

        self.view = LogView()
        self.view.setObjectName("LogView")
        self.view.setLineWrapMode(QtWidgets.QTextEdit.WidgetWidth)
        self.view.setWordWrapMode(QtGui.QTextOption.WrapAtWordBoundaryOrAnywhere)  # paths have no spaces to break at
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.view.setFrameShape(QtWidgets.QFrame.NoFrame)
        self.view.document().setDocumentMargin(10)
        self.log_font = _monospace_font(9)  # set on every run: the style sheet gives the view Segoe UI
        frame = QtWidgets.QFrame()
        frame.setObjectName("LogFrame")
        frame.setLayout(vbox(self.view, margins=(1, 1, 1, 1)))

        self.refresh_button = Button("Refresh", "refresh-cw", themes=self.themes, tooltip="Read the log again (F5)")
        self.live = Switch("Live", self.themes)
        self.live.setToolTip("Show new records as they are written")
        self.summary = label("", "LogSummary")
        self.copy_button = Button("Copy", "copy", themes=self.themes,
                                  tooltip="Copy the selected records, or every shown record when none is selected")
        self.export_button = Button("Export", "download", themes=self.themes,
                                    tooltip="Save the shown records to a text file (Ctrl+E)")
        self.folder_button = Button("Open Folder", "folder-open", themes=self.themes,
                                    tooltip="Open the folder with the log files")
        self.clear_button = Button("Clear Logs", "trash-2", "danger", themes=self.themes,
                                   tooltip="Delete the log files of every day")
        actions = hbox(self.refresh_button, self.live, 14, self.summary, None, self.copy_button, self.export_button,
                       self.folder_button, self.clear_button, spacing=10, margins=(16, 10, 16, 14))

        content = vbox(header, vbox(frame, margins=(16, 12, 16, 0)), actions, spacing=0)
        content.setStretch(1, 1)
        body.setLayout(content)
        self.setLayout(vbox(body, margins=(EDGE, EDGE, EDGE, EDGE)))

        self._live_timer = QtCore.QTimer(self)
        self._live_timer.setInterval(LIVE_INTERVAL)
        self._live_timer.timeout.connect(self._poll)
        self._flash_timer = QtCore.QTimer(self)  # "Copied" / "Exported" on a button for 2 s
        self._flash_timer.setSingleShot(True)
        self._flash_timer.setInterval(2000)
        self._flash_timer.timeout.connect(self._end_flash)
        self.day.currentIndexChanged.connect(lambda _index: self._load(to_end=True))
        self.level.changed.connect(lambda _value: self._render(to_end=True))
        self.search.textChanged.connect(lambda _text: self._render(to_end=True))
        self.refresh_button.clicked.connect(self.reload)
        self.live.toggled.connect(self._set_live)
        self.copy_button.clicked.connect(self.copy_records)
        self.export_button.clicked.connect(self.export_records)
        self.folder_button.clicked.connect(self.runtime.open_logs)
        self.clear_button.clicked.connect(self.clear_all)
        self.view.menu_requested.connect(self._show_menu)
        self._follow_end = False
        self.view.verticalScrollBar().rangeChanged.connect(self._on_range)
        self.view.verticalScrollBar().actionTriggered.connect(self._on_scroll_action)
        self.themes.manager_changed.connect(self._on_theme)
        disable_max_accelerators(self)  # Esc, F5 and the Ctrl shortcuts reach the window, not 3ds Max
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
        self.view.setFocus()
        if self.live.isChecked():
            self._live_timer.start()

    def _place(self):
        """First time centred over the Manager, 85% of its size (at least 860 x 480)."""
        manager = self.manager_window.frameGeometry()
        self.resize(max(860, min(1100, int(manager.width() * 0.85))), max(480, int(manager.height() * 0.85)))
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
        key = event.key()
        control = bool(event.modifiers() & Qt.ControlModifier)
        if key == Qt.Key_Escape:
            if self.view.selected:
                self.view.clear_selection()
            else:
                self.close_window()
        elif key == Qt.Key_F5:
            self.reload()
        elif control and key == Qt.Key_F:
            self.focus_search()
        elif control and key == Qt.Key_C:
            self.copy_records()
        elif control and key == Qt.Key_A:
            self.view.select_all()
        elif control and key == Qt.Key_E:
            self.export_records()
        else:
            QtWidgets.QWidget.keyPressEvent(self, event)

    def _show_menu(self, global_pos):
        menu = themed_menu(self)
        add_action(menu, "Search / Filter (Ctrl+F)", self.focus_search, self.themes, "search")
        copy = add_action(menu, "Copy Selected (Ctrl+C)", self.copy_records, self.themes, "copy")
        copy.setEnabled(bool(self.view.selected))
        add_action(menu, "Export (Ctrl+E)", self.export_records, self.themes, "download")
        add_action(menu, "Go to Latest", self.go_to_latest, self.themes, "scan")
        exec_menu(menu, global_pos)
        menu.deleteLater()

    # --- actions --------------------------------------------------------------------
    def focus_search(self):
        self.search.setFocus()
        self.search.selectAll()

    def copy_records(self):
        """The selected records, or every shown one when nothing is selected, as they stand in the file."""
        records = ([self.view_records[index] for index in sorted(self.view.selected)] if self.view.selected
                   else self.view_records)
        if not records:
            return
        QtWidgets.QApplication.clipboard().setText("\n".join(record.text() for record in records))
        self._flash(self.copy_button, "Copied")

    def export_records(self):
        """Save every shown record (the level filter and the search apply) to a text file the user picks."""
        records = self._shown()
        if not records:
            return
        documents = QtCore.QStandardPaths.writableLocation(QtCore.QStandardPaths.DocumentsLocation)
        name = "MaxPkg-" + os.path.basename(self.day.value() or "runtime.log")
        target, _choice = QtWidgets.QFileDialog.getSaveFileName(self, "Export Log", os.path.join(documents, name),
                                                                "Log files (*.log);;Text files (*.txt)")
        if not target:
            return
        try:
            with open(target, "w", encoding="utf-8") as stream:
                stream.write("\n".join(record.text() for record in records) + "\n")
        except OSError as error:
            log.warning("logs", "Could not export the log: " + str(error))
            self._flash(self.export_button, "Not saved")
            return
        self._flash(self.export_button, "Exported")

    def clear_all(self):
        """Delete every daily log file after a Yes; the view then shows the empty state."""
        days = log_days(self.folder)
        if not days:
            return
        size = size_text(sum(day.size for day in days))
        text = ("The log files of {} days ({}) will be deleted. This cannot be undone.".format(len(days), size)
                if len(days) > 1 else "Today's log file ({}) will be deleted. This cannot be undone.".format(size))
        if not confirm(self, self.themes, "Clear all logs?", text, "Clear Logs", "trash-2", danger=True,
                       icon_name="trash-2"):
            return
        removed, _freed = clear_logs(self.folder)
        if removed < len(days):
            log.warning("logs", "{} of {} log files could not be deleted".format(len(days) - removed, len(days)))
        self.view.clear_selection()
        self._list_days(select_newest=True)
        self._load(to_end=True)

    def go_to_latest(self):
        """The newest day, scrolled to its last record."""
        if self.days and self.day.value() != self.days[0].file_path:
            self.day.set_value(self.days[0].file_path)
            self._load(to_end=True)
        self._scroll_to_end()

    def _scroll_to_end(self):
        """Show the last record. The document lays itself out in steps and grows the scroll range after this call,
        so the view keeps following the end until the user scrolls."""
        self._follow_end = True
        bar = self.view.verticalScrollBar()
        bar.setValue(bar.maximum())

    def _on_range(self, _minimum, maximum):
        if self._follow_end:
            self.view.verticalScrollBar().setValue(maximum)

    def _on_scroll_action(self, _action):
        self._follow_end = False  # the user scrolled (wheel, drag, keys)

    def _flash(self, button, text):
        self._end_flash()
        self._flashing = (button, button.text())
        button.set_label(text)
        self._flash_timer.start()

    def _end_flash(self):
        flashing = getattr(self, "_flashing", None)
        if flashing is not None:
            flashing[0].set_label(flashing[1])
            self._flashing = None

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

    def _on_theme(self):
        self.update()
        if self.isVisible():
            self._render(to_end=False)

    # --- view -----------------------------------------------------------------------
    def _render(self, to_end):
        """Write the shown records into the view. The selection follows its records through a re-read or a
        filter change; records that are no longer shown leave it."""
        vertical = self.view.verticalScrollBar()
        at_end = to_end or vertical.value() >= vertical.maximum() - 4
        position = vertical.value()
        old_keys = _record_keys(self.view_records)
        chosen = set(old_keys[index] for index in self.view.selected if index < len(old_keys))
        anchor = old_keys[self.view.anchor] if self.view.anchor is not None and self.view.anchor < len(old_keys) \
            else None
        shown = self._shown()
        self.summary.setText(summary_text(shown) if self.records else "")
        theme = self.themes.manager
        self.view.setUpdatesEnabled(False)
        self.view.clear()
        self.view.pills = {}
        self.view.rows = {}
        self.view.selection_color = with_alpha(theme.color("accent"), 0.28 if theme.is_light else 0.22)
        cursor = QtGui.QTextCursor(self.view.document())
        cursor.beginEditBlock()
        # Long lines wrap with a hanging indent: the continuation starts under the message column, not under the time.
        hanging = QtGui.QFontMetricsF(self.log_font).horizontalAdvance(" ") * MESSAGE_COLUMN
        block = QtGui.QTextBlockFormat()
        block.setLineHeight(LINE_HEIGHT, PROPORTIONAL_HEIGHT)
        block.setLeftMargin(hanging)
        block.setTextIndent(-hanging)
        cursor.setBlockFormat(block)
        writer = _Writer(cursor, block, theme, self.log_font, self.view.pills, self.view.rows)
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
        indent = " " * MESSAGE_COLUMN
        for index, record in enumerate(shown):
            if record.session_start:
                if not writer.empty:
                    writer.line()
                writer.record = index
                writer.run("Session started {}  ·  {}".format(record.time, record.message), "accent", bold=True)
                writer.line()
                writer.record = -1
                continue
            writer.record = index
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
            writer.record = -1
        cursor.endEditBlock()
        self.view_records = shown
        self.view.count = len(shown)
        keys = _record_keys(shown)
        self.view.set_selection([index for index, key in enumerate(keys) if key in chosen],
                                keys.index(anchor) if anchor in keys else None)
        self.view.setUpdatesEnabled(True)
        if at_end:
            self._scroll_to_end()
        else:
            self._follow_end = False
            vertical.setValue(min(position, vertical.maximum()))


class _Writer(object):
    """Appends coloured runs and lines to the log document and notes which record each line shows."""

    def __init__(self, cursor, block, theme, font, pills, rows):
        self.cursor = cursor
        self.block = block
        self.theme = theme
        self.font = font
        self.pills = pills
        self.rows = rows
        self.record = -1
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
        if self.record >= 0:
            self.rows[self.cursor.blockNumber()] = self.record
        self.cursor.insertText(text, character)
        self.empty = False

    def line(self):
        self.cursor.insertBlock(self.block)
