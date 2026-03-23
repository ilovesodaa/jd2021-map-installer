"""Sync-refinement widget for audio/video offset adjustment.

Provides:
- **Audio offset** spinbox (ms, fine-grained).
- **Video offset** spinbox (ms, fine-grained).
- **Combined offset display** (read-only, computed from the two).
- **Preview** toggle button that starts/stops FFplay inside an
  embedded frame (``QWidget`` whose ``winId()`` can be passed to
  FFplay ``-wid``).
- **Apply** button to commit the override to the in-memory
  ``NormalizedMapData``.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QDoubleSpinBox,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
    QCheckBox,
)

logger = logging.getLogger("jd2021.ui.widgets.sync_refinement")


class SyncRefinementWidget(QWidget):
    """Audio/video offset adjustment + embedded FFplay preview frame."""

    # Signals
    offset_changed = pyqtSignal(float)       # combined offset in ms
    preview_requested = pyqtSignal(bool)      # True = start, False = stop
    apply_requested = pyqtSignal(float, float) # (audio_ms, video_ms) to apply
    pad_audio_requested = pyqtSignal()
    nav_requested = pyqtSignal(int)          # -1 = prev, 1 = next

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self._connect_internal()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        group = QGroupBox("Sync Refinement")
        group_layout = QVBoxLayout(group)
        root.addWidget(group)

        # -- Offset spinboxes -----------------------------------------------
        offsets_row = QHBoxLayout()

        # Audio offset
        offsets_row.addWidget(QLabel("Audio Offset (ms):"))
        self._audio_spin = QDoubleSpinBox()
        self._audio_spin.setRange(-50000.0, 50000.0)
        self._audio_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._audio_spin.setDecimals(1)
        self._audio_spin.setValue(0.0)
        self._audio_spin.setToolTip("Shift audio timing (negative = earlier)")
        offsets_row.addWidget(self._audio_spin)

        offsets_row.addSpacing(12)

        # Video offset toggle + spin
        self._video_check = QCheckBox("Video Offset (ms):")
        self._video_check.setToolTip("Enable to override the engine's videoStartTime")
        self._video_check.toggled.connect(self._on_video_toggle)
        offsets_row.addWidget(self._video_check)
        
        self._video_spin = QDoubleSpinBox()
        self._video_spin.setRange(-50000.0, 50000.0)
        self._video_spin.setButtonSymbols(QDoubleSpinBox.ButtonSymbols.NoButtons)
        self._video_spin.setDecimals(1)
        self._video_spin.setValue(0.0)
        self._video_spin.setEnabled(False)
        self._video_spin.setToolTip("Shift video timing (negative = earlier)")
        offsets_row.addWidget(self._video_spin)

        group_layout.addLayout(offsets_row)

        # -- Increment Buttons Row ------------------------------------------
        # V1 Parity: +/- 1000, 100, 10, 1 (ms)
        self._video_buttons = []
        inc_row_audio = QHBoxLayout()
        inc_row_audio.addWidget(QLabel("Adj Audio:"))
        
        for delta in [-1000.0, -100.0, -10.0, -1.0, 1.0, 10.0, 100.0, 1000.0]:
            btn = QPushButton(f"{delta:+.0f}")
            btn.setFixedWidth(45)
            btn.setStyleSheet("font-size: 10px; padding: 2px;")
            btn.clicked.connect(lambda _, d=delta: self._adjust_audio(d))
            inc_row_audio.addWidget(btn)
        inc_row_audio.addStretch()
        group_layout.addLayout(inc_row_audio)

        inc_row_video = QHBoxLayout()
        inc_row_video.addWidget(QLabel("Adj Video:"))
        for delta in [-1000.0, -100.0, -10.0, -1.0, 1.0, 10.0, 100.0, 1000.0]:
            btn = QPushButton(f"{delta:+.0f}")
            btn.setFixedWidth(45)
            btn.setStyleSheet("font-size: 10px; padding: 2px;")
            btn.clicked.connect(lambda _, d=delta: self._adjust_video(d))
            inc_row_video.addWidget(btn)
            self._video_buttons.append(btn)
            
        inc_row_video.addStretch()
        group_layout.addLayout(inc_row_video)


        # -- Separator -------------------------------------------------------
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        group_layout.addWidget(sep)

        # -- Preview frame ---------------------------------------------------
        preview_row = QHBoxLayout()

        self._btn_preview = QPushButton("▶  Preview")
        self._btn_preview.setObjectName("btn_preview")
        self._btn_preview.setCheckable(True)
        self._btn_preview.setToolTip("Start/stop the FFplay preview window")
        self._btn_preview.clicked.connect(self._on_preview_toggled)
        preview_row.addWidget(self._btn_preview)

        self._btn_pad = QPushButton("Pad Audio")
        self._btn_pad.setToolTip("Auto-calculate audio offset to match video duration")
        self._btn_pad.clicked.connect(self.pad_audio_requested.emit)
        preview_row.addWidget(self._btn_pad)

        self._btn_sync_beatgrid = QPushButton("Sync Beatgrid")
        self._btn_sync_beatgrid.setToolTip("Copy video offset to audio offset (1:1 align)")
        self._btn_sync_beatgrid.clicked.connect(self._on_sync_beatgrid)
        preview_row.addWidget(self._btn_sync_beatgrid)

        self._btn_apply = QPushButton("✔  Apply Offset")
        self._btn_apply.setObjectName("btn_apply_offset")
        self._btn_apply.setToolTip("Commit the combined offset to the current map data")
        self._btn_apply.clicked.connect(self._on_apply)
        preview_row.addWidget(self._btn_apply)

        group_layout.addLayout(preview_row)

        # -- Navigation row (multi-map) --------------------------------------
        self._nav_group = QWidget()
        nav_layout = QHBoxLayout(self._nav_group)
        nav_layout.setContentsMargins(0, 4, 0, 0)
        
        self._btn_prev = QPushButton("< Prev Map")
        self._btn_prev.clicked.connect(lambda: self.nav_requested.emit(-1))
        nav_layout.addWidget(self._btn_prev)

        self._nav_label = QLabel("Map 1 / 1")
        self._nav_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._nav_label.setStyleSheet("font-weight: bold;")
        nav_layout.addWidget(self._nav_label, 1)

        self._btn_next = QPushButton("Next Map >")
        self._btn_next.clicked.connect(lambda: self.nav_requested.emit(1))
        nav_layout.addWidget(self._btn_next)

        self._nav_group.setVisible(False)
        group_layout.addWidget(self._nav_group)

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _connect_internal(self) -> None:
        self._audio_spin.valueChanged.connect(self._update_combined)
        self._video_spin.valueChanged.connect(self._update_combined)

    def _update_combined(self) -> None:
        combined = self._audio_spin.value() + self._video_spin.value()
        self.offset_changed.emit(combined)

    def _adjust_audio(self, delta: float) -> None:
        self._audio_spin.setValue(self._audio_spin.value() + delta)

    def _adjust_video(self, delta: float) -> None:
        if self._video_check.isChecked():
            self._video_spin.setValue(self._video_spin.value() + delta)

    def _on_sync_beatgrid(self) -> None:
        """Copies video offset to audio offset."""
        if self._video_check.isChecked():
            self._audio_spin.setValue(self._video_spin.value())

    def _on_video_toggle(self, checked: bool) -> None:
        self._video_spin.setEnabled(checked)
        self._update_combined()

    def set_ipk_mode(self, is_ipk: bool) -> None:
        """Disable audio padding/trimming for IPK sources."""
        self._audio_spin.setEnabled(not is_ipk)
        if is_ipk:
            self._audio_spin.setValue(0.0)
            self._audio_spin.setToolTip("Audio reprocessing disabled for IPK sources")
        else:
            self._audio_spin.setToolTip("Shift audio timing (negative = earlier)")

    def set_video_editable(self, editable: bool) -> None:
        """Enable or disable the video offset checkbox/spinbox entirely."""
        self._video_check.setEnabled(editable)
        for btn in self._video_buttons:
            btn.setEnabled(editable)
            
        # If disabled, we still keep the value but the user can't change it
        if not editable:
            self._video_spin.setEnabled(False)
        else:
            self._video_spin.setEnabled(self._video_check.isChecked())

    def set_nav_visible(self, visible: bool, label_text: str = "") -> None:
        """Toggle multi-map navigation visibility."""
        self._nav_group.setVisible(visible)
        if label_text:
            self._nav_label.setText(label_text)

    def _on_preview_toggled(self, checked: bool) -> None:
        self._btn_preview.setText("⏹  Stop" if checked else "▶  Preview")
        self.preview_requested.emit(checked)

    def set_preview_state(self, playing: bool) -> None:
        """Update the preview button state from outside."""
        self._btn_preview.blockSignals(True)
        self._btn_preview.setChecked(playing)
        self._btn_preview.setText("⏹  Stop" if playing else "▶  Preview")
        self._btn_preview.blockSignals(False)

    def _on_apply(self) -> None:
        audio_ms = self._audio_spin.value()
        video_ms = self._video_spin.value() if self._video_check.isChecked() else 0.0
        self.apply_requested.emit(audio_ms, video_ms)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def combined_offset(self) -> float:
        return self._audio_spin.value() + self._video_spin.value()

    def set_offsets(self, audio_ms: float = 0.0, video_ms: float = 0.0) -> None:
        """Programmatically set both offset spinboxes."""
        logger.debug("SyncRefinementWidget.set_offsets calling: audio=%.1f, video=%.1f", audio_ms, video_ms)
        self._audio_spin.setValue(audio_ms)
        self._video_spin.setValue(video_ms)
        self._video_check.setChecked(video_ms != 0.0)

    def reset(self) -> None:
        """Reset both spinboxes to zero."""
        self._audio_spin.setValue(0.0)
        self._video_spin.setValue(0.0)
