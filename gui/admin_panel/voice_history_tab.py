# gui/admin_panel/voice_history_tab.py
"""Вкладка «История расшифровок»: что и когда распознал STT, каким движком и с каким результатом."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPlainTextEdit, QSplitter, QMessageBox, QApplication,
)
from PyQt6.QtCore import Qt, QTimer

from gui.async_worker import run_in_background
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

STATUS_LABELS = {"ok": "Готово", "empty": "Пусто", "error": "Ошибка"}
MEDIA_LABELS = {"voice": "Голосовое", "video_note": "Кружок"}
REFRESH_MS = 4000
ROW_LIMIT = 300


def _fetch(status):
    db = DatabaseManager()
    try:
        return db.voice.list_transcriptions(limit=ROW_LIMIT, status=status)
    finally:
        db.close()


def _clear():
    db = DatabaseManager()
    try:
        return db.voice.clear_transcriptions()
    finally:
        db.close()


class VoiceHistoryTab(QWidget):
    COLUMNS = ["Время", "Пользователь", "Тип", "Движок", "Сек", "Статус", "Текст / ошибка"]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rows: list = []
        self._signature = None
        self._loading = False
        self._init_ui()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._auto_refresh)
        self._timer.start(REFRESH_MS)

    def _init_ui(self):
        layout = QVBoxLayout(self)

        bar = QHBoxLayout()
        bar.addWidget(QLabel("Статус:"))
        self.status_filter = QComboBox()
        self.status_filter.addItem("Все", None)
        for key, label in STATUS_LABELS.items():
            self.status_filter.addItem(label, key)
        self.status_filter.currentIndexChanged.connect(self.refresh)
        bar.addWidget(self.status_filter)
        bar.addStretch()
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color: #888; font-size: 11px")
        bar.addWidget(self.count_label)
        refresh_btn = QPushButton("Обновить")
        refresh_btn.clicked.connect(self.refresh)
        bar.addWidget(refresh_btn)
        clear_btn = QPushButton("Очистить историю")
        clear_btn.clicked.connect(self._confirm_clear)
        bar.addWidget(clear_btn)
        layout.addLayout(bar)

        splitter = QSplitter(Qt.Orientation.Vertical)
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels(self.COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.itemSelectionChanged.connect(self._show_details)
        splitter.addWidget(self.table)

        detail_box = QWidget()
        detail_layout = QVBoxLayout(detail_box)
        detail_layout.setContentsMargins(0, 0, 0, 0)
        detail_head = QHBoxLayout()
        detail_head.addWidget(QLabel("Полный текст выбранной расшифровки:"))
        detail_head.addStretch()
        copy_btn = QPushButton("Копировать")
        copy_btn.clicked.connect(self._copy_details)
        detail_head.addWidget(copy_btn)
        detail_layout.addLayout(detail_head)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        detail_layout.addWidget(self.details)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter)

    # ── Данные ────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh()

    def _auto_refresh(self):
        if self.isVisible():
            self.refresh()

    def refresh(self):
        if self._loading:
            return
        self._loading = True
        run_in_background(
            _fetch, self.status_filter.currentData(),
            on_done=self._apply_rows, on_error=self._on_error,
        )

    def _on_error(self, message):
        self._loading = False
        self.count_label.setText(f"Ошибка загрузки: {message}")

    def _apply_rows(self, rows):
        self._loading = False
        signature = [(r["id"], r["status"]) for r in rows]
        if signature == self._signature:
            return  # ничего не изменилось — не трогаем таблицу и выделение
        self._signature = signature
        self._rows = rows

        selected_id = self._selected_id()
        self.table.setUpdatesEnabled(False)
        try:
            self.table.setRowCount(len(rows))
            for i, r in enumerate(rows):
                user = r.get("author_username") or r.get("author_telegram_id") or "—"
                duration = r.get("duration_sec")
                body = r.get("error") if r["status"] == "error" else (r.get("text") or "")
                cells = [
                    str(r.get("created_at") or ""),
                    str(user),
                    MEDIA_LABELS.get(r.get("media_type"), r.get("media_type") or ""),
                    r.get("engine") or "",
                    "" if duration is None else f"{duration:g}",
                    STATUS_LABELS.get(r["status"], r["status"]),
                    " ".join(str(body).split())[:300],
                ]
                for col, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, r["id"])
                    self.table.setItem(i, col, item)
                if r["status"] == "error":
                    for col in range(len(cells)):
                        self.table.item(i, col).setForeground(Qt.GlobalColor.red)
        finally:
            self.table.setUpdatesEnabled(True)

        self.count_label.setText(f"Записей: {len(rows)}")
        if selected_id is not None:
            for i, r in enumerate(rows):
                if r["id"] == selected_id:
                    self.table.selectRow(i)
                    break

    def _selected_id(self):
        row = self.table.currentRow()
        item = self.table.item(row, 0) if row >= 0 else None
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _show_details(self):
        selected = self._selected_id()
        row = next((r for r in self._rows if r["id"] == selected), None)
        if not row:
            self.details.clear()
            return
        text = row.get("text") or ""
        if row.get("error"):
            text = f"{text}\n\nОшибка: {row['error']}".strip()
        self.details.setPlainText(text or "(пусто)")

    def _copy_details(self):
        QApplication.clipboard().setText(self.details.toPlainText())

    def _confirm_clear(self):
        answer = QMessageBox.question(
            self, "Очистить историю", "Удалить всю историю расшифровок? Сообщения в чатах не затрагиваются.",
        )
        if answer == QMessageBox.StandardButton.Yes:
            self._signature = None
            run_in_background(_clear, on_done=lambda _: self.refresh(), on_error=self._on_error)
