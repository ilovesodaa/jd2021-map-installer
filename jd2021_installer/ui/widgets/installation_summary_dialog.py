"""Dialog displaying install completion checklists and stats."""

from __future__ import annotations

from typing import Optional

from PyQt6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from jd2021_installer.core.install_summary import InstallSummary, render_install_summary


class InstallationSummaryDialog(QDialog):
    """Modal summary dialog shown after install pipeline completion."""

    def __init__(self, summaries: list[InstallSummary], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setWindowTitle("Installation Summary")
        self.setMinimumSize(820, 560)
        self._summaries = summaries
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(10)

        heading = QLabel("Installation Summary")
        heading.setObjectName("installationSummaryTitle")
        layout.addWidget(heading)

        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)

        blocks = []
        for summary in self._summaries:
            blocks.append(render_install_summary(summary))

        text.setPlainText("\n\n" + ("\n\n" + ("=" * 72) + "\n\n").join(blocks))
        layout.addWidget(text)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def show_summaries(summaries: list[InstallSummary], parent: Optional[QWidget] = None) -> None:
        if not summaries:
            return
        dialog = InstallationSummaryDialog(summaries, parent)
        dialog.exec()