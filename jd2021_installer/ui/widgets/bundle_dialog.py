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
    QCheckBox,
)
from PyQt6.QtCore import Qt


class BundleSelectDialog(QDialog):
    """Allows selecting multiple maps from a detected Bundle IPK."""

    def __init__(self, ipk_name: str, maps_found: List[str], parent=None):
        super().__init__(parent)
        self.setWindowTitle("Bundle IPK Detected")
        self.setMinimumSize(360, 420)

        self._selected_maps = []

        layout = QVBoxLayout(self)
        
        lbl = QLabel(f"The archive <b>{ipk_name}</b> contains multiple maps.<br>Please select the maps you want to install.")
        layout.addWidget(lbl)

        controls = QHBoxLayout()
        self._select_all = QCheckBox("Select All")
        self._select_all.setToolTip("Toggle all bundle maps on or off")
        self._select_all.setChecked(True)
        self._select_all.toggled.connect(self._on_select_all_toggled)
        controls.addWidget(self._select_all)
        self._count_label = QLabel()
        controls.addStretch(1)
        controls.addWidget(self._count_label)
        layout.addLayout(controls)

        self.list_widget = QListWidget()
        self.list_widget.setToolTip("Check the maps you want to install from this bundle")
        self.list_widget.itemChanged.connect(self._on_item_changed)
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
        self._refresh_selection_state()

    def _on_select_all_toggled(self, checked: bool) -> None:
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            item.setCheckState(state)
        self._refresh_selection_state()

    def _on_item_changed(self, _: QListWidgetItem) -> None:
        self._refresh_selection_state()

    def _refresh_selection_state(self) -> None:
        total = self.list_widget.count()
        selected = 0
        for i in range(total):
            if self.list_widget.item(i).checkState() == Qt.CheckState.Checked:
                selected += 1
        self._count_label.setText(f"{selected} of {total} selected")
        all_selected = total > 0 and selected == total
        self._select_all.blockSignals(True)
        self._select_all.setChecked(all_selected)
        self._select_all.blockSignals(False)

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
