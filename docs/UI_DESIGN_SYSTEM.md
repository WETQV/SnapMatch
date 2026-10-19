# Дизайн-система SnapMatch (gui/design)

Пакет `gui/design/` — единственный источник внешнего вида. Макет-эталон: `tools/ui_mockup/` (в старом каталоге, не менять).

## Структура
| Модуль | Что внутри |
|---|---|
| `tokens.py` | палитры dark/light/oled, `make_tokens`, `build_qss`, `tokens()` (текущие токены). **Единственное место, где разрешены hex-цвета** |
| `widgets.py` | виджеты и помощники сборки страниц |
| `motion.py` | `FadeStack`, `NavIndicator`, `Toast`, `SegmentedControl`, `fade_in`, флаг `ENABLED` / `set_enabled()` |
| `tooltip.py` | `TooltipManager(app)` — свои подсказки |
| `shell.py` | `TitleBar`, `FrameController` (собственная рамка, resize по краям), `prepare_translucent` |
| `appearance.py` | настройки оформления, применение темы, шрифты, `AppearanceCard` |
| `icons.py` | иконки qtawesome (`mdi6.*`) с кэшем; без qtawesome возвращает пустой `QIcon()` |

Реэкспорт: `from gui.design import card, label, page_header, primary, FxButton, ...` (имя `tokens` занято модулем, функция экспортируется как `current_tokens`).

## Токены
`bg`, `surface`, `surface_alt`, `border`, `text`, `text_muted`, `input_bg`, `hover_fill`, `accent`, `accent_hover`, `accent_text`, `danger`, `warning`, `info` (цвета статусов — только для статусов), `knob`, `win_close`, `is_dark`. Режимы: system / dark / light / oled. Акцент: system / brand (`#22C58B`) / свой hex. Радиус 12, шрифты Manrope (UI) и JetBrains Mono (id, команды, числа).

## Правила
1. **Один акцент**, никаких градиентов и «свечения»: глубина — уровни поверхностей и тонкие линии.
2. **Hex-цвета в коде запрещены** (вне `tokens.py`). Цвет — из `tokens()`/`icons.icon(name, "accent")`, стиль — через QSS по `objectName` (`h1`, `h2`, `muted`, `mono`, `sectionLabel`, `card`, `rowCard`, `divider`, `fieldError`...). Не вызывайте `setStyleSheet` на виджетах — перебьёте тему.
3. **Анимации только через `gui/design/motion.py`** (или `Progress` из `widgets.py`) и всегда проверяют `motion.ENABLED`. Анимируем прозрачность и сдвиг, 140–250 мс, `OutCubic`.
4. **Подсказки**: первая строка `toolTip` — заголовок (жирным), остальное — пояснение. `setToolTip("Запустить сервер\nПроцесс стартует в фоне.")`.
5. Иконки — только через `icons.icon()` / `icon_button()`; цвета иконок — роли токенов.

## Что взять
- **Кнопки**: `FxButton("Текст")` (обычная), `primary("Сохранить")` (одна на экран), `icon_button("Старт", "mdi6.play-outline", variant="")`; `setObjectName("danger"|"pill"|"tab")`. Обычный `QPushButton` получит запасной стиль, но для новых экранов берите `FxButton`.
- **Переключатели**: `SwitchRow(текст, checked)` вместо `QCheckBox` (API: `toggled`, `isChecked`, `setChecked`).
- **Списки/слайдер**: `FxComboBox`, `FxSlider`. Поля ввода — обычные `QLineEdit/QSpinBox/QPlainTextEdit` (стилизованы QSS; моно-шрифт — `setObjectName("mono")`).
- **Статусы**: `StatusBadge(text, kind)` (ok/error/warn/idle/info), `IconTile`, `StatTile(value, caption, icon, kind)` (число «набегает»), `ServerCard` — строка списка с выбором.
- **Структура**: `card()` → `(frame, layout)`, `label(text, "h2")`, `page_header(title, subtitle, *buttons)`, `make_table(headers, rows)`, `Collapsible(title, content)`, `SegmentedControl(labels)` (вкладки-«пилюли» внутри экрана), `Toast` — `window.toast.show_message("...")`.
- **Тема/акцент**: `AppearanceCard`, `appearance.controller()` (`changed(dict)`, `frameless_changed(bool)`).

## Сборка страницы
```python
class MyPage(QWidget):
    def __init__(self):
        super().__init__()
        root = QVBoxLayout(self); root.setContentsMargins(28, 24, 28, 24); root.setSpacing(16)
        save = primary("Сохранить")
        root.addLayout(page_header("Заголовок", "Одна строка пояснения", save))
        box, lay = card()
        lay.addWidget(label("Секция", "h2"))
        lay.addWidget(SwitchRow("Включить что-то", True))
        root.addWidget(box); root.addStretch()
```
Длинные формы кладите в `QScrollArea` (`setWidgetResizable(True)`, `setFrameShape(NoFrame)`). Карточки верхнего уровня (`QFrame#card`) появляются лесенкой при переключении экрана (`FadeStack`).

## Новый экран в навигации
В `gui/admin_panel/admin_panel_base.py::init_ui` после создания страницы: `self.add_page("Название", "mdi6.иконка", widget)` — порядок вызовов = порядок пунктов. Переключить: `self.show_page(widget_or_index)`. Уведомление: `self.toast.show_message(...)`. Каталог иконок: имена `mdi6.*` из Material Design Icons.

## Настройки оформления (config.json)
`ui_theme` (system|dark|light|oled, по умолчанию dark), `ui_accent` (system|brand|#RRGGBB), `ui_frameless` (bool), `ui_animations` (bool). Старый `oled_mode` синхронизируется (= `ui_theme == "oled"`), источник правды — `ui_theme`. Старый конфиг с `oled_mode: true` без `ui_theme` мигрирует в `oled`.

## Известные ограничения старых экранов
Внутренности вкладок (кроме «Доп. настроек» — карточки оформления) ещё не перенесены: у них встречаются жёстко заданные цвета в `setStyleSheet` (статусы, справка в «Голосе», диалоги статистики) и макеты, рассчитанные на окно без боковой панели. Запасные правила QSS делают их читаемыми во всех темах, но не заменяют переноса.
