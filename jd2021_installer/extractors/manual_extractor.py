"""Manual Extractor for JD2021 Map Installer.

Assembles an extraction directory from a collection of manually-specified
local file paths (audio, video, musictrack, tapes, assets) provided by
the user via the UI.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Dict, Optional

from jd2021_installer.core.exceptions import DownloadError
from jd2021_installer.extractors.base import BaseExtractor

logger = logging.getLogger("jd2021.extractors.manual")


class ManualExtractor(BaseExtractor):
    """Assembles a map directory from manually specified paths."""

    def _warn(self, message: str) -> None:
        self._warnings.append(message)
        logger.warning(message)

    def get_warnings(self) -> list[str]:
        return list(self._warnings)

    def _detect_musictrack(self, root: Path) -> bool:
        codename_lower = self._codename.lower() if self._codename else ""
        for p in root.rglob("*musictrack*.tpl.ckd"):
            if not p.is_file():
                continue
            if not codename_lower:
                return True
            parts_lower = [part.lower() for part in p.parts]
            if codename_lower in parts_lower or p.name.lower().startswith(codename_lower):
                return True
        return False

    def _validate_manual_explicit_inputs(self, root: Optional[Path]) -> None:
        """Validate explicit manual selections before assembling output."""
        provided_files = {k: Path(v) for k, v in self._files.items() if v}
        provided_dirs = {k: Path(v) for k, v in self._dirs.items() if v}

        if not provided_files and not provided_dirs:
            return

        # Required files mirror V1 manual-v2 behavior.
        required_labels = {
            "audio": "Audio file",
            "video": "Video (.webm)",
            "mtrack": "Musictrack CKD",
        }
        missing_required: list[str] = []

        explicit_audio_ok = bool(provided_files.get("audio") and provided_files["audio"].is_file())
        explicit_video_ok = bool(provided_files.get("video") and provided_files["video"].is_file())
        explicit_mtrack_ok = bool(provided_files.get("mtrack") and provided_files["mtrack"].is_file())

        root_audio_ok = False
        root_video_ok = False
        root_mtrack_ok = False
        if root and root.is_dir():
            root_audio_ok, root_video_ok = self._resolve_codename_media(root)
            root_mtrack_ok = self._detect_musictrack(root)

        if not (explicit_audio_ok or root_audio_ok):
            missing_required.append(required_labels["audio"])
        if not (explicit_video_ok or root_video_ok):
            missing_required.append(required_labels["video"])
        if not (explicit_mtrack_ok or root_mtrack_ok):
            missing_required.append(required_labels["mtrack"])

        if missing_required:
            raise DownloadError(
                "Manual mode missing required inputs: " + ", ".join(missing_required) + "."
            )

        optional_file_labels = {
            "sdesc": "Songdesc CKD",
            "dtape": "Dance tape",
            "ktape": "Karaoke tape",
            "mseq": "Mainsequence tape",
        }
        optional_dir_labels = {
            "moves": "Moves directory",
            "pictos": "Pictos directory",
            "menuart": "MenuArt directory",
            "amb": "AMB directory",
        }

        for key, p in provided_files.items():
            if p.is_file():
                continue
            if key in required_labels:
                self._warn(f"Manual override for {required_labels[key]} was not found and will be ignored: {p}")
            else:
                label = optional_file_labels.get(key, key)
                self._warn(f"Manual optional file missing ({label}): {p}")

        for key, p in provided_dirs.items():
            if p.is_dir():
                continue
            label = optional_dir_labels.get(key, key)
            self._warn(f"Manual optional directory missing ({label}): {p}")

    def _resolve_root_dir(self, root: Path) -> Path:
        """Apply source-type specific root resolution for manual mode."""
        return root

    def is_ipk_source(self) -> bool:
        """True when manual mode is operating on unpacked IPK content."""
        return self._source_type == "ipk"

    def _validate_ipk_root(self, root: Path) -> None:
        """Validate codename/root consistency for manual IPK roots."""
        if not self.is_ipk_source():
            return

        candidates = set()

        world_maps = root / "world" / "maps"
        if world_maps.is_dir():
            candidates.update(d.name for d in world_maps.iterdir() if d.is_dir())

        # V1 parity: legacy bundles may use world/jd20XX/<codename>/
        world_root = root / "world"
        if world_root.is_dir():
            for jd_dir in world_root.iterdir():
                if not jd_dir.is_dir():
                    continue
                name = jd_dir.name.lower()
                if not name.startswith("jd"):
                    continue
                if not name[2:].isdigit():
                    continue
                candidates.update(d.name for d in jd_dir.iterdir() if d.is_dir())

        candidates = sorted(candidates)
        if not candidates:
            return

        self.bundle_maps = candidates

        if not self._codename:
            self._codename = candidates[0]
            if len(candidates) > 1:
                logger.warning(
                    "Manual IPK source contains multiple maps; auto-selected first candidate '%s'.",
                    self._codename,
                )
            else:
                logger.info("Inferred manual IPK codename from root: %s", self._codename)
            return

        lower_candidates = {c.lower() for c in candidates}
        if self._codename.lower() not in lower_candidates:
            fallback = candidates[0]
            logger.warning(
                "Manual IPK codename '%s' does not match discovered maps (%s); using '%s'.",
                self._codename,
                ", ".join(candidates),
                fallback,
            )
            self._codename = fallback

    def _resolve_codename_media(self, root: Path) -> tuple[bool, bool]:
        """Return flags for audio/video presence scoped to codename when possible."""
        codename_lower = self._codename.lower() if self._codename else ""

        has_audio = False
        has_video = False
        for p in root.rglob("*"):
            if not p.is_file():
                continue
            name_low = p.name.lower()
            path_low = str(p).lower().replace('\\', '/')

            if "audiopreview" in name_low:
                continue

            if codename_lower:
                in_codename_scope = codename_lower in [part.lower() for part in p.parts]
                if not in_codename_scope and not name_low.startswith(codename_lower):
                    continue

            if name_low.endswith((".ogg", ".wav", ".wav.ckd")):
                if "/amb/" in path_low or "/autodance/" in path_low:
                    continue
                if name_low.startswith("amb_"):
                    continue
                has_audio = True

            if name_low.endswith(".webm") and "mappreview" not in name_low and "videopreview" not in name_low:
                has_video = True

            if has_audio and has_video:
                break

        return has_audio, has_video

    def _validate_root_source_readiness(self, root: Path) -> None:
        """Eagerly validate root-only manual mode to match V1 readiness behavior."""
        has_audio, has_video = self._resolve_codename_media(root)
        has_musictrack = self._detect_musictrack(root)
        missing: list[str] = []

        if self.is_ipk_source():
            has_structure = False
            if (root / "world" / "maps").is_dir():
                has_structure = True
            else:
                world_root = root / "world"
                if world_root.is_dir():
                    has_structure = any(
                        d.is_dir() and d.name.lower().startswith("jd") and d.name[2:].isdigit()
                        for d in world_root.iterdir()
                    )
            if not has_structure:
                missing.append("Unpacked IPK folder must contain world/maps/ or world/jd20XX/.")
        else:
            html_paths = [
                root / "assets.html",
                root / "nohud.html",
            ]
            if not any(p.is_file() for p in html_paths):
                missing.append("Downloaded assets mode requires assets.html or nohud.html.")

        if not has_audio:
            missing.append("Audio (.ogg/.wav/.wav.ckd) not found in source folder.")
        if not has_video:
            missing.append("Gameplay video (.webm) not found in source folder.")
        if not has_musictrack:
            missing.append("Musictrack CKD is required (fatal for config generation).")

        if missing:
            raise DownloadError(" ".join(missing))

    def __init__(
        self,
        codename: str,
        source_type: str = "jdu",
        root_dir: Optional[str] = None,
        files: Optional[Dict[str, str]] = None,
        dirs: Optional[Dict[str, str]] = None,
    ) -> None:
        """Initialize the extractor.

        Args:
            codename: The name of the map.
            root_dir: Optional base directory if files are already bundled.
            files:    Dict of logical name → absolute file path (e.g. dict(audio="...", dtape="...")).
            dirs:     Dict of logical name → absolute directory path for assets (moves, pictos, etc).
        """
        inferred_codename = codename.strip() if codename else ""
        if not inferred_codename and root_dir:
            inferred_codename = Path(root_dir).name.strip()
        self._codename = inferred_codename
        self._source_type = source_type.strip().lower() if source_type else "jdu"
        self._root_dir = Path(root_dir) if root_dir else None
        self._files = files or {}
        self._dirs = dirs or {}
        self._warnings: list[str] = []
        self.bundle_maps: list[str] = []

    def get_codename(self) -> Optional[str]:
        return self._codename or None

    def extract(self, output_dir: Path) -> Path:
        """Copy manual files to the extraction output_dir.

        If a root folder was provided and no granular files were given,
        we can simply return the root folder as the extracted data.
        Otherwise, we assemble a clean directory.
        """
        # If there are NO explicit files/dirs configured but there IS a root,
        # just yield the root directly as the extraction source for the normalizer.
        resolved_root = self._resolve_root_dir(self._root_dir) if self._root_dir and self._root_dir.is_dir() else None
        if resolved_root:
            self._validate_ipk_root(resolved_root)

        if resolved_root and not any(self._files.values()) and not any(self._dirs.values()):
            self._validate_root_source_readiness(resolved_root)
            logger.info(
                "Manual extraction using root dir directly (%s): %s",
                self._source_type,
                resolved_root,
            )
            return resolved_root

        if not self._codename:
            raise DownloadError("Codename is required for manual mode.")

        self._validate_manual_explicit_inputs(resolved_root)

        map_output_dir = output_dir / self._codename
        map_output_dir.mkdir(parents=True, exist_ok=True)
        
        logger.info("Assembling manual files into %s (source_type=%s)", map_output_dir, self._source_type)

        # Base case: copy everything from root if provided, then overwrite with specific files
        if resolved_root:
            logger.info("Copying contents of root dir %s", resolved_root)
            shutil.copytree(resolved_root, map_output_dir, dirs_exist_ok=True)

        # Copy specific files
        for ftype, path_str in self._files.items():
            if not path_str:
                continue
            src = Path(path_str)
            if src.is_file():
                dest = map_output_dir / src.name
                shutil.copy2(src, dest)
                logger.info("Copied manual file: %s", src.name)
            else:
                self._warn(f"Manual file not found and skipped ({ftype}): {src}")

        # Copy specific asset directories
        for dtype, dpath_str in self._dirs.items():
            if not dpath_str:
                continue
            src_dir = Path(dpath_str)
            if src_dir.is_dir():
                dest_dir = map_output_dir / src_dir.name
                shutil.copytree(src_dir, dest_dir, dirs_exist_ok=True)
                logger.info("Copied manual dir: %s", src_dir.name)
            else:
                self._warn(f"Manual directory not found and skipped ({dtype}): {src_dir}")

        return map_output_dir
