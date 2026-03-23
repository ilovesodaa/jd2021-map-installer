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
    import argparse
    parser = argparse.ArgumentParser(description="JD2021 Map Installer V2")
    parser.add_argument("--cli", action="store_true", help="Run in headless CLI mode")
    parser.add_argument("--mode", choices=["fetch", "html", "ipk", "batch", "manual"], default="fetch", help="Import mode")
    parser.add_argument("--target", help="Input path (codename for fetch, file for ipk/html, dir for batch/manual)")
    parser.add_argument("--game-dir", help="Path to JD2021 'data' directory")
    args = parser.parse_args()

    if args.cli:
        from jd2021_installer.cli import run_cli
        return run_cli(args)

    setup_logging()

    app = QApplication(sys.argv)
    app.setApplicationName("JD2021 Map Installer")
    app.setApplicationVersion("2.0.0")

    window = MainWindow()
    if args.target:
        # Pre-fill target if passed via CMD but starting GUI
        window._current_target = args.target
        # TODO: update UI widgets to reflect this
    window.show()

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
