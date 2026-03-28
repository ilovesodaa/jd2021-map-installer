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
import os
import re
from pathlib import Path
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
    QRadioButton,
    QScrollArea,
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

        # Auto-detect counterparts (V1 parity)
        def auto_detect(source_path: str, is_asset: bool):
            if not source_path:
                return
            src = Path(source_path)
            asset_guess, nohud_guess = self._find_html_pair(src.parent)

            if is_asset and not self.inputs["html"]["nohud"].text().strip() and nohud_guess:
                self.inputs["html"]["nohud"].setText(str(nohud_guess))
                logger.info("Auto-detected NOHUD HTML: %s", nohud_guess)
            elif not is_asset and not self.inputs["html"]["asset"].text().strip() and asset_guess:
                self.inputs["html"]["asset"].setText(str(asset_guess))
                logger.info("Auto-detected Asset HTML: %s", asset_guess)

            # Keep a valid target selected no matter which HTML field was browsed.
            target = self.inputs["html"]["asset"].text().strip() or source_path
            self.target_selected.emit(target)

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
        
        # Add scroll area since there are many fields
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        
        scroll_content = QWidget()
        scroll_lay = QVBoxLayout(scroll_content)
        scroll_lay.setContentsMargins(0, 0, 0, 0)

        # Source flavor selection (v1 parity)
        source_lay = QHBoxLayout()
        source_lay.addWidget(QLabel("Source Type:"))
        self._manual_source_combo = QComboBox()
        self._manual_source_combo.addItems(["JDU", "IPK"])
        self._manual_source_combo.currentTextChanged.connect(self._on_manual_source_type_changed)
        source_lay.addWidget(self._manual_source_combo)
        self._manual_source_hint = QLabel("Downloaded assets + nohud HTML")
        source_lay.addWidget(self._manual_source_hint)
        source_lay.addStretch()
        scroll_lay.addLayout(source_lay)

        # Submode Selection
        submode_lay = QHBoxLayout()
        submode_lay.addWidget(QLabel("Manual Submode:"))
        self._manual_sub_select = QRadioButton("Select Files")
        self._manual_sub_scan = QRadioButton("Scan Directory")
        self._manual_sub_scan.setChecked(True)
        submode_lay.addWidget(self._manual_sub_select)
        submode_lay.addWidget(self._manual_sub_scan)
        submode_lay.addStretch()
        scroll_lay.addLayout(submode_lay)

        # Top generic entries
        top_lay = QGridLayout()
        top_lay.setContentsMargins(0, 0, 0, 0)
        
        root_row = FileRowWidget("Root Folder:", is_dir=True)
        root_row.path_changed.connect(self._on_manual_root_changed)
        top_lay.addWidget(root_row, 0, 0, 1, 2)

        self._manual_scan_btn = QPushButton("Scan")
        self._manual_scan_btn.clicked.connect(self._on_manual_scan_clicked)
        top_lay.addWidget(self._manual_scan_btn, 0, 2)

        lbl_code = QLabel("Codename:")
        lbl_code.setMinimumWidth(120)
        top_lay.addWidget(lbl_code, 1, 0)
        inp_code = QLineEdit()
        top_lay.addWidget(inp_code, 1, 1)

        scroll_lay.addLayout(top_lay)

        # Required Files Group
        grp_req = QGroupBox("Required Files")
        lay_req = QVBoxLayout(grp_req)
        
        row_audio = FileRowWidget("Audio File:", file_filter="Audio (*.ogg *.wav *.wav.ckd);;All (*.*)")
        row_video = FileRowWidget("Video File:", file_filter="WebM (*.webm);;All (*.*)")
        row_mtrack = FileRowWidget("Musictrack CKD:", file_filter="CKD (*.ckd);;All (*.*)")
        
        lay_req.addWidget(row_audio)
        lay_req.addWidget(row_video)
        lay_req.addWidget(row_mtrack)
        scroll_lay.addWidget(grp_req)

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
        scroll_lay.addWidget(grp_tapes)

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
        scroll_lay.addWidget(grp_assets)
        
        # Add stretch so fields pack tightly at the top
        scroll_lay.addStretch()
        
        scroll.setWidget(scroll_content)
        lay.addWidget(scroll)
        
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

    def _on_manual_root_changed(self, path: str) -> None:
        """Triggered when root folder in manual mode is changed."""
        self.target_selected.emit(path)
        if not self._manual_sub_scan.isChecked():
            return
            
        # Scan and auto-fill
        root = Path(path)
        if not root.is_dir():
            return

        source_type = self.manual_source_type
        scan_root = self._resolve_scan_root(root, source_type)
        codename = self.inputs["manual"]["codename"].text().strip()
        
        # 1. Infer codename from directory name
        if not codename:
            self.inputs["manual"]["codename"].setText(scan_root.name)
            codename = scan_root.name
        
        # 2. Auto-discover common files
        from jd2021_installer.parsers.normalizer import _find_ckd_files
        
        mapping = {
            "mtrack": "*musictrack*.tpl.ckd",
            "sdesc": "*songdesc*.tpl.ckd",
            "dtape": "*_tml_dance.?tape.ckd",
            "ktape": "*_tml_karaoke.?tape.ckd",
            "mseq": "*mainsequence*.tape.ckd",
        }
        
        for key, pattern in mapping.items():
            found = _find_ckd_files(str(scan_root), pattern, codename=codename or None)
            if found and not self.inputs["manual"][key].text().strip():
                self.inputs["manual"][key].setText(found[0])
                
        # Audio/Video
        if not self.inputs["manual"]["video"].text().strip():
            video = self._pick_manual_video(scan_root, codename or None, source_type)
            if video:
                self.inputs["manual"]["video"].setText(str(video))

        if not self.inputs["manual"]["audio"].text().strip():
            audio = self._pick_manual_audio(scan_root, codename or None, source_type)
            if audio:
                self.inputs["manual"]["audio"].setText(str(audio))
        
        # Folders
        folders = self._discover_manual_folders(scan_root)
        for key, folder in folders.items():
            if folder and not self.inputs["manual"][key].text().strip():
                self.inputs["manual"][key].setText(str(folder))

    def _on_manual_source_type_changed(self, text: str) -> None:
        """Mirror V1 behavior: clear manual state when source type changes."""
        source_type = text.strip().lower()
        if hasattr(self, "_manual_source_hint"):
            if source_type == "ipk":
                self._manual_source_hint.setText("Unpacked IPK map files")
            else:
                self._manual_source_hint.setText("Downloaded assets + nohud HTML")

        self.inputs["manual"]["root"].clear()
        self.inputs["manual"]["codename"].clear()
        for key in (
            "audio",
            "video",
            "mtrack",
            "sdesc",
            "dtape",
            "ktape",
            "mseq",
            "moves",
            "pictos",
            "menuart",
            "amb",
        ):
            self.inputs["manual"][key].clear()

    def _matches_codename(self, path: Path, codename: Optional[str]) -> bool:
        if not codename:
            return True
        lower_codename = codename.lower()
        lower_name = path.name.lower()
        if re.match(rf"^{re.escape(lower_codename)}(?:[^a-z0-9]|$)", lower_name):
            return True
        return lower_codename in [p.lower() for p in path.parts]

    def _pick_manual_video(self, scan_root: Path, codename: Optional[str], source_type: str) -> Optional[Path]:
        if source_type == "ipk":
            candidates = [
                p for p in scan_root.rglob("*.webm")
                if "mappreview" not in p.name.lower() and "videopreview" not in p.name.lower()
            ]
        else:
            candidates = [
                p for p in scan_root.glob("*.webm")
                if "mappreview" not in p.name.lower() and "videopreview" not in p.name.lower()
            ]

        if not candidates:
            return None

        if codename:
            scoped = [p for p in candidates if self._matches_codename(p, codename)]
            if scoped:
                candidates = scoped

        for quality in ["ULTRA_HD", "ULTRA", "HIGH_HD", "HIGH", "MID_HD", "MID", "LOW_HD", "LOW"]:
            suffix = f"_{quality}.webm"
            for path in candidates:
                if path.name.upper().endswith(suffix):
                    return path
        return candidates[0]

    def _pick_manual_audio(self, scan_root: Path, codename: Optional[str], source_type: str) -> Optional[Path]:
        if source_type == "ipk":
            priority = ("*.wav", "*.wav.ckd", "*.ogg")
        else:
            priority = ("*.ogg", "*.wav", "*.wav.ckd")

        for pattern in priority:
            top_hits = [p for p in scan_root.glob(pattern) if "audiopreview" not in p.name.lower()]
            if codename:
                scoped = [p for p in top_hits if self._matches_codename(p, codename)]
                if scoped:
                    return scoped[0]
            elif top_hits:
                return top_hits[0]

        for pattern in priority:
            recursive_hits = [p for p in scan_root.rglob(pattern) if "audiopreview" not in p.name.lower()]
            recursive_hits = [
                p
                for p in recursive_hits
                if "autodance" not in str(p).lower() and not p.name.lower().startswith("amb_")
            ]
            if not recursive_hits:
                continue
            if codename:
                scoped = [p for p in recursive_hits if self._matches_codename(p, codename)]
                if scoped:
                    return scoped[0]
            else:
                return recursive_hits[0]

        return None

    def _discover_manual_folders(self, scan_root: Path) -> dict[str, Optional[Path]]:
        menuart_textures = next(
            (
                p
                for p in scan_root.rglob("textures")
                if p.is_dir() and p.parent.name.lower() == "menuart"
            ),
            None,
        )
        menuart = menuart_textures or next(
            (p for p in scan_root.rglob("menuart") if p.is_dir()),
            None,
        )

        amb = next(
            (
                p
                for p in scan_root.rglob("amb")
                if p.is_dir() and p.parent.name.lower() == "audio"
            ),
            None,
        )

        return {
            "moves": next((p for p in scan_root.rglob("moves") if p.is_dir()), None),
            "pictos": next((p for p in scan_root.rglob("pictos") if p.is_dir()), None),
            "menuart": menuart,
            "amb": amb,
        }

    def _resolve_scan_root(self, root: Path, source_type: str) -> Path:
        """Prefer codename folder under world/maps for IPK-oriented scans."""
        if source_type != "ipk":
            return root

        world_maps = root / "world" / "maps"
        if world_maps.is_dir():
            candidates = [d for d in world_maps.iterdir() if d.is_dir()]
            if candidates:
                return sorted(candidates, key=lambda p: p.name.lower())[0]
        return root

    def _on_manual_scan_clicked(self) -> None:
        """Manual re-scan trigger that reuses the root-change scan routine."""
        root_path = self.inputs["manual"]["root"].text().strip()
        if root_path:
            self._on_manual_root_changed(root_path)

    def _find_html_pair(self, folder: Path) -> tuple[Optional[Path], Optional[Path]]:
        """Find Asset and NOHUD HTML files in a folder (ported from V1 behavior)."""
        if not folder.exists() or not folder.is_dir():
            return None, None

        asset: Optional[Path] = None
        nohud: Optional[Path] = None
        html_files = sorted(
            [
                p
                for p in folder.iterdir()
                if p.is_file() and p.suffix.lower() in {".html", ".htm"}
            ],
            key=lambda p: p.name.lower(),
        )

        for html in html_files:
            lower = html.name.lower()
            if "nohud" in lower and nohud is None:
                nohud = html
            elif "asset" in lower and asset is None:
                asset = html

        # Fallback: if names are unconventional but two or more html files exist.
        if len(html_files) >= 2:
            if asset is None:
                asset = next((h for h in html_files if h != nohud), html_files[0])
            if nohud is None:
                nohud = next((h for h in html_files if h != asset), html_files[-1])

        return asset, nohud

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def current_mode(self) -> str:
        return MODE_LABELS[self._mode_combo.currentIndex()]

    @property
    def current_mode_index(self) -> int:
        return self._mode_combo.currentIndex()

    @property
    def manual_source_type(self) -> str:
        if not hasattr(self, "_manual_source_combo"):
            return "jdu"
        return self._manual_source_combo.currentText().strip().lower()
