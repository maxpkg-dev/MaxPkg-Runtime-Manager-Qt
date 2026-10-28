"""Themed confirmation dialog. Never use QMessageBox inside the Manager: it inherits the Manager stylesheet
(light text) but keeps the native button background, so its buttons become white without readable text."""

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt
from .frame import EDGE, WindowChrome, apply_native_frame, paint_window_shape, prepare_window
from .widgets import Button, IconLabel, hbox, label, vbox


class ConfirmDialog(QtWidgets.QDialog):
    """Modal question with the Manager look: icon, title, text, Cancel and a confirm button."""

    def __init__(self, parent, themes, title, text, confirm_text, confirm_icon="", danger=False, icon_name="info"):
        QtWidgets.QDialog.__init__(self, parent)
        self.setObjectName("ConfirmDialog")
        self.setWindowTitle(title)
        self.themes = themes
        prepare_window(self)
        self.chrome = WindowChrome(self, title, themes, collapsible=False, flags=Qt.Dialog)
        self.setModal(True)
        glyph = IconLabel(icon_name, themes, "iconDanger" if danger else "iconAccent", 22)
        heading = label(title, "PageTitle")
        message = label(text, "", wrap=True)
        message.setMinimumWidth(300)
        cancel = Button("Cancel", "", "default", themes)
        confirm = Button(confirm_text, confirm_icon, "danger" if danger else "primary", themes)
        cancel.clicked.connect(self.reject)
        confirm.clicked.connect(self.accept)
        cancel.setDefault(danger)  # a destructive action is never the Enter default
        confirm.setDefault(not danger)
        cancel.setFocus()
        header = QtWidgets.QWidget()
        header.setLayout(hbox(glyph, heading, None, spacing=10))
        self.chrome.attach_title_bar(header)
        body = vbox(header, message, hbox(None, cancel, confirm, spacing=10), spacing=14,
                    margins=(18 + EDGE, 16 + EDGE, 18 + EDGE, 16 + EDGE))
        self.setLayout(body)
        self.setStyleSheet(themes.qss())

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        paint_window_shape(self, painter, theme.color("surfacePrimary"), theme.color("textDisabled"))
        painter.end()

    def showEvent(self, event):
        QtWidgets.QDialog.showEvent(self, event)
        apply_native_frame(self, self.themes.color("textDisabled"))
        parent = self.parentWidget()
        if parent is not None:
            center = parent.frameGeometry().center()
            self.move(center - QtCore.QPoint(self.width() // 2, self.height() // 2))

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QDialog.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QDialog.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QDialog.mouseReleaseEvent(self, event)


def confirm(parent, themes, title, text, confirm_text, confirm_icon="", danger=False, icon_name="info"):
    dialog = ConfirmDialog(parent, themes, title, text, confirm_text, confirm_icon, danger, icon_name)
    accepted = (dialog.exec_() if hasattr(dialog, "exec_") else dialog.exec()) == QtWidgets.QDialog.Accepted
    dialog.deleteLater()
    return accepted
