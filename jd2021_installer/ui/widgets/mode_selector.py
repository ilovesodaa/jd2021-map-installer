"""Mode-selection widget: choose input mode and provide dynamic inputs.

Modes
-----
- **Fetch**   – Enter one or more song codenames to scrape from the web.
- **HTML**    – Load a previously-saved HTML page.
- **IPK**     – Load a local IPK archive file.
- **Batch**   – Select a directory containing multiple IPK files.
- **Manual**  – Point to a pre-extracted map directory or set of files.

Each mode shows a tailored input area via a ``QStackedWidget``.
"""

from __future__ import annotations

import logging
from typing import Optional

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

logger = logging.getLogger("jd2021.ui.widgets.mode_selector")

# Mode identifiers (indices match the combo-box order)
MODE_FETCH = 0
MODE_HTML = 1
MODE_IPK = 2
MODE_BATCH = 3
MODE_MANUAL = 4

MODE_LABELS = [
    "Fetch (Codename)",
    "HTML File",
    "IPK Archive",
    "Batch (Directory)",
    "Manual (Directory)",
]


class FileRowWidget(QWidget):
    """Reusable row for labeled file/directory input with a 'Browse' button."""

    path_changed = pyqtSignal(str)

    def __init__(
        self,
        label_text: str,
        is_dir: bool = False,
        file_filter: str = "All Files (*.*)",
        placeholder: str = "",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.is_dir = is_dir
        self.file_filter = file_filter

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel(label_text)
        lbl.setMinimumWidth(120)
        lay.addWidget(lbl)

        self.line_edit = QLineEdit()
        self.line_edit.setReadOnly(True)
        self.line_edit.setPlaceholderText(placeholder)
        lay.addWidget(self.line_edit)

        btn = QPushButton("Browse…")
        btn.clicked.connect(self._browse)
        lay.addWidget(btn)

    def _browse(self) -> None:
        if self.is_dir:
            path = QFileDialog.getExistingDirectory(self, "Select Directory")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, "Select File", "", self.file_filter
            )

        if path:
            self.line_edit.setText(path)
            self.path_changed.emit(path)


