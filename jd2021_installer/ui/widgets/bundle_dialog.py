"""Dialog for selecting maps from a Bundle IPK."""

from typing import List, Optional

from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QListWidget,
    QListWidgetItem,
    QLabel,
    QDialogButtonBox,
)
from PyQt6.QtCore import Qt


class BundleSelectDialog(QDialog):
    """Allows selecting multiple maps from a detected Bundle IPK."""

    def __init__(self, ipk_name: str, maps_found: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bundle IPK Detected")
        self.resize(300, 400)

        self._selected_maps = []

        layout = QVBoxLayout(self)
        
        lbl = QLabel(f"The archive <b>{ipk_name}</b> contains multiple maps.<br>Please select the maps you want to install.")
        layout.addWidget(lbl)

        self.list_widget = QListWidget()
        for m in maps_found:
            item = QListWidgetItem(m)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list_widget.addItem(item)
            
        layout.addWidget(self.list_widget)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def get_selected_maps(self) -> List[str]:
        selected = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                selected.append(item.text())
        return selected

    @staticmethod
    def show_dialog(ipk_name: str, maps_found: List[str], parent=None) -> Optional[List[str]]:
        dialog = BundleSelectDialog(ipk_name, maps_found, parent)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            return dialog.get_selected_maps()
        return None
