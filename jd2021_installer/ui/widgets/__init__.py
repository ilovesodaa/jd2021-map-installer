"""Reusable PyQt6 custom widgets.

All widgets are imported here for convenient access::

    from jd2021_installer.ui.widgets import (
        ModeSelectorWidget,
        ConfigWidget,
        ActionWidget,
        ProgressLogWidget,
        SyncRefinementWidget,
    )
"""

from jd2021_installer.ui.widgets.action_panel import ActionWidget
from jd2021_installer.ui.widgets.config_panel import ConfigWidget
from jd2021_installer.ui.widgets.feedback_panel import ProgressLogWidget, StepStatus
from jd2021_installer.ui.widgets.mode_selector import ModeSelectorWidget
from jd2021_installer.ui.widgets.sync_refinement import SyncRefinementWidget
from jd2021_installer.ui.widgets.log_console import LogConsoleWidget

__all__ = [
    "ActionWidget",
    "ConfigWidget",
    "ModeSelectorWidget",
    "ProgressLogWidget",
    "StepStatus",
    "SyncRefinementWidget",
    "LogConsoleWidget",
]