class ModeSelectorWidget(QWidget):
    """Dropdown + dynamic input area for selecting the map-import mode."""

    mode_changed = pyqtSignal(str)  # emits the label string
    target_selected = pyqtSignal(str)  # emits the user-provided input/main path

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.inputs: dict[str, dict[str, QLineEdit]] = {
            "fetch": {},
            "html": {},
            "ipk": {},
            "batch": {},
            "manual": {},
        }
        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        # Mode row layout to keep combo box concise
        mode_row = QHBoxLayout()
        lbl = QLabel("Mode:")
        lbl.setStyleSheet("font-weight: bold;")
        lbl.setFixedWidth(80)
        mode_row.addWidget(lbl)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(MODE_LABELS)
        self._mode_combo.currentIndexChanged.connect(self._on_mode_index_changed)
        mode_row.addWidget(self._mode_combo)
        mode_row.addStretch()
        root.addLayout(mode_row)

        # Stacked widget for mode-specific inputs
        self._stack = QStackedWidget()
        root.addWidget(self._stack)

        self._stack.addWidget(self._build_fetch_page())  # 0
        self._stack.addWidget(self._build_html_page())  # 1
        self._stack.addWidget(self._build_ipk_page())  # 2
        self._stack.addWidget(self._build_batch_page())  # 3
        self._stack.addWidget(self._build_manual_page())  # 4

    # -- Mode Pages ---------------------------------------------------------

    def _build_fetch_page(self) -> QWidget:
        page = QWidget()
        lay = QHBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        lbl = QLabel("Codename(s):")
        lbl.setMinimumWidth(120)
        lay.addWidget(lbl)

        inp = QLineEdit()
        inp.setPlaceholderText("e.g. RainOnMe, DontStartNow")
        inp.textChanged.connect(lambda t: self.target_selected.emit(t))
        lay.addWidget(inp)

        self.inputs["fetch"]["codenames"] = inp
        return page

    def _build_html_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        warn = QLabel(
            "⚠️ Asset/NoHUD links expire after ~30 minutes! Fetch fresh links if download fails."
        )
        warn.setStyleSheet("color: #856404; font-weight: bold;")
        warn.setWordWrap(True)
        lay.addWidget(warn)

        asset_row = FileRowWidget(
            "Asset HTML:",
            is_dir=False,
            file_filter="HTML Files (*.html *.htm)",
            placeholder="No file selected",
        )
        lay.addWidget(asset_row)

        nohud_row = FileRowWidget(
            "NOHUD HTML:",
            is_dir=False,
            file_filter="HTML Files (*.html *.htm)",
            placeholder="No file selected",
        )
        lay.addWidget(nohud_row)

        self.inputs["html"]["asset"] = asset_row.line_edit
        self.inputs["html"]["nohud"] = nohud_row.line_edit

        # Auto-detect counterparts
        def auto_detect(source_path: str, is_asset: bool):
            if not source_path: return
            src = Path(source_path)
            target_obj = self.inputs["html"]["nohud"] if is_asset else self.inputs["html"]["asset"]
            if target_obj.text() and Path(target_obj.text()).exists(): return
            
            # Simple heuristic guessing: "assets" <-> "nohud" or "asset" <-> "nohud"
            stem = src.stem.lower()
            name_lower = src.name.lower()
            candidate = None
            if is_asset and ("asset" in name_lower or "hud" not in name_lower):
                # Try replacing asset with nohud, or just append _nohud
                for test in ["_nohud.html", "_no_hud.html", "nohud.html"]:
                    c = src.parent / (stem.replace("assets", "nohud").replace("asset", "nohud") + test if "asset" not in stem else stem.replace("assets", "nohud").replace("asset", "nohud") + ".html")
                    if not c.exists():
                        c = src.parent / (stem + test)
                    if c.exists():
                        candidate = c
                        break
            elif not is_asset and "nohud" in name_lower:
                for test in ["_assets.html", "_asset.html", "assets.html", "asset.html"]:
                    c = src.parent / (stem.replace("nohud", "assets") + ".html")
                    if not c.exists():
                        c = src.parent / stem.replace("nohud", "").strip("_") / ".html"
                    if c.exists():
                        candidate = c
                        break
                        
            # More aggressive counterpart heuristic: if there are only 2 HTML files in the dir
            if not candidate and src.parent.exists():
                htmls = list(src.parent.glob("*.html"))
                if len(htmls) == 2:
                    candidate = next(h for h in htmls if h != src)

            if candidate and candidate.exists():
                logger.info("Auto-detected HTML counterpart: %s", candidate)
                target_obj.setText(str(candidate))
                
            if is_asset:
                self.target_selected.emit(source_path)

        asset_row.path_changed.connect(lambda p: auto_detect(p, True))
        nohud_row.path_changed.connect(lambda p: auto_detect(p, False))

        return page

    def _build_ipk_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        row = FileRowWidget(
            "IPK File:",
            is_dir=False,
            file_filter="IPK Archives (*.ipk);;All Files (*.*)",
            placeholder="No IPK selected",
        )
        row.path_changed.connect(lambda t: self.target_selected.emit(t))
        lay.addWidget(row)
        lay.addStretch()

        self.inputs["ipk"]["file"] = row.line_edit
        return page

    def _build_batch_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        warn = QLabel(
            "Batch installs from a folder containing map subfolders with asset/nohud HTML files "
            "or already-downloaded files."
        )
        warn.setStyleSheet("color: #555555; font-style: italic;")
        warn.setWordWrap(True)
        lay.addWidget(warn)

        row = FileRowWidget(
            "Maps Folder:", is_dir=True, placeholder="No directory selected"
        )
        row.path_changed.connect(lambda t: self.target_selected.emit(t))
        lay.addWidget(row)
        lay.addStretch()

        self.inputs["batch"]["dir"] = row.line_edit
        return page

    def _build_manual_page(self) -> QWidget:
        """The monster manual page mirroring Tkinter V1."""
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 4, 0, 0)

        # Top generic entries
        top_lay = QGridLayout()
        top_lay.setContentsMargins(0, 0, 0, 0)
        
        root_row = FileRowWidget("Root Folder:", is_dir=True)
        root_row.path_changed.connect(lambda t: self.target_selected.emit(t))
        top_lay.addWidget(root_row, 0, 0, 1, 2)

        lbl_code = QLabel("Codename:")
        lbl_code.setMinimumWidth(120)
        top_lay.addWidget(lbl_code, 1, 0)
        inp_code = QLineEdit()
        top_lay.addWidget(inp_code, 1, 1)

        lay.addLayout(top_lay)

        # Required Files Group
        grp_req = QGroupBox("Required Files")
        lay_req = QVBoxLayout(grp_req)
        
        row_audio = FileRowWidget("Audio File:", file_filter="Audio (*.ogg *.wav *.wav.ckd);;All (*.*)")
        row_video = FileRowWidget("Video File:", file_filter="WebM (*.webm);;All (*.*)")
        row_mtrack = FileRowWidget("Musictrack CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        
        lay_req.addWidget(row_audio)
        lay_req.addWidget(row_video)
        lay_req.addWidget(row_mtrack)
        lay.addWidget(grp_req)

        # Optional Tapes Group
        grp_tapes = QGroupBox("Tapes & Config")
        lay_tapes = QVBoxLayout(grp_tapes)
        
        row_sdesc = FileRowWidget("Songdesc CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        row_dtape = FileRowWidget("Dance Tape CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        row_ktape = FileRowWidget("Karaoke Tape CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        row_mseq = FileRowWidget("Mainseq Tape CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        
        lay_tapes.addWidget(row_sdesc)
        lay_tapes.addWidget(row_dtape)
        lay_tapes.addWidget(row_ktape)
        lay_tapes.addWidget(row_mseq)
        lay.addWidget(grp_tapes)

        # Optional Assets Group
        grp_assets = QGroupBox("Asset Folders")
        lay_assets = QVBoxLayout(grp_assets)
        
        row_moves = FileRowWidget("Moves Folder:", is_dir=True)
        row_pictos = FileRowWidget("Pictos Folder:", is_dir=True)
        row_menuart = FileRowWidget("MenuArt Folder:", is_dir=True)
        row_amb = FileRowWidget("AMB Folder:", is_dir=True)
        
        lay_assets.addWidget(row_moves)
        lay_assets.addWidget(row_pictos)
        lay_assets.addWidget(row_menuart)
        lay_assets.addWidget(row_amb)
        lay.addWidget(grp_assets)
        
        self.inputs["manual"].update({
            "root": root_row.line_edit,
            "codename": inp_code,
            "audio": row_audio.line_edit,
            "video": row_video.line_edit,
            "mtrack": row_mtrack.line_edit,
            "sdesc": row_sdesc.line_edit,
            "dtape": row_dtape.line_edit,
            "ktape": row_ktape.line_edit,
            "mseq": row_mseq.line_edit,
            "moves": row_moves.line_edit,
            "pictos": row_pictos.line_edit,
            "menuart": row_menuart.line_edit,
            "amb": row_amb.line_edit,
        })
        
        return page

    # ------------------------------------------------------------------
    # Slots / helpers
    # ------------------------------------------------------------------

    def _on_mode_index_changed(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        self.mode_changed.emit(MODE_LABELS[index])
        logger.debug("Mode switched to: %s", MODE_LABELS[index])

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        return MODE_LABELS[self._mode_combo.currentIndex()]

    @property
    def current_mode_index(self) -> int:
        return self._mode_combo.currentIndex()
