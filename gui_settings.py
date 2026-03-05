"""Settings dialog, quickstart hint, and post-apply cleanup for the GUI installer.

Extracted from MapInstallerGUI to reduce the size of gui_installer.py.
"""

import glob
import os
import shutil
import tkinter as tk
from tkinter import ttk, messagebox

from log_config import get_logger
import map_installer

logger = get_logger("gui_settings")


# ---------------------------------------------------------------------------
# Quickstart hint
# ---------------------------------------------------------------------------

def show_quickstart_if_needed(root, settings):
    """Display a short beginner hint once (or until disabled in settings).

    Modifies *settings* in-place and persists the change if shown.
    """
    if not settings.get("show_quickstart_on_launch", True):
        return
    if settings.get("quickstart_seen", False):
        return

    messagebox.showinfo(
        "Quick Start",
        "Fastest path for first-time users:\n\n"
        "1) Enter Codename\n"
        "2) Click Fetch & Install\n"
        "3) Use Apply & Finish at the end\n\n"
        "No manual HTML browsing is required for this flow."
    )
    settings["quickstart_seen"] = True
    map_installer.save_settings(settings)


# ---------------------------------------------------------------------------
# Settings dialog
# ---------------------------------------------------------------------------

def open_settings_dialog(root, settings, on_save):
    """Open a modal settings dialog.

    Args:
        root: Parent Tk window.
        settings: Current settings dict (read-only -- a fresh copy is loaded).
        on_save: Callback ``fn(new_settings)`` called when the user clicks Save.
    """
    # Load fresh settings so we don't depend on caller's stale copy
    settings = map_installer.load_settings()

    # Lazy import to avoid circular dependency (ToolTip lives in gui_installer)
    from gui_installer import ToolTip

    dlg = tk.Toplevel(root)
    dlg.title("Installer Settings")
    dlg.geometry("520x360")
    dlg.resizable(False, False)
    dlg.transient(root)
    dlg.grab_set()

    frame = ttk.Frame(dlg, padding=12)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Installer Settings",
              font=("Consolas", 11, "bold")).pack(anchor="w", pady=(0, 8))

    # Skip preflight
    skip_pf_var = tk.BooleanVar(value=settings["skip_preflight"])
    skip_pf_cb = ttk.Checkbutton(
        frame, text="Skip pre-flight checks",
        variable=skip_pf_var)
    skip_pf_cb.pack(anchor="w", pady=2)
    ToolTip(skip_pf_cb,
            "Skip pre-flight checks if they've already passed.\n"
            "The Install button will be enabled immediately on launch.")

    # Suppress offset notification
    suppress_var = tk.BooleanVar(value=settings["suppress_offset_notification"])
    suppress_cb = ttk.Checkbutton(
        frame, text="Suppress offset refinement notification",
        variable=suppress_var)
    suppress_cb.pack(anchor="w", pady=2)
    ToolTip(suppress_cb,
            "Don't show the 'offset refinement is needed' popup\n"
            "after the installation pipeline completes.")

    # Cleanup behavior
    cleanup_frame = ttk.Frame(frame)
    cleanup_frame.pack(anchor="w", pady=(4, 2), fill="x")
    ttk.Label(cleanup_frame, text="After Apply & Finish:").pack(
        side="left", padx=(0, 8))

    cleanup_mode_var = tk.StringVar(value=settings.get("cleanup_behavior", "ask"))
    cleanup_mode_combo = ttk.Combobox(
        cleanup_frame,
        textvariable=cleanup_mode_var,
        values=["ask", "delete", "keep"],
        state="readonly",
        width=12)
    cleanup_mode_combo.pack(side="left")
    ToolTip(
        cleanup_mode_combo,
        "ask: show prompt after apply\n"
        "delete: auto-delete intermediate files immediately\n"
        "keep: keep files and never show cleanup prompt"
    )

    # Notification preference: preflight success popup
    preflight_popup_var = tk.BooleanVar(
        value=settings.get("show_preflight_success_popup", True))
    preflight_popup_cb = ttk.Checkbutton(
        frame, text="Show 'Pre-flight passed' popup",
        variable=preflight_popup_var)
    preflight_popup_cb.pack(anchor="w", pady=2)
    ToolTip(preflight_popup_cb,
            "If disabled, passing pre-flight will only enable the Install button\n"
            "without opening a popup.")

    # Notification preference: quick-start hint
    quickstart_var = tk.BooleanVar(
        value=settings.get("show_quickstart_on_launch", True))
    quickstart_cb = ttk.Checkbutton(
        frame, text="Show quick-start hint on launch",
        variable=quickstart_var)
    quickstart_cb.pack(anchor="w", pady=2)
    ToolTip(quickstart_cb,
            "Shows a short beginner guide at startup.\n"
            "Helpful for users who skip documentation.")

    # Default quality
    quality_frame = ttk.Frame(frame)
    quality_frame.pack(anchor="w", pady=(8, 2))
    ttk.Label(quality_frame, text="Default video quality:").pack(
        side="left", padx=(0, 8))
    quality_var = tk.StringVar(value=settings["default_quality"])
    quality_combo = ttk.Combobox(
        quality_frame, textvariable=quality_var,
        values=["ultra_hd", "ultra", "high_hd", "high",
                "mid_hd", "mid", "low_hd", "low"],
        state="readonly", width=12)
    quality_combo.pack(side="left")

    # Buttons
    btn_frame = ttk.Frame(frame)
    btn_frame.pack(side="bottom", pady=(16, 0))

    def _save():
        old_quickstart = settings.get("show_quickstart_on_launch", True)
        new_quickstart = quickstart_var.get()
        new_settings = {
            "skip_preflight": skip_pf_var.get(),
            "suppress_offset_notification": suppress_var.get(),
            "cleanup_behavior": cleanup_mode_var.get(),
            "default_quality": quality_var.get(),
            "show_preflight_success_popup": preflight_popup_var.get(),
            "show_quickstart_on_launch": new_quickstart,
            "quickstart_seen": settings.get("quickstart_seen", False),
        }

        # If quick-start hints were re-enabled, show them again next launch.
        if new_quickstart and not old_quickstart:
            new_settings["quickstart_seen"] = False

        map_installer.save_settings(new_settings)
        on_save(new_settings)
        print("    Settings saved.")
        dlg.destroy()

    ttk.Button(btn_frame, text="Save", command=_save, width=10).pack(
        side="left", padx=(0, 8))
    ttk.Button(btn_frame, text="Cancel", command=dlg.destroy, width=10).pack(
        side="left")


