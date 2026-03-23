"""Quickstart Guide dialog for first-time users."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QCheckBox,
    QHBoxLayout,
    QWidget,
)

class QuickstartDialog(QDialog):
    """Simple dialog explaining the basic workflow."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("JD2021 Map Installer - Quickstart Guide")
        self.setMinimumSize(500, 400)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        title = QLabel("Welcome to JD2021 Map Installer V2!")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #5865F2;")
        layout.addWidget(title)

        guide = QTextBrowser()
        guide.setOpenExternalLinks(True)
        guide.setHtml(\"\"\"
            <h3>How to use this tool:</h3>
            <ol>
                <li><b>Set Game Directory:</b> Go to the 'Configuration' tab and select your JD2021 'data' folder.</li>
                <li><b>Choose Mode:</b>
                    <ul>
                        <li><b>Fetch:</b> Enter a codename (e.g., <i>TemperatureAlt</i>) to auto-download from Discord.</li>
                        <li><b>HTML:</b> Manually select .html files from the JDU bot.</li>
                        <li><b>IPK/Direct:</b> Select a local .ipk file or extracted map folder.</li>
                    </ul>
                </li>
                <li><b>Install:</b> Click 'Start Installation'. The tool will extract, normalize, and copy files.</li>
                <li><b>Sync Refinement:</b> After installation, use the 'Sync Refinement' panel to fine-tune audio/video timing if needed.</li>
            </ol>
            <p><i>Tip: Use 'Sync Beatgrid' to quickly align audio trim with the video start time.</i></p>
            <hr/>
            <p>For more help, visit the <a href="https://github.com/VenB304/jd2021-map-installer">GitHub Repository</a>.</p>
        \"\"\" )
        layout.addWidget(guide)

        footer = QHBoxLayout()
        self.dont_show_again = QCheckBox("Don't show this again")
        footer.addWidget(self.dont_show_again)
        footer.addStretch()
        
        btn_close = QPushButton("Got it!")
        btn_close.clicked.connect(self.accept)
        btn_close.setDefault(True)
        footer.addWidget(btn_close)
        
        layout.addLayout(footer)

    @classmethod
    def show_guide(cls, parent=None) -> bool:
        """Show the guide and return True if 'Don't show again' was checked."""
        dlg = cls(parent)
        dlg.exec()
        return dlg.dont_show_again.isChecked()
