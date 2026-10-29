"""Themed modal dialogs (confirmation, Support MaxPkg). Never use QMessageBox inside the Manager: it inherits the
Manager stylesheet (light text) but keeps the native button background, so its buttons become white without
readable text."""

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt
from .frame import EDGE, WindowChrome, apply_native_frame, glass_border, native_event, paint_window_shape, prepare_window
from .widgets import Button, IconLabel, Shimmer, hbox, label, vbox

SUPPORT_TEXT = (
    "MaxPkg is free and lives only thanks to its community.",
    "We do not earn anything from the scripts in the catalog or from their sales. Keeping MaxPkg online still "
    "costs money every month: servers, storage, download traffic, the email service for our newsletters and "
    "update notices, and other paid services that are not cheap.",
    "If MaxPkg saves you time, please consider a donation. Every contribution, big or small, keeps the catalog "
    "running and the Package Manager improving. Thank you!",
)


class ThemedDialog(QtWidgets.QDialog):
    """Frameless modal window with the Manager look; subclasses fill it and call `finish(body)`."""

    def __init__(self, parent, themes, title):
        QtWidgets.QDialog.__init__(self, parent)
        self.setWindowTitle(title)
        self.themes = themes
        prepare_window(self)
        self.chrome = WindowChrome(self, title, themes, collapsible=False, flags=Qt.Dialog)
        self.setModal(True)

    def finish(self, header, *rows):
        """Lay out `header` (also the title bar: drag to move) above `rows`."""
        self.chrome.attach_title_bar(header)
        self.setLayout(vbox(header, *rows, spacing=14, margins=(18 + EDGE, 16 + EDGE, 18 + EDGE, 16 + EDGE)))
        self.setStyleSheet(self.themes.qss())

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        paint_window_shape(self, painter, theme.color("surfacePrimary"), glass_border(theme.color("surfacePrimary")))
        painter.end()

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QDialog.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QDialog.showEvent(self, event)
        apply_native_frame(self, glass_border(self.themes.color("surfacePrimary")))
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


class ConfirmDialog(ThemedDialog):
    """Modal question with the Manager look: icon, title, text, Cancel and a confirm button."""

    def __init__(self, parent, themes, title, text, confirm_text, confirm_icon="", danger=False, icon_name="info"):
        ThemedDialog.__init__(self, parent, themes, title)
        self.setObjectName("ConfirmDialog")
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
        self.finish(header, message, hbox(None, cancel, confirm, spacing=10))


class SupportDialog(ThemedDialog):
    """Why MaxPkg needs donations, and a shimmering Donate button (accepted when it is clicked)."""

    def __init__(self, parent, themes):
        ThemedDialog.__init__(self, parent, themes, "Support MaxPkg")
        self.setObjectName("SupportDialog")
        badge = QtWidgets.QLabel()
        badge.setObjectName("NoticeBadge")
        badge.setFixedSize(36, 36)
        badge.setAlignment(Qt.AlignCenter)
        themes.bind_icon(badge, "heart", "iconSuccess", 18)
        header = QtWidgets.QWidget()
        header.setLayout(hbox(badge, label("Support MaxPkg", "PageTitle"), None, spacing=12))
        paragraphs = []
        for text in SUPPORT_TEXT:
            paragraph = label(text, "SupportText", wrap=True)
            paragraph.setFixedWidth(400)
            paragraphs.append(paragraph)
        later = Button("Not now", "", "default", themes)
        later.clicked.connect(self.reject)
        donate = Button("Donate", "heart-success", "installed", themes)
        donate.setToolTip("Opens the MaxPkg donation page in your browser")
        donate.clicked.connect(self.accept)
        donate.shimmer = Shimmer(donate, radius=10)
        donate.setDefault(True)
        self.donate_button = donate
        self.finish(header, vbox(*paragraphs, spacing=10), hbox(None, later, donate, spacing=10))


def _run(dialog):
    accepted = (dialog.exec_() if hasattr(dialog, "exec_") else dialog.exec()) == QtWidgets.QDialog.Accepted
    dialog.deleteLater()
    return accepted


def confirm(parent, themes, title, text, confirm_text, confirm_icon="", danger=False, icon_name="info"):
    return _run(ConfirmDialog(parent, themes, title, text, confirm_text, confirm_icon, danger, icon_name))


def ask_support(parent, themes):
    """True when the user chose Donate."""
    return _run(SupportDialog(parent, themes))
