"""Application entry point.

Creates the PyQt6 application, initializes logging, and shows the main window.
"""

from __future__ import annotations

import logging
import sys

from PyQt6.QtWidgets import QApplication, QMessageBox

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
    raw_args = sys.argv[1:]
    has_cli_args = any(
        arg == "--cli"
        or arg.startswith("--mode")
        or arg.startswith("--target")
        or arg.startswith("--game-dir")
        for arg in raw_args
    )

    setup_logging()

    app = QApplication([sys.argv[0]])
    app.setApplicationName("JD2021 Map Installer")
    app.setApplicationVersion("2.0.0")

    window = MainWindow()
    window.show()

    if has_cli_args:
        QMessageBox.warning(
            window,
            "GUI Only Application",
            "CLI routing is disabled in v2.\n"
            "Provided CLI arguments were ignored and the GUI has started instead.",
        )

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
