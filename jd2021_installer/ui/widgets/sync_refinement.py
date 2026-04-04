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
    offsets_changed = pyqtSignal(float, float)  # (audio_ms, video_ms)
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

    def _set_preview_icon(self, playing: bool) -> None:
        text = "Stop" if playing else "Preview"
        self._btn_preview.setText(text)

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(4, 4, 4, 4)

        group = QGroupBox("Sync Refinement")
        group_layout = QVBoxLayout(group)
        root.addWidget(group)

        # -- Offset spinboxes -----------------------------------------------
        offsets_row = QHBoxLayout()

        # Audio offset
        audio_offset_label = QLabel("Audio Offset (ms):")
        audio_offset_label.setObjectName("syncOffsetLabel")
        offsets_row.addWidget(audio_offset_label)
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
        self._video_check.setObjectName("videoOffsetCheck")
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
        self._audio_buttons = []
        self._video_buttons = []
        inc_row_audio = QHBoxLayout()
        inc_row_audio.setSpacing(4)
        audio_label = QLabel("Adj Audio:")
        audio_label.setObjectName("syncOffsetLabel")
        audio_label.setMinimumWidth(70)
        inc_row_audio.addWidget(audio_label)
        
        for delta in [-1000.0, -100.0, -10.0, -1.0, 1.0, 10.0, 100.0, 1000.0]:
            btn = QPushButton(f"{delta:+.0f}")
            btn.setMinimumWidth(50)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("syncAdjustButton", True)
            btn.clicked.connect(lambda _, d=delta: self._adjust_audio(d))
            inc_row_audio.addWidget(btn, 1)
            self._audio_buttons.append(btn)
        group_layout.addLayout(inc_row_audio)

        inc_row_video = QHBoxLayout()
        inc_row_video.setSpacing(4)
        video_label = QLabel("Adj Video:")
        video_label.setObjectName("syncOffsetLabel")
        video_label.setMinimumWidth(70)
        inc_row_video.addWidget(video_label)
        for delta in [-1000.0, -100.0, -10.0, -1.0, 1.0, 10.0, 100.0, 1000.0]:
            btn = QPushButton(f"{delta:+.0f}")
            btn.setMinimumWidth(50)
            btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            btn.setProperty("syncAdjustButton", True)
            btn.clicked.connect(lambda _, d=delta: self._adjust_video(d))
            inc_row_video.addWidget(btn, 1)
            self._video_buttons.append(btn)

        group_layout.addLayout(inc_row_video)


        # -- Separator -------------------------------------------------------
        sep = QFrame()
        sep.setObjectName("sectionSeparator")
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Plain)
        sep.setLineWidth(1)
        group_layout.addWidget(sep)

        # -- Preview frame ---------------------------------------------------
        preview_row = QHBoxLayout()

        self._btn_preview = QPushButton("Preview")
        self._btn_preview.setObjectName("btn_preview")
        self._set_preview_icon(False)
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

        self._btn_apply = QPushButton("Apply Offset")
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
        self._nav_label.setObjectName("syncNavLabel")
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
        audio_ms = self._audio_spin.value()
        video_ms = self._video_spin.value()
        self.offsets_changed.emit(audio_ms, video_ms)

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

    def get_audio_offset(self) -> float:
        """Return current audio offset (ms)."""
        return self._audio_spin.value()

    def get_video_offset(self) -> float:
        """Return current video offset (ms)."""
        return self._video_spin.value()

    def get_offsets(self) -> tuple[float, float]:
        """Return (audio_ms, video_ms)."""
        return self.get_audio_offset(), self.get_video_offset()

    def set_video_override(
        self,
        enabled: bool,
        *,
        lock_toggle: bool = False,
        force_spin_enabled: Optional[bool] = None,
    ) -> None:
        """Public API to control video override UI state without private-field access."""
        self._video_check.blockSignals(True)
        self._video_check.setChecked(enabled)
        self._video_check.setEnabled(not lock_toggle)
        self._video_check.blockSignals(False)

        if force_spin_enabled is None:
            self._video_spin.setEnabled(enabled)
        else:
            self._video_spin.setEnabled(force_spin_enabled)
        self._update_combined()

    def apply_profile(self, profile_name: str) -> None:
        """Apply readjust profile behavior to sync controls."""
        profile = profile_name.strip().lower()

        if profile == "ipk":
            self.set_audio_editable(False)
            self.set_video_editable(True)
            self.set_video_override(True, lock_toggle=True, force_spin_enabled=True)
            return

        if profile in {"fetch_html", "fetch-html", "fetchhtml"}:
            self.set_audio_editable(True)
            self.set_video_editable(False)
            self.set_video_override(False, lock_toggle=True, force_spin_enabled=False)
            return

        # generic/default
        self.set_audio_editable(True)
        self.set_video_editable(True)
        self.set_video_override(self._video_check.isChecked(), lock_toggle=False)

    def set_ipk_mode(self, is_ipk: bool) -> None:
        """Disable audio padding/trimming for IPK sources."""
        self.set_audio_editable(not is_ipk)
        if is_ipk:
            self._audio_spin.setValue(0.0)
            self._audio_spin.setToolTip("Audio reprocessing disabled for IPK sources")
        else:
            self._audio_spin.setToolTip("Shift audio timing (negative = earlier)")

    def set_audio_editable(self, editable: bool) -> None:
        """Enable or disable audio offset controls entirely."""
        self._audio_spin.setEnabled(editable)
        for btn in self._audio_buttons:
            btn.setEnabled(editable)

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
        self._set_preview_icon(checked)
        self.preview_requested.emit(checked)

    def set_preview_state(self, playing: bool) -> None:
        """Update the preview button state from outside."""
        self._btn_preview.blockSignals(True)
        self._btn_preview.setChecked(playing)
        self._set_preview_icon(playing)
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
        self._update_combined()

    def reset(self) -> None:
        """Reset both spinboxes to zero."""
        self._audio_spin.setValue(0.0)
        self._video_spin.setValue(0.0)
        self._video_check.setChecked(False)
        self._update_combined()