# ---------------------------------------------------------------------------
# Post-apply cleanup
# ---------------------------------------------------------------------------

def prompt_cleanup(root, state, settings):
    """Ask user whether to delete downloaded source files after apply.

    Args:
        root: Parent Tk window (for messagebox modality).
        state: PipelineState (needs ``download_dir`` and ``map_name``).
        settings: Current settings dict (reads ``cleanup_behavior``).
    """
    dl_dir = getattr(state, 'download_dir', None)
    if not dl_dir or not os.path.isdir(dl_dir):
        return

    cleanup_behavior = settings.get("cleanup_behavior", "ask")

    if cleanup_behavior == "delete":
        answer = True
    elif cleanup_behavior == "keep":
        return
    else:
        answer = messagebox.askyesno(
            "Clean Up Downloads",
            f"Delete downloaded source files for '{state.map_name}' to save disk space?\n\n"
            "This removes extracted scenes and decoded intermediates.\n"
            "Audio (.ogg), video (.webm), and IPK data are kept in case\n"
            "you need to reinstall or adjust the offset later.\n\n"
            "This cannot be undone.")

    if not answer:
        return

    removed = 0

    # 1. Scene ZIPs
    for f in glob.glob(os.path.join(dl_dir, "*_MAIN_SCENE_*.zip")):
        try:
            os.remove(f)
            removed += 1
        except OSError as e:
            logger.warning("Could not delete %s: %s", f, e)

    # 2. Extracted scene directories
    for d in glob.glob(os.path.join(dl_dir, "*_MAIN_SCENE_*")):
        if os.path.isdir(d):
            try:
                shutil.rmtree(d)
                removed += 1
            except OSError as e:
                logger.warning("Could not remove directory %s: %s", d, e)
    extracted_dir = os.path.join(dl_dir, "main_scene_extracted")
    if os.path.isdir(extracted_dir):
        try:
            shutil.rmtree(extracted_dir)
            removed += 1
        except OSError as e:
            logger.warning("Could not remove directory %s: %s", extracted_dir, e)

    # 3. Decoded CKD intermediates (textures already converted to PNG/TGA)
    for f in glob.glob(os.path.join(dl_dir, "*.ckd")):
        try:
            os.remove(f)
            removed += 1
        except OSError as e:
            logger.warning("Could not delete %s: %s", f, e)

    if removed:
        print(f"    Cleaned up {removed} downloaded file(s)/folder(s) for {state.map_name}.")
    else:
        print("    No intermediate files found to clean up.")
