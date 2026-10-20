"""Макет нового интерфейса SnapMatch (данные вымышленные, логика не подключена).

Запуск из корня проекта:  python tools/ui_mockup/mockup.py [--shot DIR]
Кнопка внизу слева переключает светлую/тёмную тему. Ключ --shot сохраняет PNG всех экранов.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import qtawesome as qta
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QStackedWidget, QLabel, QFrame, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QComboBox, QSlider, QPlainTextEdit, QCheckBox, QSpinBox,
    QFormLayout, QSplitter,
)

import theme

NAV = [
    ("mdi6.account-group-outline", "Пользователи"),
    ("mdi6.tune-variant", "Настройки"),
    ("mdi6.microphone-outline", "Голос"),
    ("mdi6.text-recognition", "Расшифровки"),
    ("mdi6.puzzle-outline", "MCP"),
    ("mdi6.briefcase-outline", "Секретарь"),
]


def card(layout_cls=QVBoxLayout) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    lay = layout_cls(frame)
    lay.setContentsMargins(18, 16, 18, 16)
    lay.setSpacing(10)
    return frame, lay


def label(text: str, name: str = "") -> QLabel:
    w = QLabel(text)
    if name:
        w.setObjectName(name)
    return w


def page_header(title: str, subtitle: str, *buttons: QPushButton) -> QHBoxLayout:
    row = QHBoxLayout()
    col = QVBoxLayout()
    col.setSpacing(2)
    col.addWidget(label(title, "h1"))
    col.addWidget(label(subtitle, "muted"))
    row.addLayout(col)
    row.addStretch()
    for b in buttons:
        row.addWidget(b)
    return row


def make_table(headers: list[str], rows: list[list[str]]) -> QTableWidget:
    t = QTableWidget(len(rows), len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setShowGrid(False)
    t.setAlternatingRowColors(True)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    header = t.horizontalHeader()
    header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    header.setSectionResizeMode(len(headers) - 1, QHeaderView.ResizeMode.Stretch)
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    header.setStretchLastSection(True)
    t.verticalHeader().setDefaultSectionSize(44)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            t.setItem(r, c, QTableWidgetItem(value))
    return t


def primary(text: str, icon: str | None = None) -> QPushButton:
    b = QPushButton(text)
    b.setObjectName("primary")
    return b


class UsersPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        add = primary("+  Добавить")
        root.addLayout(page_header("Пользователи", "Кто общается с ботом и какой у них приоритет", add))

        search = QLineEdit()
        search.setPlaceholderText("Поиск по имени или Telegram ID…")
        root.addWidget(search)

        split = QSplitter()
        table = make_table(
            ["Имя", "Telegram ID", "Приоритет", "Статус"],
            [["Анна К.", "482910337", "5", "Активен"], ["Дмитрий", "129384756", "3", "Активен"],
             ["spam_bot_77", "998877665", "0", "Забанен"], ["Мария", "551203948", "7", "Активен"],
             ["Игорь_dev", "334455667", "10", "Активен"], ["Олеся", "778899001", "1", "Активен"]],
        )
        table.selectRow(0)
        split.addWidget(table)

        side, lay = card()
        lay.addWidget(label("Анна К.", "h2"))
        lay.addWidget(label("ID 482910337 · в чате с 12 сентября", "muted"))
        form = QFormLayout()
        form.setSpacing(10)
        spin = QSpinBox()
        spin.setRange(0, 10)
        spin.setValue(5)
        spin.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        form.addRow("Приоритет", spin)
        lay.addLayout(form)
        lay.addWidget(label("Последние сообщения", "h2"))
        history = QPlainTextEdit("Анна: Привет! Можешь составить план на неделю?\n"
                                 "Бот: Конечно, вот черновик…\nАнна: Добавь туда спортзал")
        history.setReadOnly(True)
        lay.addWidget(history, 1)
        ban = QPushButton("Забанить")
        ban.setObjectName("danger")
        lay.addWidget(ban)
        split.addWidget(side)
        split.setSizes([620, 340])
        root.addWidget(split, 1)


class SettingsPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        save = primary("Сохранить")
        root.addLayout(page_header("Настройки", "Модель, генерация и системный промпт", save))

        row = QHBoxLayout()
        row.setSpacing(16)
        left, ll = card()
        ll.addWidget(label("Модель", "h2"))
        combo = QComboBox()
        combo.addItems(["qwen3.5-4b  ·  LM Studio", "gemma-3-4b-it-qat  ·  LM Studio", "gpt-4o-mini  ·  OpenAI"])
        ll.addWidget(combo)
        ll.addWidget(label("Температура: 0.7", "muted"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setValue(70)
        ll.addWidget(slider)
        ll.addWidget(label("Максимум токенов", "muted"))
        tokens = QSpinBox()
        tokens.setRange(0, 32000)
        tokens.setValue(2048)
        tokens.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        ll.addWidget(tokens)
        stream = QCheckBox("Потоковые ответы")
        stream.setChecked(True)
        ll.addWidget(stream)
        ll.addStretch()
        row.addWidget(left, 1)

        right, rl = card()
        head = QHBoxLayout()
        head.addWidget(label("Системный промпт", "h2"))
        head.addStretch()
        head.addWidget(QPushButton("Проверить"))
        head.addWidget(QPushButton("Редактировать"))
        rl.addLayout(head)
        prompt = QPlainTextEdit("Ты — {{model_name}}, дружелюбный помощник в Telegram.\n"
                                "Отвечай кратко и по делу. Сегодня {{current_date}}.")
        rl.addWidget(prompt, 1)
        rl.addWidget(label("Плейсхолдеры: {{model_name}} · {{current_date}} · {{pending_requests}}", "muted"))
        row.addWidget(right, 2)
        root.addLayout(row, 1)


class TranscriptsPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(16)
        root.addLayout(page_header("Расшифровки", "Что распознал STT из голосовых и кружочков",
                                   QPushButton("Обновить"), QPushButton("Очистить")))
        table = make_table(
            ["Время", "Пользователь", "Тип", "Движок", "Сек", "Статус", "Текст"],
            [["19.10 03:41", "Анна К.", "Голосовое", "vosk", "7", "", "Напомни завтра позвонить маме в десять утра"],
             ["19.10 03:12", "Дмитрий", "Кружок", "groq", "14", "", "Короче, встречаемся у входа, я буду минут через…"],
             ["19.10 02:58", "Мария", "Голосовое", "vosk", "3", "", "—"],
             ["19.10 02:30", "Игорь_dev", "Голосовое", "custom", "21", "", "HTTP 503: STT endpoint недоступен"]],
        )
        for r, (text, name) in enumerate([("Готово", "chip_ok"), ("Готово", "chip_ok"),
                                          ("Пусто", "chip_empty"), ("Ошибка", "chip_err")]):
            chip = QLabel(text)
            chip.setObjectName(name)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            holder = QWidget()
            hl = QHBoxLayout(holder)
            hl.setContentsMargins(6, 10, 6, 10)
            hl.addWidget(chip, 0, Qt.AlignmentFlag.AlignLeft)
            table.setCellWidget(r, 5, holder)
        table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(5, 110)
        table.selectRow(0)
        root.addWidget(table, 1)
        box, bl = card()
        bl.addWidget(label("Полный текст", "h2"))
        bl.addWidget(label("Напомни завтра позвонить маме в десять утра и купить подарок к субботе.", "muted"))
        root.addWidget(box)


class PlaceholderPage(QWidget):
    def __init__(self, title: str):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(28, 24, 28, 24)
        lay.addLayout(page_header(title, "Экран переносится на новую тему так же, как остальные"))
        lay.addStretch()


class Mockup(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SnapMatch — макет интерфейса")
        self.resize(1180, 760)
        self.dark = True

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        side = QWidget()
        side.setObjectName("sidebar")
        side.setFixedWidth(220)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 18, 14, 14)
        sl.addWidget(label("SnapMatch", "brand"))
        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        self.nav.setIconSize(QSize(20, 20))
        for icon, text in NAV:
            QListWidgetItem(qta.icon(icon, color="#8B96AB"), text, self.nav)
        sl.addWidget(self.nav, 1)
        self.theme_btn = QPushButton("Светлая тема")
        self.theme_btn.clicked.connect(self.toggle_theme)
        sl.addWidget(self.theme_btn)
        sl.addWidget(label("v1.0.4.4", "muted"))
        outer.addWidget(side)

        self.pages = QStackedWidget()
        self.pages.addWidget(UsersPage())
        self.pages.addWidget(SettingsPage())
        self.pages.addWidget(PlaceholderPage("Голос"))
        self.pages.addWidget(TranscriptsPage())
        self.pages.addWidget(PlaceholderPage("MCP"))
        self.pages.addWidget(PlaceholderPage("Секретарь"))
        outer.addWidget(self.pages, 1)

        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)
        self.apply_theme()

    def toggle_theme(self):
        self.dark = not self.dark
        self.apply_theme()

    def apply_theme(self):
        tokens = theme.DARK if self.dark else theme.LIGHT
        QApplication.instance().setStyleSheet(theme.build_qss(tokens))
        self.theme_btn.setText("Светлая тема" if self.dark else "Тёмная тема")
        # иконки навигации перекрашиваем под тему
        for i, (icon, _text) in enumerate(NAV):
            self.nav.item(i).setIcon(qta.icon(icon, color=tokens["text_muted"], color_active=tokens["accent"]))


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = Mockup()
    win.show()
    if "--shot" in sys.argv:
        out = sys.argv[sys.argv.index("--shot") + 1]
        os.makedirs(out, exist_ok=True)

        def shoot():
            for dark in (True, False):
                win.dark = dark
                win.apply_theme()
                for idx, name in ((0, "users"), (1, "settings"), (3, "transcripts")):
                    win.nav.setCurrentRow(idx)
                    app.processEvents()
                    win.grab().save(os.path.join(out, f"{'dark' if dark else 'light'}_{name}.png"))
            app.quit()

        from PyQt6.QtCore import QTimer
        QTimer.singleShot(400, shoot)
    sys.exit(app.exec())
