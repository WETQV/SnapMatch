"""
Splash Screen для SnapMatch — современный загрузочный экран.

Тёмная «стеклянная» карточка с мягкой тенью, дрейфующим свечением (aurora),
логотипом с вращающимся кольцом, реальным статусом загрузки и прогресс-баром.

Использование:
    splash = SplashScreen(app)
    splash.show()
    splash.set_status("Загрузка настроек…", 0.2)
    ...
    splash.finish_and_wait()   # плавно скрыть (не раньше MIN_DISPLAY_MS)

Анимация завязана на реальное время (QElapsedTimer), а не на число кадров,
поэтому скорость одинакова на слабых и быстрых машинах.
"""

from PyQt6.QtWidgets import QSplashScreen, QApplication
from PyQt6.QtGui import (
    QPixmap, QPainter, QColor, QFont, QRadialGradient, QConicalGradient,
    QLinearGradient, QPen, QFontMetrics, QPainterPath, QBrush, QImage
)
from PyQt6.QtCore import Qt, QTimer, QPointF, QRectF, QElapsedTimer, QEventLoop, pyqtSignal
import math
import os

from utils.resource_manager import get_resource_path

# Версия показывается внизу; держим в синхроне с version_info.txt / installer_info.txt
APP_VERSION = "1.0.4.4"

_FONT_FAMILIES = ["Inter", "Segoe UI", "Noto Sans", "Ubuntu", "Sans Serif"]


def _font(size: float, weight: QFont.Weight = QFont.Weight.Normal, spacing: float = 0.0) -> QFont:
    f = QFont()
    f.setFamilies(_FONT_FAMILIES)
    f.setPointSizeF(size)
    f.setWeight(weight)
    if spacing:
        f.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, spacing)
    return f


def _alpha(color: QColor, a: float) -> QColor:
    c = QColor(color)
    c.setAlphaF(max(0.0, min(1.0, a)))
    return c


