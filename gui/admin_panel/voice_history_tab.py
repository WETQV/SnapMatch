# gui/admin_panel/voice_history_tab.py
"""Вкладка «История расшифровок»: что и когда распознал STT, каким движком и с каким результатом."""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QPlainTextEdit, QSplitter, QApplication,
)
from PyQt6.QtCore import Qt, QTimer

from gui.async_worker import run_in_background
from gui.design.dialogs import ask
from gui.design import FxComboBox, StatusBadge, card, icon_button, label, make_table, page_header
from utils.database.database_manager import DatabaseManager
from utils.logger import setup_logger

logger = setup_logger(__name__)

STATUS_LABELS = {"ok": "Готово", "empty": "Пусто", "error": "Ошибка"}
STATUS_KINDS = {"ok": "ok", "empty": "warn", "error": "error"}
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
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        # Шапка: фильтр статуса, счётчик и кнопки
        self.status_filter = FxComboBox()
        self.status_filter.addItem("Все", None)
        for key, text in STATUS_LABELS.items():
            self.status_filter.addItem(text, key)
        self.status_filter.setMinimumWidth(120)
        self.status_filter.setToolTip("Фильтр по статусу\nПоказывать только расшифровки с выбранным результатом.")
        self.status_filter.currentIndexChanged.connect(self.refresh)
        self.count_label = label("", "muted")
        refresh_btn = icon_button("Обновить", "mdi6.refresh")
        refresh_btn.setToolTip("Обновить\nЗагрузить список заново. Открытая вкладка обновляется сама раз в 4 секунды.")
        refresh_btn.clicked.connect(self.refresh)
        clear_btn = icon_button("Очистить историю", "mdi6.trash-can-outline", "danger")
        clear_btn.setToolTip("Очистить историю\nУдаляет все записи расшифровок. Сообщения в чатах не затрагиваются.")
        clear_btn.clicked.connect(self._confirm_clear)
        layout.addLayout(page_header("Расшифровки", "Результаты распознавания голосовых и кружочков", refresh_btn, clear_btn))

        # Строка фильтра под шапкой
        filter_row = QHBoxLayout()
        filter_row.addWidget(label("СТАТУС", "sectionLabel"))
        filter_row.addWidget(self.status_filter)
        filter_row.addSpacing(8)
        filter_row.addWidget(self.count_label)
        filter_row.addStretch()
        layout.addLayout(filter_row)

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.setChildrenCollapsible(False)
        self.table = make_table(self.COLUMNS)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(self.COLUMNS) - 1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)   # StatusBadge шире текста пустой ячейки
        self.table.setColumnWidth(5, 116)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setMinimumHeight(160)
        self.table.itemSelectionChanged.connect(self._show_details)
        splitter.addWidget(self.table)

        detail_box, detail_layout = card()
        detail_head = QHBoxLayout()
        detail_head.addWidget(label("Полный текст", "h2"))
        detail_head.addWidget(label("выбранной расшифровки", "muted"))
        detail_head.addStretch()
        copy_btn = icon_button("Копировать", "mdi6.content-copy")
        copy_btn.setToolTip("Копировать\nКладёт полный текст выбранной расшифровки в буфер обмена.")
        copy_btn.clicked.connect(self._copy_details)
        detail_head.addWidget(copy_btn)
        detail_layout.addLayout(detail_head)
        self.details = QPlainTextEdit()
        self.details.setReadOnly(True)
        self.details.setMinimumHeight(70)
        detail_layout.addWidget(self.details)
        splitter.addWidget(detail_box)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, 1)

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
                created = str(r.get("created_at") or "")
                cells = [
                    created[5:16] if len(created) >= 16 else created,   # «ММ-ДД ЧЧ:ММ», полное время — в подсказке
                    str(user),
                    MEDIA_LABELS.get(r.get("media_type"), r.get("media_type") or ""),
                    r.get("engine") or "",
                    "" if duration is None else f"{duration:g}",
                    "",  # колонка статуса: вместо текста — StatusBadge
                    " ".join(str(body).split())[:300],
                ]
                for col, value in enumerate(cells):
                    item = QTableWidgetItem(value)
                    if col == 0:
                        item.setData(Qt.ItemDataRole.UserRole, r["id"])
                        item.setToolTip(created)
                    self.table.setItem(i, col, item)
                holder = QWidget()
                holder.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)  # клик выделяет строку
                hl = QHBoxLayout(holder)
                hl.setContentsMargins(6, 0, 6, 0)
                hl.addWidget(
                    StatusBadge(STATUS_LABELS.get(r["status"], r["status"]), STATUS_KINDS.get(r["status"], "idle"), pulse=False),
                    0, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                )
                self.table.setCellWidget(i, 5, holder)
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
        if ask(self, "Очистить историю", "Удалить всю историю расшифровок? Сообщения в чатах не затрагиваются.",
               yes="Удалить", danger=True):
            self._signature = None
            run_in_background(_clear, on_done=lambda _: self.refresh(), on_error=self._on_error)
