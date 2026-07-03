"""
Кастомный SpinBox с Unicode-стрелочками для решения проблемы с кликами на Windows.
"""

from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSpinBox, QPushButton
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QFont


class UnicodeSpinBox(QWidget):
    """
    Кастомный SpinBox с отдельными кнопками вверх/вниз на основе Unicode-стрелочек.
    Решает проблему некликабельных кнопок в стандартном QSpinBox на Windows.
    """
    
    valueChanged = pyqtSignal(int)
    
    def __init__(
        self,
        parent=None,
        min=0,
        max=100,
        value=0,
        step=1,
        suffix=""
    ):
        super().__init__(parent)
        
        self._min = min
        self._max = max
        self._value = value
        self._step = step
        self._suffix = suffix
        
        self._init_ui()
        self._update_display()
    
    def _init_ui(self):
        from PyQt6.QtWidgets import QVBoxLayout
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        # SpinBox (без кнопок)
        self.spinbox = QSpinBox()
        self.spinbox.setButtonSymbols(QSpinBox.ButtonSymbols.NoButtons)
        self.spinbox.setRange(self._min, self._max)
        self.spinbox.setValue(self._value)
        self.spinbox.valueChanged.connect(self._on_spinbox_changed)
        
        # Контейнер для кнопок (вертикальный)
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(0)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        
        # Кнопка вверх (маленькая)
        self.btn_up = QPushButton("▲")
        self.btn_up.setFixedSize(18, 14)
        self.btn_up.setFont(QFont("Segoe UI Symbol", 7))
        self.btn_up.setAccessibleName("spinbox_up")
        self.btn_up.clicked.connect(self._on_up_clicked)
        
        # Кнопка вниз (маленькая)
        self.btn_down = QPushButton("▼")
        self.btn_down.setFixedSize(18, 14)
        self.btn_down.setFont(QFont("Segoe UI Symbol", 7))
        self.btn_down.setAccessibleName("spinbox_down")
        self.btn_down.clicked.connect(self._on_down_clicked)
        
        buttons_layout.addWidget(self.btn_up)
        buttons_layout.addWidget(self.btn_down)
        
        layout.addWidget(self.spinbox, 1)
        layout.addLayout(buttons_layout)
    
    def _on_up_clicked(self):
        new_value = min(self._max, self._value + self._step)
        if new_value != self._value:
            self._value = new_value
            self._update_display()
            self.valueChanged.emit(self._value)
    
    def _on_down_clicked(self):
        new_value = max(self._min, self._value - self._step)
        if new_value != self._value:
            self._value = new_value
            self._update_display()
            self.valueChanged.emit(self._value)
    
    def _on_spinbox_changed(self, value):
        self._value = value
        self.valueChanged.emit(self._value)
    
    def _update_display(self):
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(self._value)
        self.spinbox.blockSignals(False)
    
    def value(self):
        return self._value
    
    def setValue(self, value):
        self._value = max(self._min, min(self._max, value))
        self._update_display()
        self.valueChanged.emit(self._value)
    
    def setRange(self, min_val, max_val):
        self._min = min_val
        self._max = max_val
        self.spinbox.setRange(min_val, max_val)
        # Корректируем текущее значение если оно выходит за границы
        if self._value < min_val:
            self.setValue(min_val)
        elif self._value > max_val:
            self.setValue(max_val)
    
    def setSuffix(self, suffix):
        self._suffix = suffix
        self.spinbox.setSuffix(suffix)
    
    def setToolTip(self, tooltip):
        self.spinbox.setToolTip(tooltip)
        self.btn_up.setToolTip(tooltip)
        self.btn_down.setToolTip(tooltip)


class UnicodeDoubleSpinBox(QWidget):
    """
    Кастомный DoubleSpinBox с отдельными кнопками вверх/вниз на основе Unicode-стрелочек.
    """
    
    valueChanged = pyqtSignal(float)
    
    def __init__(
        self,
        parent=None,
        min=0.0,
        max=100.0,
        value=0.0,
        step=1.0,
        decimals=2,
        suffix=""
    ):
        super().__init__(parent)
        
        self._min = min
        self._max = max
        self._value = value
        self._step = step
        self._decimals = decimals
        self._suffix = suffix
        
        self._init_ui()
        self._update_display()
    
    def _init_ui(self):
        from PyQt6.QtWidgets import QDoubleSpinBox, QVBoxLayout
        
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        
        # SpinBox (без кнопок)
        self.spinbox = QDoubleSpinBox()
        self.spinbox.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self.spinbox.setRange(self._min, self._max)
        self.spinbox.setValue(self._value)
        self.spinbox.setDecimals(self._decimals)
        self.spinbox.setSingleStep(self._step)
        self.spinbox.valueChanged.connect(self._on_spinbox_changed)
        
        # Контейнер для кнопок (вертикальный)
        buttons_layout = QVBoxLayout()
        buttons_layout.setSpacing(0)
        buttons_layout.setContentsMargins(0, 0, 0, 0)
        
        # Кнопка вверх (маленькая)
        self.btn_up = QPushButton("▲")
        self.btn_up.setFixedSize(18, 14)
        self.btn_up.setFont(QFont("Segoe UI Symbol", 7))
        self.btn_up.setAccessibleName("spinbox_up")
        self.btn_up.clicked.connect(self._on_up_clicked)
        
        # Кнопка вниз (маленькая)
        self.btn_down = QPushButton("▼")
        self.btn_down.setFixedSize(18, 14)
        self.btn_down.setFont(QFont("Segoe UI Symbol", 7))
        self.btn_down.setAccessibleName("spinbox_down")
        self.btn_down.clicked.connect(self._on_down_clicked)
        
        buttons_layout.addWidget(self.btn_up)
        buttons_layout.addWidget(self.btn_down)
        
        layout.addWidget(self.spinbox, 1)
        layout.addLayout(buttons_layout)
    
    def _on_up_clicked(self):
        new_value = min(self._max, self._value + self._step)
        if new_value != self._value:
            self._value = new_value
            self._update_display()
            self.valueChanged.emit(self._value)
    
    def _on_down_clicked(self):
        new_value = max(self._min, self._value - self._step)
        if new_value != self._value:
            self._value = new_value
            self._update_display()
            self.valueChanged.emit(self._value)
    
    def _on_spinbox_changed(self, value):
        self._value = value
        self.valueChanged.emit(self._value)
    
    def _update_display(self):
        self.spinbox.blockSignals(True)
        self.spinbox.setValue(self._value)
        self.spinbox.blockSignals(False)
    
    def value(self):
        return self._value
    
    def setValue(self, value):
        self._value = max(self._min, min(self._max, value))
        self._update_display()
        self.valueChanged.emit(self._value)
    
    def setRange(self, min_val, max_val):
        self._min = min_val
        self._max = max_val
        self.spinbox.setRange(min_val, max_val)
    
    def setSuffix(self, suffix):
        self._suffix = suffix
        self.spinbox.setSuffix(suffix)
    
    def setToolTip(self, tooltip):
        self.spinbox.setToolTip(tooltip)
        self.btn_up.setToolTip(tooltip)
        self.btn_down.setToolTip(tooltip)
