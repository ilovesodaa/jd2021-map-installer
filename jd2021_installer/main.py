"""Application entry point.

Creates the PyQt6 application, initializes logging, and shows the main window.
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from jd2021_installer.core.logging_config import apply_log_detail
from jd2021_installer.ui.main_window import MainWindow


def setup_logging(log_detail_level: str = "user") -> None:
    """Configure root logger for the application."""
    root = logging.getLogger("jd2021")
    if root.handlers:
        apply_log_detail(log_detail_level)
        return
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)
    apply_log_detail(log_detail_level)


def main() -> int:
    """Application entry point."""
    setup_logging()

    app = QApplication([sys.argv[0]])
    app.setApplicationName("JD2021 Map Installer")
    app.setApplicationVersion("2.0.0")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
