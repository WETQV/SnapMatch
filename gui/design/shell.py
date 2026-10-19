"""Оболочка окна: собственный заголовок и собственная рамка (frameless) с изменением размера по краям.

Использование (см. gui/admin_panel/admin_panel_base.py):
    root = GlowRoot(); window.setCentralWidget(root)       # корень рисует фон, полосу панели и скругление
    titlebar = TitleBar(window); outer.addWidget(titlebar)  # заголовок — прозрачный, скрыт по умолчанию
    frame = FrameController(window, root, titlebar)         # включает/выключает рамку, ловит края
    frame.set_frameless(True)

ВАЖНО (Wayland): WA_TranslucentBackground ставится на окно ДО первого show() и остаётся включённым всегда —
иначе у скруглённой рамки остаются квадратные уголки. Без собственной рамки GlowRoot рисует непрозрачный фон.
"""
from PyQt6.QtCore import QEvent, QObject, Qt
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QApplication, QHBoxLayout, QLabel, QMainWindow, QWidget

from gui.design.widgets import GlowRoot, IconTile, WinButton

EDGE = 6                 # ширина зоны изменения размера у собственной рамки, px
FRAME_RADIUS = 12        # скругление окна с собственной рамкой


def prepare_translucent(window: QMainWindow) -> None:
    """Включает прозрачность окна. Вызывать в конструкторе, до первого show()."""
    window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)


class TitleBar(QWidget):
    """Собственный заголовок окна: перетаскивание (startSystemMove — работает и на Wayland),
    двойной клик — развернуть/восстановить, кнопки свернуть/развернуть/закрыть."""

    def __init__(self, window: QMainWindow, title: str = "SnapMatch") -> None:
        super().__init__()
        self.win = window
        self.setObjectName("titlebar")
        self.setFixedHeight(38)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 6, 0)
        lay.setSpacing(8)
        lay.addWidget(IconTile("mdi6.hexagon-slice-6", "ok", 24))
        self.title = QLabel(title)
        self.title.setObjectName("h2")
        lay.addWidget(self.title)
        lay.addStretch()
        self.btn_min = WinButton("mdi6.window-minimize")
        self.btn_max = WinButton("mdi6.window-maximize")
        self.btn_close = WinButton("mdi6.window-close", danger=True)
        self.btn_min.clicked.connect(window.showMinimized)
        self.btn_max.clicked.connect(self.toggle_maximize)
        self.btn_close.clicked.connect(window.close)
        for b in (self.btn_min, self.btn_max, self.btn_close):
            lay.addWidget(b)

    def toggle_maximize(self) -> None:
        self.win.showNormal() if self.win.isMaximized() else self.win.showMaximized()

    def sync_icon(self) -> None:
        """Обновляет иконку «развернуть/восстановить» по состоянию окна."""
        self.btn_max.set_icon_name("mdi6.window-restore" if self.win.isMaximized() else "mdi6.window-maximize")

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.win.windowHandle():
            self.win.windowHandle().startSystemMove()   # двигает композитор
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximize()
        super().mouseDoubleClickEvent(event)


class FrameController(QObject):
    """Управляет собственной рамкой окна: флаг FramelessWindowHint, заголовок, скругление корня,
    изменение размера по краям (startSystemResize) и иконка maximize/restore."""

    def __init__(self, window: QMainWindow, root: GlowRoot, titlebar: TitleBar) -> None:
        super().__init__(window)
        self.window, self.root, self.titlebar = window, root, titlebar
        self.frameless = False
        self._edge_cursor = False
        titlebar.hide()
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    # ── включение/выключение ──
    def set_frameless(self, on: bool) -> None:
        if on == self.frameless:
            return
        was_visible = self.window.isVisible()
        self.frameless = on
        self.window.setWindowFlag(Qt.WindowType.FramelessWindowHint, on)
        self.titlebar.setVisible(on)
        self.root.top_offset = self.titlebar.height() if on else 0
        self.update_corners()
        if was_visible:                       # смена флага скрывает окно — показываем снова
            self.window.show()

    def update_corners(self) -> None:
        w = self.window
        rounded = self.frameless and not w.isMaximized() and not w.isFullScreen()
        self.root.corner_radius = FRAME_RADIUS if rounded else 0
        self.root.update()
        self.titlebar.sync_icon()

    # ── края окна ──
    def _edges_at(self, pos) -> Qt.Edge:
        w = self.window
        edges = Qt.Edge(0)
        if pos.x() <= EDGE:
            edges |= Qt.Edge.LeftEdge
        if pos.x() >= w.width() - EDGE:
            edges |= Qt.Edge.RightEdge
        if pos.y() <= EDGE:
            edges |= Qt.Edge.TopEdge
        if pos.y() >= w.height() - EDGE:
            edges |= Qt.Edge.BottomEdge
        return edges

    @staticmethod
    def _cursor_for(edges: Qt.Edge):
        horizontal = bool(edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge))
        vertical = bool(edges & (Qt.Edge.TopEdge | Qt.Edge.BottomEdge))
        if horizontal and vertical:
            diag = bool(edges & Qt.Edge.LeftEdge and edges & Qt.Edge.TopEdge) or bool(
                edges & Qt.Edge.RightEdge and edges & Qt.Edge.BottomEdge)
            return Qt.CursorShape.SizeFDiagCursor if diag else Qt.CursorShape.SizeBDiagCursor
        return Qt.CursorShape.SizeHorCursor if horizontal else Qt.CursorShape.SizeVerCursor

    def _reset_cursor(self) -> None:
        if self._edge_cursor:
            QGuiApplication.restoreOverrideCursor()
            self._edge_cursor = False

    def eventFilter(self, obj, event):  # noqa: N802
        w = self.window
        kind = event.type()
        if obj is w and kind == QEvent.Type.WindowStateChange:
            self.update_corners()
            return False
        if not self.frameless or w.isMaximized() or not isinstance(obj, QWidget) or obj.window() is not w:
            self._reset_cursor()
            return False
        if kind not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress):
            return False
        edges = self._edges_at(w.mapFromGlobal(event.globalPosition().toPoint()))
        if kind == QEvent.Type.MouseMove:
            if edges and not self._edge_cursor:
                QGuiApplication.setOverrideCursor(QCursor(self._cursor_for(edges)))
                self._edge_cursor = True
            elif edges and self._edge_cursor:
                QGuiApplication.changeOverrideCursor(QCursor(self._cursor_for(edges)))
            elif not edges:
                self._reset_cursor()
        elif edges and event.button() == Qt.MouseButton.LeftButton and w.windowHandle():
            w.windowHandle().startSystemResize(edges)
            return True
        return False