def _ease_out_cubic(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 3


def _ease_out_back(t: float) -> float:
    t = max(0.0, min(1.0, t))
    c1 = 1.2
    return 1.0 + (c1 + 1.0) * (t - 1.0) ** 3 + c1 * (t - 1.0) ** 2


class SplashScreen(QSplashScreen):
    """Современный загрузочный экран приложения SnapMatch."""

    finished = pyqtSignal()

    # Размер карточки и отступ под тень
    CARD_W: int = 520
    CARD_H: int = 320
    SHADOW: int = 36
    RADIUS: int = 22

    INTRO_MS: int = 650
    OUTRO_MS: int = 380
    MIN_DISPLAY_MS: int = 1300   # не гасим раньше — иначе экран «мигнёт»

    def __init__(self, app: QApplication) -> None:
        pixmap = QPixmap(1, 1)
        super().__init__(pixmap, flags=(
            Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
        ))
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.app = app

        self.total_w = self.CARD_W + self.SHADOW * 2
        self.total_h = self.CARD_H + self.SHADOW * 2
        canvas = QPixmap(self.total_w, self.total_h)
        canvas.fill(Qt.GlobalColor.transparent)
        self.setPixmap(canvas)

        # ─── Палитра ─────────────────────────────────────────────
        self.c_bg_top = QColor(20, 23, 34)
        self.c_bg_bottom = QColor(11, 12, 19)
        self.c_green = QColor(0x18, 0xB4, 0x76)
        self.c_green_dark = QColor(0x00, 0x5D, 0x40)
        self.c_red = QColor(0xF5, 0x29, 0x29)
        self.c_red_dark = QColor(0x8F, 0x18, 0x18)
        self.c_violet = QColor(124, 92, 255)
        self.c_text = QColor(236, 240, 248)
        self.c_muted = QColor(139, 150, 171)

        # ─── Логотип ─────────────────────────────────────────────
        self._logo_size = 84
        self.logo_pixmap = QPixmap()
        icon_path = get_resource_path("assets/icon3.png") or os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "icon3.png"
        )
        if icon_path and os.path.exists(icon_path):
            original = QPixmap(icon_path)
            if not original.isNull():
                # С запасом по DPI, чтобы не было «лесенок»
                dpr = max(1.0, self.devicePixelRatioF())
                side = int(self._logo_size * dpr)
                self.logo_pixmap = original.scaled(
                    side, side, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
                self.logo_pixmap.setDevicePixelRatio(dpr)

        # ─── Статичный слой (тень + карточка + рамка) рисуем один раз ─
        self._static = self._build_static_layer()

        # ─── Состояние ───────────────────────────────────────────
        self._status = "Запуск…"
        self._progress_target = 0.0   # куда стремимся (0..1)
        self._progress_shown = 0.0    # что показываем (плавно догоняет)
        self._closing = False
        self._closed_emitted = False
        self._out_started_ms = 0
        self._status_changed_ms = -1000

        self._clock = QElapsedTimer()
        self._clock.start()

        screen = QApplication.primaryScreen().geometry()
        self.move(
            screen.x() + (screen.width() - self.total_w) // 2,
            screen.y() + (screen.height() - self.total_h) // 2,
        )

        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)

    # ──────────────────────────────────────────────────────────────
    #  Публичный API
    # ──────────────────────────────────────────────────────────────

    def set_status(self, text: str, progress: float | None = None) -> None:
        """Обновить подпись и (опционально) целевой прогресс 0..1."""
        if text and text != self._status:
            self._status = text
            self._status_changed_ms = self._clock.elapsed()
        if progress is not None:
            self._progress_target = max(self._progress_target, min(1.0, progress))
        self.update()

    def finish_and_wait(self) -> None:
        """Довести прогресс до 100%, плавно скрыть сплеш и дождаться закрытия."""
        self._progress_target = 1.0
        if not self._closing:
            self._closing = True
            # Не раньше MIN_DISPLAY_MS от старта, чтобы экран успел прочитаться
            self._out_started_ms = max(self._clock.elapsed(), self.MIN_DISPLAY_MS)
        if self._closed_emitted:
            return
        loop = QEventLoop()
        self.finished.connect(loop.quit)
        loop.exec()

    # ──────────────────────────────────────────────────────────────
    #  Статичный слой
    # ──────────────────────────────────────────────────────────────

    def _card_rect(self) -> QRectF:
        return QRectF(self.SHADOW, self.SHADOW, self.CARD_W, self.CARD_H)

    def _build_static_layer(self) -> QPixmap:
        dpr = max(1.0, self.devicePixelRatioF())
        img = QImage(int(self.total_w * dpr), int(self.total_h * dpr),
                     QImage.Format.Format_ARGB32_Premultiplied)
        img.setDevicePixelRatio(dpr)
        img.fill(Qt.GlobalColor.transparent)

        p = QPainter(img)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = self._card_rect()

        # Мягкая тень: несколько слоёв с убывающей прозрачностью
        p.setPen(Qt.PenStyle.NoPen)
        steps = 14
        for i in range(steps, 0, -1):
            grow = i * (self.SHADOW / steps)
            a = 0.30 * (1.0 - i / (steps + 1)) ** 2 / 2.2
            p.setBrush(QColor(0, 0, 0, int(a * 255)))
            r = card.adjusted(-grow, -grow + 10, grow, grow + 10)
            p.drawRoundedRect(r, self.RADIUS + grow, self.RADIUS + grow)

        # Карточка
        bg = QLinearGradient(card.topLeft(), card.bottomLeft())
        bg.setColorAt(0.0, self.c_bg_top)
        bg.setColorAt(1.0, self.c_bg_bottom)
        p.setBrush(bg)
        p.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Верхний блик «стекла»
        hl = QLinearGradient(card.topLeft(), QPointF(card.left(), card.top() + 90))
        hl.setColorAt(0.0, QColor(255, 255, 255, 14))
        hl.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.setBrush(hl)
        p.drawRoundedRect(card, self.RADIUS, self.RADIUS)

        # Тонкая градиентная рамка
        border = QLinearGradient(card.topLeft(), card.bottomRight())
        border.setColorAt(0.0, _alpha(self.c_green, 0.45))
        border.setColorAt(0.5, QColor(255, 255, 255, 18))
        border.setColorAt(1.0, _alpha(self.c_red, 0.40))
        p.setPen(QPen(QBrush(border), 1.0))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(card.adjusted(0.5, 0.5, -0.5, -0.5), self.RADIUS, self.RADIUS)
        p.end()

        return QPixmap.fromImage(img)

    # ──────────────────────────────────────────────────────────────
    #  Рисование
    # ──────────────────────────────────────────────────────────────

    def drawContents(self, painter: QPainter) -> None:
        t_ms = self._clock.elapsed()
        intro = _ease_out_cubic(t_ms / self.INTRO_MS)

        if self._closing:
            out = (t_ms - self._out_started_ms) / self.OUTRO_MS
            master = 1.0 - _ease_out_cubic(out)
        else:
            master = intro
        master = max(0.0, min(1.0, master))

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.setOpacity(master)

        painter.drawPixmap(0, 0, self._static)

        card = self._card_rect()
        # Лёгкий «подъём» при появлении/уходе
        lift = (1.0 - master) * 10.0
        painter.translate(0, lift)

        # Свечение — внутри скруглённой карточки
        clip = QPainterPath()
        clip.addRoundedRect(card, self.RADIUS, self.RADIUS)
        painter.setClipPath(clip)
        self._draw_aurora(painter, card, t_ms)
        painter.setClipping(False)

        cx = card.center().x()
        self._draw_logo(painter, cx, card.top() + 92, t_ms)
        self._draw_title(painter, cx, card.top() + 182, intro)
        self._draw_subtitle(painter, cx, card.top() + 206, intro)
        self._draw_progress(painter, card, t_ms)
        self._draw_version(painter, card)

        painter.restore()

    def _draw_aurora(self, p: QPainter, card: QRectF, t_ms: int) -> None:
        """Три медленно дрейфующих цветных пятна — мягкий живой фон."""
        t = t_ms / 1000.0
        blobs = (
            (self.c_green,  0.30 + 0.12 * math.sin(t * 0.7),  0.28 + 0.10 * math.cos(t * 0.5), 0.55, 0.20),
            (self.c_red,    0.74 + 0.10 * math.cos(t * 0.6),  0.72 + 0.12 * math.sin(t * 0.8), 0.50, 0.15),
            (self.c_violet, 0.62 + 0.14 * math.sin(t * 0.4),  0.20 + 0.08 * math.cos(t * 0.9), 0.42, 0.13),
        )
        p.setPen(Qt.PenStyle.NoPen)
        for color, fx, fy, fr, fa in blobs:
            x = card.left() + card.width() * fx
            y = card.top() + card.height() * fy
            g = QRadialGradient(x, y, card.width() * fr)
            g.setColorAt(0.0, _alpha(color, fa))
            g.setColorAt(1.0, _alpha(color, 0.0))
            p.setBrush(g)
            p.drawRect(card)

    def _draw_logo(self, p: QPainter, cx: float, cy: float, t_ms: int) -> None:
        p.save()
        p.translate(cx, cy)

        pop = _ease_out_back((t_ms - 120) / 600.0)
        p.scale(pop, pop)
        t = t_ms / 1000.0

        # Мягкое «дыхание» свечения под иконкой
        pulse = 0.5 + 0.5 * math.sin(t * 2.2)
        glow = QRadialGradient(0, 0, 78)
        glow.setColorAt(0.0, _alpha(self.c_green, 0.26 + 0.10 * pulse))
        glow.setColorAt(0.55, _alpha(self.c_red, 0.07 + 0.04 * pulse))
        glow.setColorAt(1.0, _alpha(self.c_green, 0.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QPointF(0, 0), 78, 78)

        # Тонкий статичный трек кольца
        ring_r = self._logo_size / 2 + 14
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 14), 1.0))
        p.drawEllipse(QPointF(0, 0), ring_r, ring_r)

        # Дуга-спиннер с градиентом зелёный → красный
        angle = (t * 220.0) % 360.0
        cg = QConicalGradient(0, 0, -angle)
        cg.setColorAt(0.00, _alpha(self.c_green, 0.0))
        cg.setColorAt(0.55, _alpha(self.c_green, 0.9))
        cg.setColorAt(0.80, _alpha(self.c_red, 0.95))
        cg.setColorAt(1.00, _alpha(self.c_red, 0.0))
        pen = QPen(QBrush(cg), 2.6)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.drawEllipse(QPointF(0, 0), ring_r, ring_r)

        # Иконка
        if not self.logo_pixmap.isNull():
            dpr = self.logo_pixmap.devicePixelRatio()
            iw = self.logo_pixmap.width() / dpr
            ih = self.logo_pixmap.height() / dpr
            p.drawPixmap(QPointF(-iw / 2, -ih / 2), self.logo_pixmap)
        else:
            self._draw_fallback_logo(p)
        p.restore()

    def _draw_fallback_logo(self, p: QPainter) -> None:
        """Геометрический логотип, если icon3.png не найден."""
        r = self._logo_size / 2 - 4
        g = QLinearGradient(-r, -r, r, r)
        g.setColorAt(0.0, self.c_green)
        g.setColorAt(1.0, self.c_red_dark)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(0, 0), r, r)
        p.setFont(_font(34, QFont.Weight.Bold))
        p.setPen(_alpha(self.c_bg_bottom, 0.9))
        p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignmentFlag.AlignCenter, "S")

    def _draw_title(self, p: QPainter, cx: float, baseline: float, intro: float) -> None:
        a = _ease_out_cubic((intro - 0.35) / 0.65)
        if a <= 0.01:
            return
        p.save()
        p.setOpacity(p.opacity() * a)
        p.translate(0, (1.0 - a) * 8.0)

        font = _font(30, QFont.Weight.Bold, spacing=0.4)
        fm = QFontMetrics(font)
        w1 = fm.horizontalAdvance("Snap")
        w2 = fm.horizontalAdvance("Match")
        x = cx - (w1 + w2) / 2
        asc = fm.ascent()

        for text, x0, w, c0, c1 in (
            ("Snap", x, w1, self.c_green, self.c_green_dark),
            ("Match", x + w1, w2, self.c_red, self.c_red_dark),
        ):
            path = QPainterPath()
            path.addText(x0, baseline, font, text)
            g = QLinearGradient(x0, baseline - asc, x0 + w, baseline)
            g.setColorAt(0.0, c0)
            g.setColorAt(1.0, c1)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(g)
            p.drawPath(path)
        p.restore()

    def _draw_subtitle(self, p: QPainter, cx: float, baseline: float, intro: float) -> None:
        a = _ease_out_cubic((intro - 0.55) / 0.45)
        if a <= 0.01:
            return
        p.save()
        p.setOpacity(p.opacity() * a)
        font = _font(9.5, QFont.Weight.Medium, spacing=3.2)
        p.setFont(font)
        text = "AI ASSISTANT"
        tw = QFontMetrics(font).horizontalAdvance(text)
        p.setPen(self.c_muted)
        p.drawText(QPointF(cx - tw / 2, baseline), text)
        p.restore()

    def _draw_progress(self, p: QPainter, card: QRectF, t_ms: int) -> None:
        a = _ease_out_cubic((t_ms - 450) / 450.0)
        if a <= 0.01:
            return
        p.save()
        p.setOpacity(p.opacity() * a)

        margin = 44
        bar_x = card.left() + margin
        bar_w = card.width() - margin * 2
        bar_h = 4.0
        bar_y = card.bottom() - 62

        # Статус слева, процент справа
        status_font = _font(9.5)
        p.setFont(status_font)
        fm = QFontMetrics(status_font)
        fade = _ease_out_cubic((t_ms - self._status_changed_ms) / 220.0)
        p.setPen(_alpha(self.c_muted, 0.4 + 0.6 * fade))
        text = fm.elidedText(self._status, Qt.TextElideMode.ElideRight, int(bar_w - 50))
        p.drawText(QPointF(bar_x, bar_y - 12 + (1.0 - fade) * 4.0), text)

        pct = f"{int(self._progress_shown * 100)}%"
        p.setPen(_alpha(self.c_text, 0.75))
        p.drawText(QPointF(bar_x + bar_w - fm.horizontalAdvance(pct), bar_y - 12), pct)

        # Трек
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(255, 255, 255, 18))
        p.drawRoundedRect(QRectF(bar_x, bar_y, bar_w, bar_h), 2, 2)

        # Заполнение
        fill_w = bar_w * self._progress_shown
        if fill_w > 1.0:
            fill = QRectF(bar_x, bar_y, fill_w, bar_h)
            g = QLinearGradient(bar_x, 0, bar_x + bar_w, 0)
            g.setColorAt(0.0, self.c_green)
            g.setColorAt(1.0, self.c_red)
            p.setBrush(g)
            p.drawRoundedRect(fill, 2, 2)

            # Бегущий блик по заполненной части
            sheen_x = bar_x + ((t_ms / 900.0) % 1.0) * (fill_w + 60) - 30
            sg = QLinearGradient(sheen_x - 30, 0, sheen_x + 30, 0)
            sg.setColorAt(0.0, QColor(255, 255, 255, 0))
            sg.setColorAt(0.5, QColor(255, 255, 255, 90))
            sg.setColorAt(1.0, QColor(255, 255, 255, 0))
            clip = QPainterPath()
            clip.addRoundedRect(fill, 2, 2)
            p.setClipPath(clip)
            p.setBrush(sg)
            p.drawRect(fill)
        p.restore()

    def _draw_version(self, p: QPainter, card: QRectF) -> None:
        p.save()
        font = _font(8.5)
        p.setFont(font)
        text = f"v{APP_VERSION}"
        tw = QFontMetrics(font).horizontalAdvance(text)
        p.setPen(_alpha(self.c_muted, 0.55))
        p.drawText(QPointF(card.center().x() - tw / 2, card.bottom() - 18), text)
        p.restore()

    # ──────────────────────────────────────────────────────────────
    #  Анимация
    # ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        t_ms = self._clock.elapsed()

        # Прогресс плавно догоняет цель; пока новых статусов нет — медленно ползёт
        # вперёд (не дальше 92%), чтобы экран не казался зависшим. 100% — только по факту.
        target = self._progress_target
        if not self._closing:
            target = max(target, min(0.92, self._progress_shown + 0.004))
        delta = target - self._progress_shown
        if delta > 0:
            self._progress_shown += delta * 0.12
        if self._progress_target >= 1.0 and self._progress_shown > 0.995:
            self._progress_shown = 1.0

        if self._closing and t_ms - self._out_started_ms >= self.OUTRO_MS:
            self._timer.stop()
            self.hide()
            if not self._closed_emitted:
                self._closed_emitted = True
                self.finished.emit()
            return

        self.update()
