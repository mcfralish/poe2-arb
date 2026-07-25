"""Settings dialog: edits the Config fields that matter day-to-day."""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from ..config import Config


class SettingsDialog(QDialog):
    def __init__(self, cfg: Config, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self._cfg = cfg

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.league = QLineEdit(cfg.league or "")
        self.league.setPlaceholderText("blank = auto-detect current league")
        form.addRow("League", self.league)

        self.threshold = self._dspin(cfg.profit_threshold_pct, 0.0, 100.0, 0.5, "%")
        form.addRow("Profit threshold", self.threshold)

        self.fee = self._dspin(cfg.fee_pct, 0.0, 20.0, 0.1, "%")
        form.addRow("Fee haircut per hop", self.fee)

        self.interval = QSpinBox()
        self.interval.setRange(5, 240)
        self.interval.setSuffix(" min")
        self.interval.setValue(cfg.watch_interval_minutes)
        form.addRow("Watch interval", self.interval)

        self.max_currencies = QSpinBox()
        self.max_currencies.setRange(3, 20)
        self.max_currencies.setValue(cfg.max_currencies)
        form.addRow("Currencies in graph (top-N by volume)", self.max_currencies)

        self.max_cycle_len = QComboBox()
        self.max_cycle_len.addItems(["3", "4"])
        self.max_cycle_len.setCurrentText(str(cfg.max_cycle_len))
        form.addRow("Max loop length", self.max_cycle_len)

        self.liquidity = self._dspin(cfg.liquidity_floor_divines, 0.0, 100000.0, 5.0, " div")
        form.addRow("Liquidity floor (daily volume)", self.liquidity)

        self.depth = self._dspin(cfg.depth_divines, 0.5, 1000.0, 0.5, " div")
        form.addRow("Fill depth per edge", self.depth)

        self.sound = QCheckBox("Play sound with notifications")
        self.sound.setChecked(cfg.alert_sound)
        form.addRow("", self.sound)

        note = QLabel(
            "Larger graphs / shorter intervals mean more requests to GGG's API.\n"
            "Defaults are tuned to stay well inside their rate limits — be polite."
        )
        note.setStyleSheet("color: gray;")
        layout.addWidget(note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _dspin(value: float, lo: float, hi: float, step: float, suffix: str) -> QDoubleSpinBox:
        s = QDoubleSpinBox()
        s.setRange(lo, hi)
        s.setSingleStep(step)
        s.setSuffix(suffix)
        s.setValue(value)
        return s

    def result_config(self) -> Config:
        return replace(
            self._cfg,
            league=self.league.text().strip() or None,
            profit_threshold_pct=self.threshold.value(),
            fee_pct=self.fee.value(),
            watch_interval_minutes=self.interval.value(),
            max_currencies=self.max_currencies.value(),
            max_cycle_len=int(self.max_cycle_len.currentText()),
            liquidity_floor_divines=self.liquidity.value(),
            depth_divines=self.depth.value(),
            alert_sound=self.sound.isChecked(),
        )
