"""Dialog for correcting non-ASCII characters in song metadata."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QDialogButtonBox,
)

class MetadataCorrectionDialog(QDialog):
    """Prompts user to replace non-ASCII characters in metadata fields."""

    def __init__(self, field_name: str, original_value: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Metadata Encoding Issue")
        self.setMinimumWidth(450)
        
        self.field_name = field_name
        self.original_value = original_value
        
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        layout.addWidget(QLabel(f"The field <b>{self.field_name}</b> contains non-ASCII characters:"))
        
        # Original value display
        self.original_display = QTextEdit(self.original_value)
        self.original_display.setReadOnly(True)
        self.original_display.setMaximumHeight(60)
        self.original_display.setObjectName("metadataOriginalDisplay")
        layout.addWidget(self.original_display)

        layout.addWidget(QLabel("Suggested ASCII/Sanitized Replacement:"))
        
        # Sanitized suggestion
        suggested = "".join(c for c in self.original_value if ord(c) < 128)
        self.input_field = QLineEdit(suggested)
        layout.addWidget(self.input_field)

        layout.addWidget(QLabel("<small><i>Tip: Some characters like '©' are fine, but Chinese/special scripts may crash the engine.</i></small>"))

        btns = QHBoxLayout()
        btn_ignore = QPushButton("Keep Original")
        btn_ignore.clicked.connect(self._on_ignore)
        
        btn_ok = QPushButton("Apply Replacement")
        btn_ok.clicked.connect(self.accept)
        btn_ok.setDefault(True)

        btns.addWidget(btn_ignore)
        btns.addStretch()
        btns.addWidget(btn_ok)
        layout.addLayout(btns)

    def _on_ignore(self) -> None:
        self.input_field.setText(self.original_value)
        self.accept()

    def get_value(self) -> str:
        return self.input_field.text()

    @staticmethod
    def get_corrected_value(field_name: str, value: str, parent=None) -> str:
        """Show dialog and return the (possibly) corrected value."""
        dialog = MetadataCorrectionDialog(field_name, value, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_value()
        return value
