from __future__ import annotations

import logging

from jd2021_installer.ui.widgets.log_console import LogConsoleWidget, SUCCESS_LEVEL


def test_resolve_level_recognizes_developer_profile_prefixes(qtbot) -> None:
    widget = LogConsoleWidget()
    qtbot.addWidget(widget)

    line = "12:34:56 [CRITICAL] jd2021.ui.main_window: Boom"
    assert widget._resolve_level_for_line(line, logging.INFO) == logging.CRITICAL

    line = "12:34:56 [WARNING] jd2021.ui.main_window: Heads up"
    assert widget._resolve_level_for_line(line, logging.INFO) == logging.WARNING


def test_normalize_line_text_strips_logger_prefixes(qtbot) -> None:
    widget = LogConsoleWidget()
    qtbot.addWidget(widget)

    developer_line = "12:34:56 [INFO ] jd2021.ui.main_window: Started"
    normalized = widget._normalize_line_text(developer_line, logging.INFO)
    assert normalized == "INFO: Started"

    bracketed_line = "[WARNING] Low disk space"
    normalized_warn = widget._normalize_line_text(bracketed_line, logging.WARNING)
    assert normalized_warn == "WARNING: Low disk space"


def test_prefix_and_colors_cover_all_levels(qtbot) -> None:
    widget = LogConsoleWidget()
    qtbot.addWidget(widget)

    assert widget._prefix_for_level(logging.DEBUG) == "DEBUG"
    assert widget._prefix_for_level(logging.INFO) == "INFO"
    assert widget._prefix_for_level(logging.WARNING) == "WARNING"
    assert widget._prefix_for_level(logging.ERROR) == "ERROR"
    assert widget._prefix_for_level(logging.CRITICAL) == "CRITICAL"
    assert widget._prefix_for_level(SUCCESS_LEVEL) == "SUCCESS"

    assert widget._line_color(logging.WARNING) == "#E67E22"
    assert widget._line_color(logging.ERROR) == "#C62828"
    assert widget._line_color(logging.CRITICAL) == "#8E1B1B"
    assert widget._line_color(SUCCESS_LEVEL) == "#1E8E3E"
