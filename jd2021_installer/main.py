"""Application entry point.

Creates the PyQt6 application, initializes logging, and shows the main window.
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication

from jd2021_installer.ui.main_window import MainWindow


def setup_logging() -> None:
    """Configure root logger for the application."""
    root = logging.getLogger("jd2021")
    if root.handlers:
        return
    root.setLevel(logging.DEBUG)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(handler)


def main() -> int:
    """Application entry point."""
    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("JD2021 Map Installer")
    app.setApplicationVersion("2.0.0")

    window = MainWindow()
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
