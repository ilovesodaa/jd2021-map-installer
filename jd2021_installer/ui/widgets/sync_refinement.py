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
)

logger = logging.getLogger("jd2021.ui.widgets.sync_refinement")


class SyncRefinementWidget(QWidget):
    """Audio/video offset adjustment + embedded FFplay preview frame."""

    # Signals
    offset_changed = pyqtSignal(float)       # combined offset in ms
    preview_requested = pyqtSignal(bool)      # True = start, False = stop
    apply_requested = pyqtSignal(float)       # combined offset to apply
    pad_audio_requested = pyqtSignal()

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
        self._audio_spin.setRange(-5000.0, 5000.0)
        self._audio_spin.setSingleStep(10.0)
        self._audio_spin.setDecimals(1)
        self._audio_spin.setValue(0.0)
        self._audio_spin.setToolTip("Shift audio timing (negative = earlier)")
        offsets_row.addWidget(self._audio_spin)

        offsets_row.addSpacing(12)

        # Video offset
        offsets_row.addWidget(QLabel("Video Offset (ms):"))
        self._video_spin = QDoubleSpinBox()
        self._video_spin.setRange(-5000.0, 5000.0)
        self._video_spin.setSingleStep(10.0)
        self._video_spin.setDecimals(1)
        self._video_spin.setValue(0.0)
        self._video_spin.setToolTip("Shift video timing (negative = earlier)")
        offsets_row.addWidget(self._video_spin)

        group_layout.addLayout(offsets_row)

        # -- Combined display -----------------------------------------------
        combined_row = QHBoxLayout()
        combined_row.addWidget(QLabel("Combined Offset:"))
        self._combined_display = QLineEdit("0.0 ms")
        self._combined_display.setReadOnly(True)
        self._combined_display.setMaximumWidth(120)
        self._combined_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        combined_row.addWidget(self._combined_display)
        combined_row.addStretch()
        group_layout.addLayout(combined_row)

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

        self._btn_apply = QPushButton("✔  Apply Offset")
        self._btn_apply.setObjectName("btn_apply_offset")
        self._btn_apply.setToolTip("Commit the combined offset to the current map data")
        self._btn_apply.clicked.connect(self._on_apply)
        preview_row.addWidget(self._btn_apply)

        group_layout.addLayout(preview_row)

        # Embedded video container (winId() can be passed to FFplay -wid)
        self._preview_frame = QWidget()
        self._preview_frame.setMinimumHeight(180)
        self._preview_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._preview_frame.setStyleSheet("background-color: #111; border-radius: 4px;")
        group_layout.addWidget(self._preview_frame)

    # ------------------------------------------------------------------
    # Internal wiring
    # ------------------------------------------------------------------

    def _connect_internal(self) -> None:
        self._audio_spin.valueChanged.connect(self._update_combined)
        self._video_spin.valueChanged.connect(self._update_combined)

    def _update_combined(self) -> None:
        combined = self._audio_spin.value() + self._video_spin.value()
        self._combined_display.setText(f"{combined:+.1f} ms")
        self.offset_changed.emit(combined)

    def _on_preview_toggled(self, checked: bool) -> None:
        self._btn_preview.setText("⏹  Stop" if checked else "▶  Preview")
        self.preview_requested.emit(checked)

    def _on_apply(self) -> None:
        combined = self._audio_spin.value() + self._video_spin.value()
        self.apply_requested.emit(combined)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def preview_frame(self) -> QWidget:
        """Return the container widget whose ``winId()`` can embed FFplay."""
        return self._preview_frame

    @property
    def combined_offset(self) -> float:
        return self._audio_spin.value() + self._video_spin.value()

    def set_offsets(self, audio_ms: float = 0.0, video_ms: float = 0.0) -> None:
        """Programmatically set both offset spinboxes."""
        self._audio_spin.setValue(audio_ms)
        self._video_spin.setValue(video_ms)

    def reset(self) -> None:
        """Reset both spinboxes to zero."""
        self._audio_spin.setValue(0.0)
        self._video_spin.setValue(0.0)
