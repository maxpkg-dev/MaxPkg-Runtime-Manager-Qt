"""Onboarding window shown after installation: a step-by-step guide built from the HTML welcome window.

Welcome → Discover → Toolbar → Updates, with a clickable stepper, Back / Next and the original texts and
actions. The update choice (automatic or manual) is saved immediately; closing at any step keeps the current
settings. The window stays open while the user explores the Manager.
"""

from ..qt_compat import QtCore, QtGui, QtWidgets, Qt, Signal
from . import icons
from .frame import (EDGE, WindowChrome, apply_native_frame, bounded_position, glass_border, native_event,
                    paint_window_shape, prepare_window)
from .theme import with_alpha
from .widgets import BrandLogo, Button, hbox, label, paint_check, vbox

STEPS = ("Welcome", "Discover", "Toolbar", "Updates")
NARROW = 640


class IconTile(QtWidgets.QLabel):
    def __init__(self, themes, icon_name, size, icon_size, object_name, token="iconAccent"):
        QtWidgets.QLabel.__init__(self)
        self.setObjectName(object_name)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        themes.bind_icon(self, icon_name, token, icon_size)


class Stepper(QtWidgets.QWidget):
    """Circles joined by a line: finished steps show a check, the current one is highlighted. Clickable."""

    selected = Signal(int)

    def __init__(self, themes, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.themes = themes
        self.current = 0
        self.setFixedHeight(58)
        self.setMouseTracking(True)
        self.setCursor(Qt.PointingHandCursor)

    def set_current(self, index):
        self.current = index
        self.update()

    def _centers(self):
        margin = 60
        step = (self.width() - 2 * margin) / float(len(STEPS) - 1)
        return [QtCore.QPointF(margin + index * step, 18) for index in range(len(STEPS))]

    def mouseReleaseEvent(self, event):
        for index, center in enumerate(self._centers()):
            if abs(event.pos().x() - center.x()) < 46:
                self.selected.emit(index)
                return

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        centers = self._centers()
        accent = theme.color("accent")
        for index in range(len(centers) - 1):
            done = index < self.current
            painter.setPen(QtGui.QPen(accent if done else theme.color("borderDefault"), 2))
            painter.drawLine(QtCore.QPointF(centers[index].x() + 14, 18), QtCore.QPointF(centers[index + 1].x() - 14, 18))
        dpr = self.devicePixelRatioF()
        number_font = QtGui.QFont(self.font())
        number_font.setPixelSize(12)
        number_font.setBold(True)
        caption_font = QtGui.QFont(self.font())
        caption_font.setPixelSize(11)
        for index, center in enumerate(centers):
            circle = QtCore.QRectF(center.x() - 12, center.y() - 12, 24, 24)
            if index < self.current:
                painter.setPen(Qt.NoPen)
                painter.setBrush(accent)
                painter.drawEllipse(circle)
                painter.drawPixmap(int(circle.x()) + 5, int(circle.y()) + 5,
                                   icons.pixmap("check", theme.color("backgroundWindow"), 14, dpr))
            elif index == self.current:
                painter.setPen(Qt.NoPen)
                painter.setBrush(with_alpha(accent, 0.22))
                painter.drawEllipse(circle.adjusted(-4, -4, 4, 4))
                painter.setBrush(accent)
                painter.drawEllipse(circle)
                painter.setFont(number_font)
                painter.setPen(theme.color("backgroundWindow"))
                painter.drawText(circle, Qt.AlignCenter, str(index + 1))
            else:
                painter.setPen(QtGui.QPen(theme.color("borderStrong"), 1.5))
                painter.setBrush(theme.color("surfaceSecondary"))
                painter.drawEllipse(circle)
                painter.setFont(number_font)
                painter.setPen(theme.color("textMuted"))
                painter.drawText(circle, Qt.AlignCenter, str(index + 1))
            painter.setFont(caption_font)
            painter.setPen(theme.color("textStrong" if index == self.current else "textMuted"))
            painter.drawText(QtCore.QRectF(center.x() - 50, 36, 100, 18), Qt.AlignCenter, STEPS[index])
        painter.end()


class UpdateChoice(QtWidgets.QAbstractButton):
    """Choice card: icon, title, optional 'Recommended' tag, explanation and a check mark when selected."""

    def __init__(self, icon_name, title, text, themes, recommended=False):
        QtWidgets.QAbstractButton.__init__(self)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self.setMinimumHeight(104)
        self.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        self._icon_name, self._title, self._text = icon_name, title, text
        self._themes = themes
        self._recommended = recommended

    def sizeHint(self):
        return QtCore.QSize(250, 104)

    def paintEvent(self, _event):
        theme = self._themes.manager
        painter = QtGui.QPainter(self)
        painter.setRenderHint(QtGui.QPainter.Antialiasing)
        rect = QtCore.QRectF(self.rect()).adjusted(1, 1, -1, -1)
        checked, hovered = self.isChecked(), self.underMouse()
        accent = theme.color("accent")
        if checked:
            painter.setPen(QtGui.QPen(accent, 1.5))
            painter.setBrush(with_alpha(accent, 0.10))
        else:
            painter.setPen(QtGui.QPen(theme.color("textDisabled" if hovered else "borderDefault"), 1))
            painter.setBrush(theme.color("surfaceHover" if hovered else "surfaceSecondary"))
        painter.drawRoundedRect(rect, 14, 14)
        dpr = self.devicePixelRatioF()
        painter.drawPixmap(18, 18, icons.pixmap(self._icon_name, accent if checked else theme.color("iconPrimary"), 22, dpr))
        title_font = QtGui.QFont(self.font())
        title_font.setPixelSize(15)
        title_font.setBold(True)
        painter.setFont(title_font)
        painter.setPen(theme.color("textStrong"))
        painter.drawText(QtCore.QRect(18, 50, self.width() - 36, 22), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        if self._recommended:
            tag_font = QtGui.QFont(self.font())
            tag_font.setPixelSize(10)
            tag_font.setBold(True)
            metrics = QtGui.QFontMetrics(title_font)
            tag_metrics = QtGui.QFontMetrics(tag_font)
            text = "RECOMMENDED"
            tag = QtCore.QRectF(18 + metrics.horizontalAdvance(self._title) + 10, 52, tag_metrics.horizontalAdvance(text) + 14, 18)
            painter.setPen(QtGui.QPen(theme.color("successBorder"), 1))
            painter.setBrush(theme.color("successSurface"))
            painter.drawRoundedRect(tag, 9, 9)
            painter.setFont(tag_font)
            painter.setPen(theme.color("successText"))
            painter.drawText(tag, Qt.AlignCenter, text)
        text_font = QtGui.QFont(self.font())
        text_font.setPixelSize(12)
        painter.setFont(text_font)
        painter.setPen(theme.color("textSecondary"))
        painter.drawText(QtCore.QRect(18, 74, self.width() - 36, self.height() - 78),
                         Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._text)
        paint_check(painter, QtCore.QRectF(self.width() - 40, 18, 20, 20), checked, hovered, theme, radio=True,
                    dpr=dpr)
        painter.end()


def _page(themes, tile, eyebrow, title, text, extra=None):
    """Centred step page: big icon tile, eyebrow, title, text, then the step's own controls."""
    page = QtWidgets.QWidget()
    column = vbox(spacing=0, margins=(32, 8, 32, 8))
    column.addStretch(1)
    column.addWidget(tile, 0, Qt.AlignHCenter)
    column.addSpacing(22)
    for widget, gap in ((label(eyebrow, "WelcomeEyebrow"), 8), (label(title, "WelcomeTitle", wrap=True), 10),
                        (label(text, "WelcomeText", wrap=True), 22)):
        # Full width with centred text: an alignment flag on a word-wrapped label stops Qt from giving it
        # the height of its wrapped lines (the text was cut after the first line).
        widget.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        column.addWidget(widget)
        column.addSpacing(gap)
    if extra is not None:
        if isinstance(extra, QtWidgets.QLayout):
            column.addLayout(extra)
        else:
            column.addWidget(extra, 0, Qt.AlignHCenter)
    column.addStretch(2)
    page.setLayout(column)
    return page


class WelcomeWindow(QtWidgets.QWidget):
    closed = Signal()

    def __init__(self, runtime, themes, open_manager, parent=None):
        QtWidgets.QWidget.__init__(self, parent)
        self.setObjectName("WelcomeWindow")
        self.setWindowTitle("Welcome to MaxPkg")
        self.runtime = runtime
        self.themes = themes
        self.open_manager = open_manager
        prepare_window(self)
        self.chrome = WindowChrome(self, "Welcome to MaxPkg", themes, collapsible=False, flags=Qt.Window)
        self.setMinimumSize(560, 520)

        header = QtWidgets.QFrame()
        header.setObjectName("WelcomeHeader")
        logo = BrandLogo(themes, size=34, glyph=24)
        brand = label("maxpkg", "WelcomeBrand")
        brand.setAttribute(Qt.WA_TransparentForMouseEvents)
        close_button = self.chrome.window_buttons("Close")[0]
        header.setLayout(hbox(logo, brand, None, close_button, spacing=10, margins=(18, 10, 10, 10)))
        self.chrome.attach_title_bar(header)

        self.stepper = Stepper(themes)
        self.stepper.selected.connect(self.go_to)

        installed = label("✓  Package Manager {} installed".format(runtime.version), "WelcomeInstalled")
        browse = Button("Browse scripts", "arrow-right", "primary", themes)
        browse.setLayoutDirection(Qt.RightToLeft)
        browse.clicked.connect(lambda: self.open_manager("discover"))
        customize = Button("Customize toolbar", "arrow-right", "primary", themes)
        customize.setLayoutDirection(Qt.RightToLeft)
        customize.clicked.connect(lambda: self.open_manager("settings:toolbar"))
        self.automatic = UpdateChoice("sparkles", "Automatically", "Check for updates and install new versions for me.",
                                      themes, recommended=True)
        self.manual = UpdateChoice("settings", "Manually", "I will check and install updates myself.", themes)
        self.automatic.clicked.connect(lambda: self._choose(True))
        self.manual.clicked.connect(lambda: self._choose(False))
        self.choices = QtWidgets.QBoxLayout(QtWidgets.QBoxLayout.LeftToRight)
        self.choices.setSpacing(14)
        self.choices.addWidget(self.automatic)
        self.choices.addWidget(self.manual)
        self.error = label("", "WelcomeError", wrap=True)
        self.error.hide()
        hint = label("You can change this later in Settings.", "WelcomeHint")
        hint.setAlignment(Qt.AlignHCenter)
        updates_controls = vbox(self.choices, hint, self.error, spacing=12)

        self.pages = QtWidgets.QStackedWidget()
        pages = (
            _page(themes, IconTile(themes, "maxpkg-logo", 96, 52, "WelcomeHeroTile", "brandIcon"), "WELCOME",
                  "Your next steps", "You're ready to find, install, and organize your 3ds Max scripts.", installed),
            _page(themes, IconTile(themes, "search", 96, 44, "WelcomeHeroTile"), "STEP 1 OF 3  ·  DISCOVER",
                  "Find your next script", "Browse the catalog and install useful tools.", browse),
            _page(themes, IconTile(themes, "panel-top", 96, 44, "WelcomeHeroTile"), "STEP 2 OF 3  ·  PERSONALIZE",
                  "Set up your toolbar", "Choose your layout, button size, and theme.", customize),
            _page(themes, IconTile(themes, "refresh-cw", 96, 44, "WelcomeHeroTile"), "STEP 3 OF 3  ·  UPDATES",
                  "How should scripts update?", "Pick how MaxPkg keeps your installed scripts current.",
                  updates_controls),
        )
        for page in pages:
            self.pages.addWidget(page)

        footer = QtWidgets.QFrame()
        footer.setObjectName("WelcomeFooter")
        self.back = Button("Back", "arrow-left", "default", themes)
        self.back.clicked.connect(lambda: self.go_to(self.pages.currentIndex() - 1))
        self.next = Button("Get started", "arrow-right", "primary", themes)
        self.next.setLayoutDirection(Qt.RightToLeft)
        self.next.setMinimumWidth(130)
        self.next.clicked.connect(self._next)
        footer.setLayout(hbox(label("This window stays open while you explore.", "WelcomeHint"), None, self.back,
                              self.next, spacing=10, margins=(22, 12, 22, 12)))

        body = vbox(self.stepper, self.pages, spacing=0, margins=(24, 18, 24, 6))
        body.setStretch(1, 1)
        self.setLayout(vbox(header, body, footer, spacing=0, margins=(EDGE, EDGE, EDGE, EDGE)))
        self.setStyleSheet(themes.qss())
        themes.manager_changed.connect(self._restyle)
        self._sync_choice()
        self.go_to(0)

    # --- navigation -------------------------------------------------------------------
    def go_to(self, index):
        index = max(0, min(len(STEPS) - 1, index))
        self.pages.setCurrentIndex(index)
        self.stepper.set_current(index)
        self.back.setVisible(index > 0)
        last = index == len(STEPS) - 1
        self.next.set_label("Get started" if index == 0 else ("Finish" if last else "Next"))
        self.next.icon_name = "check" if last else "arrow-right"
        # Arrows point forward after the text; the Finish check leads like every other icon.
        self.next.setLayoutDirection(Qt.LeftToRight if last else Qt.RightToLeft)
        self.themes.bind_icon(self.next, self.next.icon_name, "textStrong", 16)

    def _next(self):
        if self.pages.currentIndex() >= len(STEPS) - 1:
            self.close()
        else:
            self.go_to(self.pages.currentIndex() + 1)

    def keyPressEvent(self, event):
        key = event.key()
        if key in (Qt.Key_Right, Qt.Key_Return, Qt.Key_Enter):
            self._next()
        elif key == Qt.Key_Left:
            self.go_to(self.pages.currentIndex() - 1)
        elif key == Qt.Key_Escape:
            self.close()
        else:
            QtWidgets.QWidget.keyPressEvent(self, event)

    # --- update choice ----------------------------------------------------------------
    def _sync_choice(self):
        settings = self.runtime.settings
        self.automatic.setChecked(settings.auto_check_packages and settings.download_automatically)
        self.manual.setChecked(not settings.auto_check_packages and not settings.download_automatically)

    def _choose(self, automatic):
        settings = self.runtime.settings
        previous = (settings.auto_check_packages, settings.download_automatically)
        settings.auto_check_packages = settings.download_automatically = automatic
        if not self.runtime.save_settings("updates"):
            settings.auto_check_packages, settings.download_automatically = previous
            self.error.setText("Your choice could not be saved. Try again or change it later in Settings.")
            self.error.show()
        else:
            self.error.hide()
        self._sync_choice()

    def _restyle(self):
        self.setStyleSheet(self.themes.qss())
        apply_native_frame(self, glass_border(self.themes.color("surfaceSecondary")))
        self.update()

    # --- window -----------------------------------------------------------------------
    def show_centered(self):
        if not self.isVisible():
            screen = QtWidgets.QApplication.screenAt(QtGui.QCursor.pos()) or QtWidgets.QApplication.primaryScreen()
            work = screen.availableGeometry()
            self.resize(min(760, work.width() - 24), min(600, work.height() - 64))
            self.move(bounded_position(work.center() - QtCore.QPoint(self.width() // 2, self.height() // 2),
                                       self.size()))
        self.show()
        self.raise_()
        self.activateWindow()

    def resizeEvent(self, event):
        QtWidgets.QWidget.resizeEvent(self, event)
        self.choices.setDirection(QtWidgets.QBoxLayout.TopToBottom if self.width() < NARROW
                                  else QtWidgets.QBoxLayout.LeftToRight)

    def paintEvent(self, _event):
        theme = self.themes.manager
        painter = QtGui.QPainter(self)
        gradient = QtGui.QLinearGradient(0, 0, self.width(), self.height())
        gradient.setColorAt(0.0, theme.color("backgroundGradientTop"))
        gradient.setColorAt(0.48, theme.color("surfaceSecondary"))
        gradient.setColorAt(1.0, theme.color("backgroundGradientBottom"))
        paint_window_shape(self, painter, QtGui.QBrush(gradient), glass_border(theme.color("surfaceSecondary")))
        painter.end()

    def nativeEvent(self, event_type, message):
        handled = native_event(self, message)
        return handled if handled is not None else QtWidgets.QWidget.nativeEvent(self, event_type, message)

    def showEvent(self, event):
        QtWidgets.QWidget.showEvent(self, event)
        apply_native_frame(self, glass_border(self.themes.color("surfaceSecondary")))

    def closeEvent(self, event):
        try:
            self.themes.manager_changed.disconnect(self._restyle)
        except (RuntimeError, TypeError):
            pass
        QtWidgets.QWidget.closeEvent(self, event)
        self.closed.emit()

    def mousePressEvent(self, event):
        if not self.chrome.mouse_press(event):
            QtWidgets.QWidget.mousePressEvent(self, event)

    def mouseMoveEvent(self, event):
        if not self.chrome.mouse_move(event):
            QtWidgets.QWidget.mouseMoveEvent(self, event)

    def mouseReleaseEvent(self, event):
        self.chrome.mouse_release(event)
        QtWidgets.QWidget.mouseReleaseEvent(self, event)


__all__ = ["WelcomeWindow"]
