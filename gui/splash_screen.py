"""
Splash Screen для SnapMatch — современный загрузочный экран
с плавающими частицами, брендовым логотипом и градиентным текстом.
"""

from PyQt6.QtWidgets import QSplashScreen, QApplication
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QRadialGradient,
    QLinearGradient, QPen, QFontMetrics, QPainterPath, QBrush
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF
import math
import random
import os

from utils.resource_manager import get_resource_path


class Particle:
    """Плавающая частица для атмосферного фона."""

    __slots__ = ('x', 'y', 'vx', 'vy', 'radius', 'base_alpha',
                 'phase', 'speed', 'color_index')

    def __init__(self, bounds_w: int, bounds_h: int) -> None:
        self.x: float = random.uniform(0, bounds_w)
        self.y: float = random.uniform(0, bounds_h)
        self.vx: float = random.uniform(-0.3, 0.3)
        self.vy: float = random.uniform(-0.2, -0.6)
        self.radius: float = random.uniform(1.2, 3.5)
        self.base_alpha: float = random.uniform(0.15, 0.55)
        self.phase: float = random.uniform(0, math.tau)
        self.speed: float = random.uniform(0.02, 0.05)
        self.color_index: int = random.randint(0, 4)

    def update(self, bounds_w: int, bounds_h: int) -> None:
        """Обновить позицию частицы, перезапускать при выходе за границы."""
        self.x += self.vx
        self.y += self.vy
        self.phase += self.speed

        # Перезапуск снизу при выходе за верхнюю границу
        if self.y < -10:
            self.y = bounds_h + 10
            self.x = random.uniform(0, bounds_w)
        if self.x < -10:
            self.x = bounds_w + 10
        elif self.x > bounds_w + 10:
            self.x = -10

    def current_alpha(self) -> float:
        """Мерцающая прозрачность."""
        return self.base_alpha * (0.5 + 0.5 * math.sin(self.phase))


