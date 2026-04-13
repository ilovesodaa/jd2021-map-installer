"""Update result dialog — shows update check outcome and offers update action."""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QObject, Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.update_dialog")


class _UpdateWorker(QObject):
    """Runs an update operation in a background thread."""

    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, updater, branch: str) -> None:
        super().__init__()
        self._updater = updater
        self._branch = branch

    def run(self) -> None:
        try:
            result = self._updater.perform_update(self._branch)
            self.finished.emit(result)
        except Exception as exc:
            logger.exception("Update failed: %s", exc)
            self.error.emit(str(exc))


class UpdateResultDialog(QDialog):
    """Modal dialog that shows the result of an update check.

    Parameters
    ----------
    check_result:
        An ``UpdateCheckResult`` from the updater module.
    updater:
        The ``Updater`` instance to use if the user clicks "Update Now".
    parent:
        Parent widget.
    """

    def __init__(
        self,
        check_result,
        updater,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._result = check_result
        self._updater = updater
        self._update_thread: Optional[QThread] = None
        self._update_worker: Optional[_UpdateWorker] = None

        self.setWindowTitle("Update Check")
        self.setMinimumWidth(440)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        r = self._result

        if r.error:
            self._build_error_view(layout, r)
        elif r.is_up_to_date:
            self._build_up_to_date_view(layout, r)
        else:
            self._build_update_available_view(layout, r)

    def _build_error_view(self, layout: QVBoxLayout, r) -> None:
        icon_label = QLabel("⚠️  Could not check for updates")
        icon_label.setObjectName("updateDialogTitle")
        icon_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(icon_label)

        error_label = QLabel(str(r.error))
        error_label.setWordWrap(True)
        error_label.setStyleSheet("color: #b55;")
        layout.addWidget(error_label)

        info = QLabel(
            f"Branch: {r.branch}\n"
            f"Local commit: {r.local_commit}\n"
            f"Source: {'git repo' if r.is_git_repo else 'zip (no .git found)'}"
        )
        info.setStyleSheet("color: #888;")
        layout.addWidget(info)

        layout.addStretch()
        self._add_close_button(layout)

    def _build_up_to_date_view(self, layout: QVBoxLayout, r) -> None:
        icon_label = QLabel("✅  You're up to date!")
        icon_label.setObjectName("updateDialogTitle")
        icon_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(icon_label)

        info = QLabel(
            f"Branch: {r.branch}\n"
            f"Current commit: {r.local_commit}\n"
            f"Latest commit: {r.remote_commit}\n"
            f"Source: {'git repo' if r.is_git_repo else 'zip (no .git found)'}"
        )
        layout.addWidget(info)

        layout.addStretch()
        self._add_close_button(layout)

    def _build_update_available_view(self, layout: QVBoxLayout, r) -> None:
        icon_label = QLabel("🔄  Update Available")
        icon_label.setObjectName("updateDialogTitle")
        icon_label.setStyleSheet("font-size: 15px; font-weight: bold;")
        layout.addWidget(icon_label)

        behind_text = (
            f"{r.commits_behind} commit{'s' if r.commits_behind != 1 else ''} behind"
            if r.commits_behind > 0
            else "behind remote"
        )
        info = QLabel(
            f"Branch: {r.branch}\n"
            f"Current: {r.local_commit}\n"
            f"Latest: {r.remote_commit}\n"
            f"Status: {behind_text}"
        )
        layout.addWidget(info)

        if r.remote_commit_message:
            msg_label = QLabel(f"Latest commit:\n\"{r.remote_commit_message}\"")
            msg_label.setWordWrap(True)
            msg_label.setStyleSheet("font-style: italic; color: #666;")
            layout.addWidget(msg_label)

        method = "git pull" if r.is_git_repo else "zip download"
        method_label = QLabel(f"Update method: {method}")
        method_label.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(method_label)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        btn_update = QPushButton("Update Now")
        btn_update.setMinimumWidth(120)
        btn_update.clicked.connect(self._on_update)
        btn_layout.addWidget(btn_update)

        btn_later = QPushButton("Later")
        btn_later.setMinimumWidth(80)
        btn_later.clicked.connect(self.reject)
        btn_layout.addWidget(btn_later)

        layout.addLayout(btn_layout)

    def _add_close_button(self, layout: QVBoxLayout) -> None:
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setMinimumWidth(80)
        btn_ok.clicked.connect(self.accept)
        btn_layout.addWidget(btn_ok)
        layout.addLayout(btn_layout)

    def _on_update(self) -> None:
        """Start the update process in a background thread."""
        if self._update_thread is not None and self._update_thread.isRunning():
            return

        progress = QProgressDialog("Downloading update...", "", 0, 0, self)
        progress.setWindowTitle("Updating")
        progress.setWindowModality(Qt.WindowModality.ApplicationModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(False)
        progress.show()

        worker = _UpdateWorker(self._updater, self._result.branch)
        thread = QThread(self)
        worker.moveToThread(thread)

        def _on_finished(result) -> None:
            progress.close()
            progress.deleteLater()
            if result.success:
                self._show_update_success(result)
            else:
                QMessageBox.critical(
                    self,
                    "Update Failed",
                    f"Update failed:\n{result.error}",
                )
            thread.quit()

        def _on_error(msg: str) -> None:
            progress.close()
            progress.deleteLater()
            QMessageBox.critical(self, "Update Error", f"Update error:\n{msg}")
            thread.quit()

        thread.started.connect(worker.run)
        worker.finished.connect(_on_finished)
        worker.error.connect(_on_error)
        worker.finished.connect(worker.deleteLater)
        worker.error.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)

        def _cleanup() -> None:
            self._update_worker = None
            self._update_thread = None

        thread.finished.connect(_cleanup)

        self._update_worker = worker
        self._update_thread = thread
        thread.start()

    def _show_update_success(self, result) -> None:
        """Show success message and offer restart."""
        reply = QMessageBox.information(
            self,
            "Update Complete",
            f"Update applied successfully!\n\n"
            f"Method: {result.method}\n"
            f"Previous: {result.old_commit}\n"
            f"Current: {result.new_commit}\n\n"
            "The application needs to restart to use the new version.\n"
            "Restart now?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._restart_application()
        else:
            self.accept()

    @staticmethod
    def _restart_application() -> None:
        """Restart the current application process."""
        import subprocess

        python = sys.executable
        # Always restart via -m so the project root is on sys.path correctly,
        # regardless of whether argv[0] is a script path or a module flag.
        restart_args = [python, "-m", "jd2021_installer.main"]
        try:
            subprocess.Popen(restart_args)
        except Exception as exc:
            logger.error("Failed to restart: %s", exc)
            QMessageBox.warning(
                None,
                "Restart Failed",
                f"Could not auto-restart. Please close and re-open the application.\n\n{exc}",
            )
            return
        # Exit current process
        from PyQt6.QtWidgets import QApplication
        app = QApplication.instance()
        if app:
            app.quit()
