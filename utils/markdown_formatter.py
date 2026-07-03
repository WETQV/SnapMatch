# utils/markdown_formatter.py

import re
import html
from typing import Tuple, Optional

class TelegramMarkdownRenderer:
    """
    Упрощённый и надёжный рендерер Markdown для Telegram.
    Поддерживает только те элементы, которые понимает Telegram.
    """
    
    def __init__(self):
        # Telegram поддерживаемые HTML теги
        self.supported_tags = {
            'b', 'strong', 'i', 'em', 'u', 'ins', 's', 'strike', 'del',
            'code', 'pre', 'a', 'tg-spoiler'
        }
    
    def process_text(self, text: str) -> Tuple[str, Optional[str]]:
        """
        Основная функция обработки текста.
        Возвращает (обработанный_текст, parse_mode)
        """
        if not text or not text.strip():
            return "Пустой ответ от модели.", None
        
        # Очищаем от проблемных символов
        text = self._clean_hidden_characters(text)
        
        # ВСЕ блоки кода принудительно в HTML!
        # Заменяем блоки кода: от ``` до ``` или до конца строки ($)
        # [^\n]* позволяет захватить имя языка (python, cpp и т.д.)
        text = re.sub(r'```([^\n]*)\n?([\s\S]*?)(?:```|$)', self._replace_code_block_match, text)
        
        # Если есть HTML теги от блоков кода - принудительно используем HTML режим
        has_code_blocks = '<pre><code>' in text
        
        # Определяем тип форматирования
        if self._has_markdown(text) or has_code_blocks:
            if has_code_blocks:
                # ПРИНУДИТЕЛЬНО HTML для блоков кода
                html_text = self._markdown_to_html(text)
                return html_text, 'HTML'
            elif self._is_simple_markdown(text) and len(text) <= 1000:
                # Простой Markdown - используем MarkdownV2
                formatted_text = self._process_simple_markdown(text)
                return formatted_text, 'MarkdownV2'
            else:
                # Сложный Markdown - конвертируем в HTML
                html_text = self._markdown_to_html(text)
                return html_text, 'HTML'
        else:
            # Нет форматирования
            return text, None

    def split_for_telegram(self, text: str, parse_mode: Optional[str], max_len: int = 4096) -> Tuple[list, Optional[str]]:
        """
        Безопасно разбивает текст под лимит Telegram. Старается резать по абзацам/предложениям/словам.
        Если parse_mode == 'MarkdownV2', дополнительно следит за парными маркерами.
        Возвращает (parts, parse_mode)
        """
        if not text:
            return [""], parse_mode

        # Резерв небольшой, чтобы избежать ошибок из-за экранирования
        budget = max_len - 50
        parts = []

        def flush_chunk(chunk: str):
            if chunk:
                parts.append(chunk)

        remaining = text
        while len(remaining) > budget:
            cut = remaining[:budget]

            # 1) Пытаемся резать по двойному переводу строки (абзац)
            idx = cut.rfind("\n\n")
            if idx < 0:
                # 2) По одному переводу строки
                idx = cut.rfind("\n")
            if idx < 0:
                # 3) По окончанию предложения
                for punct in ['. ', '! ', '? ']:
                    idx = cut.rfind(punct)
                    if idx >= 0:
                        idx += 1  # оставить знак в конце
                        break
            if idx < 0:
                # 4) По пробелу
                idx = cut.rfind(' ')
            if idx < 0:
                # 5) Жесткая обрезка
                idx = budget

            # Не режем внутри HTML-тега
            if parse_mode == 'HTML':
                open_tag = cut.rfind('<')
                close_tag = cut.rfind('>')
                if open_tag > close_tag:
                    # переносим разрез до начала потенциального незакрытого тега
                    idx = min(idx, open_tag)

            # Не режем внутри кодовых конструкций Markdown
            if parse_mode == 'MarkdownV2' or parse_mode is None:
                # Тройные бэктики
                if cut.count('```') % 2 == 1:
                    idx = cut.rfind('```')
                # Инлайновые бэктики
                if cut.count('`') % 2 == 1:
                    backtick_idx = cut.rfind('`')
                    if backtick_idx != -1:
                        idx = min(idx, backtick_idx)

            chunk = remaining[:idx].rstrip()
            remaining = remaining[idx:].lstrip()

            if parse_mode == 'MarkdownV2':
                chunk = self._balance_markdown(chunk)

            flush_chunk(chunk)

        # Хвост
        tail = remaining
        if parse_mode == 'MarkdownV2':
            tail = self._balance_markdown(tail)
        flush_chunk(tail)

        return parts, parse_mode

    def _balance_markdown(self, text: str) -> str:
        """
        Закрывает незакрытые простые маркеры MarkdownV2 (*, _, `) в конце чанка,
        чтобы Telegram не ругался. Очень простая эвристика.
        """
        # Удаляем возможные утечки временных маркеров (приватные Unicode-метки)
        text = re.sub(r'[\uE000-\uE00F][A-Z]\d+[\uE000-\uE00F]', '', text)
        for marker in ['*', '_', '`']:
            if text.count(marker) % 2 != 0:
                text += marker
        return text

    def force_html(self, text: str) -> str:
        """
        Принудительно конвертирует входной текст в HTML, даже если он простой.
        Использует те же правила, что и markdown_to_html.
        """
        # Преобразуем блоки кода: от ``` до ``` или до конца строки ($)
        text = re.sub(r'```([^\n]*)\n?([\s\S]*?)(?:```|$)', self._replace_code_block_match, text)
        return self._markdown_to_html(text)

    def html_to_plain_text(self, text: str) -> str:
        """Превращает HTML-разметку в обычный текст для отправки без parse_mode."""
        if not text:
            return text

        text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
        text = re.sub(
            r'</?(pre|code|b|strong|i|em|u|ins|s|strike|del|a|tg-spoiler)[^>]*>',
            '',
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r'<[^>]+>', '', text)
        return html.unescape(text)

    def _replace_code_block_match(self, match):
        """Хелпер для замены блока кода на HTML pre/code"""
        lang = match.group(1).strip() if match.group(1) else ""
        code_content = match.group(2) if match.group(2) else ""
        
        # Экранируем спецсимволы HTML
        escaped_code = code_content.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
        return f"<pre><code>{escaped_code}</code></pre>"
    
    def unescape_markdown_v2(self, text: str) -> str:
        """
        Убирает обратные слеши экранирования MarkdownV2, чтобы текст выглядел нормально
        при отправке как HTML или Plain Text.
        """
        if not text:
            return text
        # Сначала схлопываем двойные обратные слеши \\ -> \
        text = text.replace('\\\\', '\\')
        # Затем удаляем экранирование для спецсимволов MarkdownV2
        pattern = r"\\([_*\[\]\(\)~`>\#\+\-=\|\{\}\.\!])"
        return re.sub(pattern, r"\1", text)
    
    def _clean_hidden_characters(self, text: str) -> str:
        """Очищает текст от невидимых Unicode символов"""
        # Список проблемных диапазонов
        control_ranges = [
            (0x0000, 0x0008), (0x000B, 0x000C), (0x000E, 0x001F),
            (0x007F, 0x009F), (0x200B, 0x200F), (0x2028, 0x202E),
            (0x2060, 0x2064), (0xFEFF, 0xFEFF), (0xFFF9, 0xFFFC)
        ]
        
        result = []
        for char in text:
            code = ord(char)
            is_control = any(start <= code <= end for start, end in control_ranges)
            result.append(' ' if is_control else char)
        
        return ''.join(result)
    
    def _has_markdown(self, text: str) -> bool:
        """Проверяет наличие Markdown форматирования"""
        patterns = [
            r'\*\*[^*\n]+?\*\*',           # Bold
            r'(?<!\*)\*[^*\n]+?\*(?!\*)',  # Italic
            r'`[^`\n]+?`',                 # Inline code
            r'```[\s\S]*?```',             # Code block
            r'\[[^\]]+\]\([^)]+\)',        # Links
            r'^#{1,6}\s+',                 # Headers
            r'^>\s+',                      # Quotes
            r'^[-*+]\s+',                  # Lists
        ]
        
        return any(re.search(pattern, text, re.MULTILINE) for pattern in patterns)
    
    def _is_simple_markdown(self, text: str) -> bool:
        """Проверяет, содержит ли только простое форматирование"""
        # Считаем простым, если есть только жирный/курсив/код
        simple_patterns = [
            r'\*\*[^*\n]+?\*\*',    # Bold
            r'\*[^*\n]+?\*',        # Italic  
            r'`[^`\n]+?`',          # Inline code
        ]
        
        # Убираем простые паттерны
        temp_text = text
        for pattern in simple_patterns:
            temp_text = re.sub(pattern, '', temp_text)
        
        # Если после удаления простых паттернов не осталось сложных, то это простой MD
        complex_patterns = [
            r'```[\s\S]*?```',      # Code blocks
            r'\[[^\]]+\]\([^)]+\)', # Links
            r'^#{1,6}\s+',          # Headers
            r'^>\s+',               # Quotes
            r'^[-*+]\s+',           # Lists
        ]
        
        return not any(re.search(pattern, temp_text, re.MULTILINE) 
                      for pattern in complex_patterns)
    
    def _process_simple_markdown(self, text: str) -> str:
        """Обрабатывает простой Markdown для MarkdownV2"""
        # Экранируем специальные символы MarkdownV2
        special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', 
                        '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']

        def escape_inner(value: str) -> str:
            for char in special_chars:
                value = value.replace(char, f'\\{char}')
            return value
        
        # Сначала сохраняем форматирование — используем приватные Unicode-маркеры
        temp_markers = {}
        counter = 0
        
        # Сохраняем жирный текст
        def save_bold(match):
            nonlocal counter
            marker = f"\uE000B{counter}\uE001"
            temp_markers[marker] = f"*{escape_inner(match.group(1))}*"
            counter += 1
            return marker
        
        text = re.sub(r'\*\*([^*\n]+?)\*\*', save_bold, text)
        
        # Сохраняем курсив
        def save_italic(match):
            nonlocal counter
            marker = f"\uE000I{counter}\uE001"
            temp_markers[marker] = f"_{escape_inner(match.group(1))}_"
            counter += 1
            return marker
        
        text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', save_italic, text)
        
        # Сохраняем код
        def save_code(match):
            nonlocal counter
            marker = f"\uE000C{counter}\uE001"
            temp_markers[marker] = f"`{match.group(1)}"+"`"
            counter += 1
            return marker
        
        text = re.sub(r'`([^`\n]+?)`', save_code, text)
        
        # Экранируем специальные символы
        for char in special_chars:
            text = text.replace(char, f'\\{char}')
        
        # Восстанавливаем форматирование
        for marker, formatted in temp_markers.items():
            text = text.replace(marker, formatted)
        
        return text
    
    def _markdown_to_html(self, text: str) -> str:
        """Конвертирует Markdown в HTML для Telegram, защищая уже существующие HTML-теги."""
        # Шаг 1: Защищаем существующие HTML блоки (например, <pre><code>)
        protected_blocks = []
        def save_protected(match):
            protected_blocks.append(match.group(0))
            return f"PROTECTEDBLOCK{len(protected_blocks)-1}PLACEHOLDER"
        
        # Защищаем <pre>...</pre> и любые другие теги, которые мы могли уже вставить
        text = re.sub(r'<(pre|code|b|i|u|s|a|tg-spoiler)[^>]*>[\s\S]*?</\1>', save_protected, text)
        
        # Шаг 2: Экранируем остальной текст (если он еще не экранирован)
        # Если в тексте нет наших заглушек, значит он "чистый" и его надо экранировать
        if "PROTECTEDBLOCK" not in text:
            text = html.escape(text)
        
        # Шаг 3: Сохраняем inline код (он еще не защищен, если он в формате `code`)
        inline_codes = []
        def save_inline_code(match):
            code = match.group(1)
            inline_codes.append(code)
            return f"INLINECODE{len(inline_codes)-1}PLACEHOLDER"
        
        text = re.sub(r'`([^`\n]+?)`', save_inline_code, text)
        
        # Шаг 4: Преобразуем Markdown в HTML
        text = re.sub(r'\*\*([^*\n]+?)\*\*', r'<b>\1</b>', text)
        text = re.sub(r'(?<!\*)\*([^*\n]+?)\*(?!\*)', r'<i>\1</i>', text)
        text = re.sub(r'__([^_\n]+?)__', r'<u>\1</u>', text)
        # Одиночное подчёркивание считается курсивом только на границах слов.
        # Это сохраняет технические имена: Q4_0, Q4_K_M, file_name.
        text = re.sub(r'(?<![\w_])_([^_\n]+?)_(?![\w_])', r'<i>\1</i>', text)
        text = re.sub(r'~~([^~\n]+?)~~', r'<s>\1</s>', text)
        text = re.sub(r'\[([^\]]+?)\]\(([^)]+?)\)', r'<a href="\2">\1</a>', text)
        text = re.sub(r'^#{1,6}\s+(.+)$', r'<b>\1</b>', text, flags=re.MULTILINE)
        text = re.sub(r'^>\s+(.+)$', r'<i>\1</i>', text, flags=re.MULTILINE)
        text = re.sub(r'^[-*+]\s+(.+)$', r'• \1', text, flags=re.MULTILINE)
        
        # Шаг 5: Восстанавливаем inline код
        for i, code in enumerate(inline_codes):
            clean_code = html.escape(code) if code else ""
            text = text.replace(f"INLINECODE{i}PLACEHOLDER", f'<code>{clean_code}</code>')
            
        # Шаг 6: Восстанавливаем защищенные блоки
        for i, block in enumerate(protected_blocks):
            text = text.replace(f"PROTECTEDBLOCK{i}PLACEHOLDER", block)
        
        return text

    def safe_format_for_streaming(
        self,
        text: str,
        *,
        allow_markdown: bool = True,
        allow_html: bool = True,
    ) -> tuple:
        """
        Форматирует текст для отправки во время стриминга (каждый шаг).
        
        В отличие от process_text(), эта функция гарантирует:
        1. Преобразует Markdown → HTML (всегда, для предсказуемости).
        2. Автоматически закрывает любые незакрытые HTML-теги в конце строки.
        3. Никогда не вызовет ошибку 400 Bad Request от Telegram.
        
        Возвращает кортеж (formatted_text, parse_mode).
        Если форматирование не нужно (нет тегов) — возвращает (plain_text, None).
        """
        if not text or not text.strip():
            return text, None

        if not allow_markdown and not allow_html:
            return text, None

        if allow_markdown and not allow_html:
            processed_text, parse_mode = self.process_text(text)
            if parse_mode == 'MarkdownV2':
                return processed_text, parse_mode
            return self.html_to_plain_text(processed_text), None

        if not allow_markdown and allow_html:
            try:
                html_text = self.force_html(text)
                if not re.search(r'<[a-z]', html_text):
                    return text, None
                return self._auto_close_html_tags(html_text), 'HTML'
            except Exception:
                return text, None
        
        # Шаг 1: Конвертируем Markdown → HTML
        # Используем force_html, который также обрабатывает блоки кода
        try:
            html_text = self.force_html(text)
        except Exception:
            # Если конвертация упала — отправляем сырой текст без форматирования
            return text, None
        
        # Шаг 2: Проверяем, появилось ли хоть что-то, что Telegram поймет как HTML
        # Если нет ни одного тега — незачем усложнять, отправляем как plain text
        if not re.search(r'<[a-z]', html_text):
            return text, None
        
        # Шаг 3: Автоматически закрываем все незакрытые теги (по стеку)
        try:
            html_text = self._auto_close_html_tags(html_text)
        except Exception:
            # На крайний случай — plain text без форматирования
            return text, None
        
        return html_text, 'HTML'
    
    def _auto_close_html_tags(self, html_text: str) -> str:
        """
        Анализирует HTML-строку и закрывает все незакрытые теги в конце.
        
        Telegram поддерживает только: b, strong, i, em, u, ins, s, strike,
        del, code, pre, a, tg-spoiler. Только они и отслеживаются.
        """
        # Теги, которые НЕ нужно закрывать (самозакрывающиеся), для HTML они редки
        void_tags = {'br', 'hr', 'img', 'input'}
        
        # Открывающий тег: <tagname ...>
        open_tag_pattern = re.compile(r'<([a-zA-Z][a-zA-Z0-9]*)[^>]*(?<!/)>')
        # Закрывающий тег: </tagname>
        close_tag_pattern = re.compile(r'</([a-zA-Z][a-zA-Z0-9]*)>')
        
        # Строим стек открытых тегов
        stack = []
        pos = 0
        for match in re.finditer(r'</?([a-zA-Z][a-zA-Z0-9]*)[^>]*>', html_text):
            tag_str = match.group(0)
            tag_name = match.group(1).lower()
            
            if tag_name in void_tags:
                continue
            
            if tag_str.startswith('</'):
                # Закрывающий тег: ищем и убираем его пару из стека
                for i in range(len(stack) - 1, -1, -1):
                    if stack[i] == tag_name:
                        stack.pop(i)
                        break
            elif not tag_str.endswith('/>'):
                # Открывающий тег
                if tag_name in self.supported_tags:
                    stack.append(tag_name)
        
        # Закрываем все оставшиеся в стеке открытые теги (в обратном порядке)
        for tag_name in reversed(stack):
            html_text += f'</{tag_name}>'
        
        return html_text


# Глобальный экземпляр
telegram_formatter = TelegramMarkdownRenderer()