class SplashScreen(QSplashScreen):
    """Современный загрузочный экран приложения SnapMatch."""

    # Количество плавающих частиц
    PARTICLE_COUNT: int = 45

    # Тайминги фаз (в кадрах при ~60 FPS)
    INTRO_FRAMES: int = 120       # 2 секунды — появление
    DISPLAY_FRAMES: int = 180     # 3 секунды — показ
    OUTRO_FRAMES: int = 80        # ~1.3 секунды — исчезновение

    def __init__(self, app: QApplication) -> None:
        # Временный пустой пиксмап, заменим ниже
        pixmap = QPixmap(1, 1)
        super().__init__(pixmap, flags=(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint
        ))

        self.app = app

        # Размер экрана
        screen = QApplication.primaryScreen().geometry()
        screen_w: int = screen.width()
        screen_h: int = screen.height()

        # Компактный размер сплеш-скрина
        self.splash_w: int = min(620, int(screen_w * 0.4))
        self.splash_h: int = min(400, int(screen_h * 0.33))

        # Финальный пиксмап с прозрачным фоном
        pixmap = QPixmap(self.splash_w, self.splash_h)
        pixmap.fill(Qt.GlobalColor.transparent)
        self.setPixmap(pixmap)

        # ─── Цветовая палитра ────────────────────────────────────
        self.colors: dict[str, QColor] = {
            # Фон
            'bg_deep':      QColor(16,  18,  27),    # #10121B
            'bg_mid':       QColor(25,  27,  42),    # #191B2A
            'bg_edge':      QColor(32,  22,  48),    # #201630

            # Брендовые градиенты
            'snap_start':   QColor(0x18, 0xB4, 0x76), # #18B476
            'snap_end':     QColor(0x00, 0x5D, 0x40), # #005D40
            'match_start':  QColor(0xF5, 0x29, 0x29), # #F52929
            'match_end':    QColor(0x8F, 0x18, 0x18), # #8F1818

            # Акценты для частиц и UI
            'cyan':         QColor(100, 228, 255),    # #64E4FF
            'lavender':     QColor(183, 148, 246),    # #B794F6
            'mint':         QColor(154, 230, 180),    # #9AE6B4

            # Текст
            'text_muted':   QColor(160, 174, 192),    # #A0AEC0

            # Утилитарные
            'border_glow':  QColor(100, 228, 255, 35),
        }

        # Цвета частиц — брендовые оттенки
        self._particle_colors: list[QColor] = [
            self.colors['snap_start'],                     # Яркий зелёный
            self.colors['snap_end'],                       # Тёмный зелёный
            self.colors['match_start'],                    # Яркий красный
            QColor(0x3D, 0xD6, 0x8B),                     # Светло-зелёный (промежуточный)
            QColor(0xFF, 0x6B, 0x6B),                      # Светло-красный (промежуточный)
        ]

        # ─── Загрузка ресурсов ───────────────────────────────────
        # В exe ресурсы лежат в _MEIPASS — используем get_resource_path
        icon_path = get_resource_path("assets/icon3.png") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon3.png"
        )

        self._logo_target_size: int = 120  # Целевой размер иконки в пикселях
        self.logo_pixmap = QPixmap()
        if icon_path and os.path.exists(icon_path):
            original = QPixmap(icon_path)
            if not original.isNull():
                # Предварительно масштабируем с качественной интерполяцией —
                # это убирает «лесенки», т.к. Qt использует билинейный фильтр,
                # а не ближайший сосед как при p.scale().
                self.logo_pixmap = original.scaled(
                    self._logo_target_size,
                    self._logo_target_size,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )

        self.has_custom_logo = not self.logo_pixmap.isNull()

        # ─── Состояние анимации ──────────────────────────────────
        self.frame: int = 0
        self.opacity: float = 0.0

        # Логотип
        self.logo_scale: float = 0.0
        self.logo_opacity: float = 0.0
        self.logo_y_offset: float = 20.0
        self.logo_glow_phase: float = 0.0

        # Текст
        self.title_opacity: float = 0.0
        self.subtitle_opacity: float = 0.0

        # Прогресс
        self.progress: float = 0.0
        self.progress_opacity: float = 0.0
        self.progress_glow: float = 0.0

        # Версия
        self.version_opacity: float = 0.0

        # Частицы
        self.particles_opacity: float = 0.0
        self.particles: list[Particle] = [
            Particle(self.splash_w, self.splash_h)
            for _ in range(self.PARTICLE_COUNT)
        ]

        # ─── Позиционирование ────────────────────────────────────
        self.move(
            (screen_w - self.splash_w) // 2,
            (screen_h - self.splash_h) // 2,
        )

        # Таймер анимации (~60 FPS)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ──────────────────────────────────────────────────────────────
    #  Easing-функции
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _ease_out_quart(t: float) -> float:
        """Мягкое замедление."""
        return 1.0 - pow(1.0 - t, 4)

    @staticmethod
    def _ease_out_cubic(t: float) -> float:
        """Кубическое замедление."""
        return 1.0 - pow(1.0 - t, 3)

    @staticmethod
    def _ease_in_out_sine(t: float) -> float:
        """Синусоидальная S-кривая."""
        return -(math.cos(math.pi * t) - 1.0) / 2.0

    @staticmethod
    def _ease_out_back(t: float) -> float:
        """Лёгкий «отскок» — элемент чуть проскакивает и возвращается."""
        c1 = 1.4
        c3 = c1 + 1.0
        return 1.0 + c3 * pow(t - 1.0, 3) + c1 * pow(t - 1.0, 2)

    # ──────────────────────────────────────────────────────────────
    #  Утилиты рисования
    # ──────────────────────────────────────────────────────────────

    @staticmethod
    def _color_with_alpha(color: QColor, alpha: float) -> QColor:
        """Создать копию цвета с заданной прозрачностью (0.0–1.0)."""
        c = QColor(color)
        c.setAlpha(max(0, min(255, int(alpha * 255))))
        return c

    # ──────────────────────────────────────────────────────────────
    #  Рисование
    # ──────────────────────────────────────────────────────────────

    def drawContents(self, painter: QPainter) -> None:
        """Основная отрисовка сплеш-скрина."""
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)

        w, h = self.width(), self.height()
        cx, cy = w // 2, h // 2

        painter.setOpacity(self.opacity)

        # --- Фон ---
        self._draw_background(painter, w, h, cx, cy)

        # --- Тонкая светящаяся рамка ---
        self._draw_border(painter, w, h)

        # --- Частицы ---
        if self.particles_opacity > 0.01:
            self._draw_particles(painter)

        # --- Логотип ---
        if self.logo_opacity > 0.01:
            if self.has_custom_logo:
                self._draw_image_logo(painter, cx, cy)
            else:
                self._draw_fallback_logo(painter, cx, cy)

        # --- Название ---
        if self.title_opacity > 0.01:
            self._draw_title(painter, cx, h)

        # --- Подзаголовок ---
        if self.subtitle_opacity > 0.01:
            self._draw_subtitle(painter, cx, h)

        # --- Прогресс-бар ---
        if self.progress_opacity > 0.01:
            self._draw_progress(painter, w, h)

        # --- Версия ---
        if self.version_opacity > 0.01:
            self._draw_version(painter, cx, h)

        painter.restore()

    def _draw_background(self, p: QPainter, w: int, h: int, cx: int, cy: int) -> None:
        """Тёмный фон с радиальным градиентом."""
        bg = QRadialGradient(cx, cy - 40, max(w, h) * 0.8)
        bg.setColorAt(0.0, self.colors['bg_deep'])
        bg.setColorAt(0.6, self.colors['bg_mid'])
        bg.setColorAt(1.0, self.colors['bg_edge'])

        p.setBrush(bg)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 0, w, h, 18, 18)

    def _draw_border(self, p: QPainter, w: int, h: int) -> None:
        """Тонкая светящаяся рамка по краю окна."""
        border_color = self._color_with_alpha(self.colors['snap_start'], 0.08 + 0.04 * math.sin(self.logo_glow_phase))
        pen = QPen(border_color, 1.0)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(1, 1, w - 2, h - 2, 17, 17)

    def _draw_particles(self, p: QPainter) -> None:
        """Отрисовка плавающих частиц."""
        p.save()
        p.setPen(Qt.PenStyle.NoPen)

        for particle in self.particles:
            alpha = particle.current_alpha() * self.particles_opacity * self.opacity
            if alpha < 0.01:
                continue

            color = self._color_with_alpha(
                self._particle_colors[particle.color_index],
                alpha,
            )
            p.setBrush(color)
            r = particle.radius
            p.drawEllipse(QPointF(particle.x, particle.y), r, r)

        p.restore()

    def _draw_image_logo(self, p: QPainter, cx: int, cy: int) -> None:
        """Отрисовка PNG логотипа (icon3.png) — предварительно сглаженного."""
        p.save()

        # Позиция (поднимаем выше, чтобы не налезало на текст)
        logo_y = cy - 75 + int(self.logo_y_offset)
        p.translate(cx, logo_y)
        p.setOpacity(self.opacity * self.logo_opacity)

        # 1. Свечение позади иконки
        glow_intensity = 0.15 + 0.08 * math.sin(self.logo_glow_phase)
        glow_r = 90
        glow = QRadialGradient(0, 0, glow_r)
        glow.setColorAt(0.0, self._color_with_alpha(self.colors['snap_start'], glow_intensity))
        glow.setColorAt(0.5, self._color_with_alpha(self.colors['match_start'], glow_intensity * 0.3))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(-glow_r, -glow_r, glow_r * 2, glow_r * 2)

        # 2. Иконка (уже отмасштабирована с SmoothTransformation в __init__)
        #    Применяем только анимационный масштаб через scale для ease_out_back.
        #    Базовый размер = 1.0, поэтому лесенок не будет.
        anim_scale = self.logo_scale
        p.scale(anim_scale, anim_scale)

        iw = self.logo_pixmap.width()
        ih = self.logo_pixmap.height()
        p.drawPixmap(-iw // 2, -ih // 2, self.logo_pixmap)

        p.restore()

    def _draw_fallback_logo(self, p: QPainter, cx: int, cy: int) -> None:
        """Геометрический логотип (если иконка не найдена)."""
        p.save()
        logo_y = cy - 40 + int(self.logo_y_offset)
        p.translate(cx, logo_y)
        scale = self.logo_scale
        p.scale(scale, scale)
        p.setOpacity(self.opacity * self.logo_opacity)

        base_r = 38
        
        # Свечение
        glow_intensity = 0.12 + 0.06 * math.sin(self.logo_glow_phase)
        glow_r = int(base_r * 2.2)
        glow = QRadialGradient(0, 0, glow_r)
        glow.setColorAt(0.0, self._color_with_alpha(self.colors['cyan'], glow_intensity))
        glow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(-glow_r, -glow_r, glow_r * 2, glow_r * 2)

        # Круг
        circle_grad = QLinearGradient(-base_r, -base_r, base_r, base_r)
        circle_grad.setColorAt(0.0, self.colors['snap_start'])
        circle_grad.setColorAt(1.0, self.colors['match_end'])
        p.setBrush(circle_grad)
        p.drawEllipse(-base_r, -base_r, base_r * 2, base_r * 2)

        # Буква S
        s_font = QFont("Segoe UI", 38, QFont.Weight.Bold)
        p.setFont(s_font)
        fm = QFontMetrics(s_font)
        text = "S"
        tw = fm.horizontalAdvance(text)
        th = fm.ascent()
        p.setPen(self._color_with_alpha(self.colors['bg_deep'], 0.9))
        p.drawText(-tw // 2, th // 2 - 2, text)

        p.restore()

    def _draw_title(self, p: QPainter, cx: int, h: int) -> None:
        """Название приложения с градиентной заливкой текста."""
        p.save()
        p.setOpacity(self.opacity * self.title_opacity)

        font = QFont("Segoe UI", 32, QFont.Weight.Bold) # Чуть жирнее для градиента
        p.setFont(font)
        fm = QFontMetrics(font)

        part1 = "Snap"
        part2 = "Match"

        w1 = fm.horizontalAdvance(part1)
        w2 = fm.horizontalAdvance(part2)
        total_w = w1 + w2
        
        h_text = fm.height()
        ascent = fm.ascent()

        title_y = h // 2 + 35
        start_x = cx - total_w // 2

        # ─── Рисуем "Snap" с градиентом ───
        path1 = QPainterPath()
        # addText принимает baseline y, поэтому title_y должен быть baseline
        # Но мы обычно центрируем. Давайте считать title_y как baseline.
        path1.addText(start_x, title_y, font, part1)
        
        # Градиент для Snap: #18B476 -> #005D40
        grad1 = QLinearGradient(start_x, title_y - ascent, start_x + w1, title_y)
        grad1.setColorAt(0.0, self.colors['snap_start'])
        grad1.setColorAt(1.0, self.colors['snap_end'])
        
        p.setBrush(QBrush(grad1))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path1)

        # ─── Рисуем "Match" с градиентом ───
        path2 = QPainterPath()
        path2.addText(start_x + w1, title_y, font, part2)
        
        # Градиент для Match: #F52929 -> #8F1818
        grad2 = QLinearGradient(start_x + w1, title_y - ascent, start_x + total_w, title_y)
        grad2.setColorAt(0.0, self.colors['match_start'])
        grad2.setColorAt(1.0, self.colors['match_end'])
        
        p.setBrush(QBrush(grad2))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawPath(path2)

        p.restore()

    def _draw_subtitle(self, p: QPainter, cx: int, h: int) -> None:
        """Подзаголовок под названием."""
        p.save()
        p.setOpacity(self.opacity * self.subtitle_opacity)

        font = QFont("Segoe UI", 12, QFont.Weight.Normal)
        p.setFont(font)
        fm = QFontMetrics(font)

        text = "AI Assistant"
        tw = fm.horizontalAdvance(text)
        sub_y = h // 2 + 65

        p.setPen(self._color_with_alpha(self.colors['text_muted'], self.subtitle_opacity))
        p.drawText(cx - tw // 2, sub_y, text)

        p.restore()

    def _draw_progress(self, p: QPainter, w: int, h: int) -> None:
        """Минималистичный прогресс-бар."""
        p.save()
        p.setOpacity(self.opacity * self.progress_opacity)

        bar_w = w - 120
        bar_h = 3
        bar_x = 60
        bar_y = h - 52

        # Трек
        track_color = self._color_with_alpha(self.colors['text_muted'], 0.12)
        p.setBrush(track_color)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(bar_x, bar_y, bar_w, bar_h, 1.5, 1.5)

        # Заполнение
        if self.progress > 0.0:
            fill_w = int(bar_w * min(self.progress, 1.0))

            # Градиент заполнения (используем цвета бренда)
            fill_grad = QLinearGradient(bar_x, 0, bar_x + fill_w, 0)
            fill_grad.setColorAt(0.0, self.colors['snap_start'])
            fill_grad.setColorAt(1.0, self.colors['match_start'])

            p.setBrush(fill_grad)
            p.drawRoundedRect(bar_x, bar_y, fill_w, bar_h, 1.5, 1.5)

            # Свечение
            glow_alpha = 0.3 + 0.2 * math.sin(self.progress_glow)
            glow_color = self._color_with_alpha(self.colors['snap_start'], glow_alpha)
            glow_r = 6
            glow_grad = QRadialGradient(bar_x + fill_w, bar_y + bar_h / 2, glow_r)
            glow_grad.setColorAt(0.0, glow_color)
            glow_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            p.setBrush(glow_grad)
            p.drawEllipse(
                int(bar_x + fill_w - glow_r),
                int(bar_y + bar_h / 2 - glow_r),
                glow_r * 2,
                glow_r * 2,
            )

        p.restore()

    def _draw_version(self, p: QPainter, cx: int, h: int) -> None:
        """Мелкий текст версии внизу."""
        p.save()
        p.setOpacity(self.opacity * self.version_opacity)

        font = QFont("Segoe UI", 9, QFont.Weight.Normal)
        p.setFont(font)
        fm = QFontMetrics(font)

        text = "v1.0.4.0"
        tw = fm.horizontalAdvance(text)
        p.setPen(self._color_with_alpha(self.colors['text_muted'], 0.4 * self.version_opacity))
        p.drawText(cx - tw // 2, h - 18, text)

        p.restore()

    # ──────────────────────────────────────────────────────────────
    #  Анимация
    # ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        """Один кадр анимации."""
        self.frame += 1

        total = self.INTRO_FRAMES + self.DISPLAY_FRAMES + self.OUTRO_FRAMES

        # Обновляем частицы каждый кадр
        for particle in self.particles:
            particle.update(self.splash_w, self.splash_h)

        # --- Фаза появления ---
        if self.frame <= self.INTRO_FRAMES:
            self._animate_intro(self.frame / self.INTRO_FRAMES)

        # --- Фаза показа ---
        elif self.frame <= self.INTRO_FRAMES + self.DISPLAY_FRAMES:
            display_t = (self.frame - self.INTRO_FRAMES) / self.DISPLAY_FRAMES
            self._animate_display(display_t)

        # --- Фаза исчезновения ---
        elif self.frame <= total:
            fade_t = (self.frame - self.INTRO_FRAMES - self.DISPLAY_FRAMES) / self.OUTRO_FRAMES
            self._animate_outro(fade_t)

        else:
            self._timer.stop()
            self.hide()
            return

        # Глобальная фаза свечения
        self.logo_glow_phase += 0.04

        self.update()

    def _animate_intro(self, t: float) -> None:
        """Волновое появление элементов."""
        self.opacity = self._ease_out_quart(t)

        if t > 0.05:
            pt = (t - 0.05) / 0.95
            self.particles_opacity = self._ease_out_cubic(pt) * 0.8

        if t > 0.15:
            lt = min(1.0, (t - 0.15) / 0.55)
            self.logo_scale = self._ease_out_back(lt)
            self.logo_opacity = self._ease_out_quart(lt)
            self.logo_y_offset = 20.0 * (1.0 - self._ease_out_quart(lt))

        if t > 0.45:
            tt = (t - 0.45) / 0.35
            self.title_opacity = self._ease_out_quart(tt)

        if t > 0.6:
            st = (t - 0.6) / 0.25
            self.subtitle_opacity = self._ease_out_quart(st)

        if t > 0.75:
            pt = (t - 0.75) / 0.25
            self.progress_opacity = self._ease_out_cubic(pt)

        if t > 0.85:
            vt = (t - 0.85) / 0.15
            self.version_opacity = self._ease_out_cubic(vt)

    def _animate_display(self, t: float) -> None:
        """Стабильный показ."""
        self.opacity = 1.0
        self.logo_scale = 1.0
        self.logo_opacity = 1.0
        self.logo_y_offset = 0.0
        self.title_opacity = 1.0
        self.subtitle_opacity = 1.0
        self.progress_opacity = 1.0
        self.version_opacity = 1.0
        self.particles_opacity = 0.8

        self.progress = min(1.0, t * 1.3)
        self.progress_glow = t * 6.0 * math.pi

    def _animate_outro(self, t: float) -> None:
        """Мягкое исчезновение."""
        fade = 1.0 - self._ease_in_out_sine(t)

        self.opacity = fade
        self.logo_opacity = fade
        self.title_opacity = fade
        self.subtitle_opacity = fade
        self.progress_opacity = fade
        self.version_opacity = fade
        self.particles_opacity = fade * 0.8

        self.logo_scale = 1.0 + t * 0.15
        self.logo_y_offset = -t * 8.0
