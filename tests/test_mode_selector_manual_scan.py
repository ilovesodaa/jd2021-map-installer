from pathlib import Path

from jd2021_installer.ui.widgets.mode_selector import (
    FileRowWidget,
    ModeSelectorWidget,
    MODE_HTML,
    MODE_JDNEXT,
)


def test_pick_manual_tape_accepts_uncooked_dtape_and_ktape(qtbot, tmp_path: Path):
    root = tmp_path / "source"
    timeline = root / "world" / "maps" / "mapx" / "timeline"
    timeline.mkdir(parents=True)

    dtape = timeline / "mapx_TML_Dance.dtape"
    ktape = timeline / "mapx_TML_Karaoke.ktape"
    dtape.write_text("params = {}", encoding="utf-8")
    ktape.write_text("params = {}", encoding="utf-8")

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    dance = widget._pick_manual_tape(root, "mapx", "mixed", tape_kind="dance")
    karaoke = widget._pick_manual_tape(root, "mapx", "mixed", tape_kind="karaoke")

    assert dance == dtape
    assert karaoke == ktape


def test_pick_manual_tape_ignores_adtape_for_dance(qtbot, tmp_path: Path):
    root = tmp_path / "source"
    timeline = root / "world" / "maps" / "mapx" / "timeline"
    timeline.mkdir(parents=True)

    # Should be ignored for dance selection
    adtape = timeline / "mapx_adtape.dtape"
    adtape.write_text("params = {}", encoding="utf-8")

    # Valid dance tape
    dtape = timeline / "mapx_TML_Dance.dtape"
    dtape.write_text("params = {}", encoding="utf-8")

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    dance = widget._pick_manual_tape(root, "mapx", "mixed", tape_kind="dance")
    assert dance == dtape


def test_infer_manual_codename_from_world_maps_single_child(qtbot, tmp_path: Path):
    root = tmp_path / "mixed_source"
    (root / "world" / "maps" / "koi").mkdir(parents=True)

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    inferred = widget._infer_manual_codename(root)
    assert inferred == "koi"


def test_pick_manual_audio_from_nonstandard_root(qtbot, tmp_path: Path):
    root = tmp_path / "mixed_source"
    root.mkdir(parents=True)

    # Top-level media + nested map payload (common mixed/non-standard layout).
    top_audio = root / "Koi.ogg"
    top_audio.write_bytes(b"dummy")
    (root / "world" / "maps" / "koi" / "timeline").mkdir(parents=True)

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    # Root should stay root (not forcibly narrowed to world/maps/koi).
    scan_root = widget._resolve_scan_root(root, "auto")
    assert scan_root == root

    picked = widget._pick_manual_audio(scan_root, "koi", "auto")
    assert picked == top_audio


def test_manual_layout_detection_shows_jdu_fields_and_autofills_html(qtbot, tmp_path: Path):
    root = tmp_path / "jdu_source"
    root.mkdir(parents=True)
    cover_generic = root / "mapx_cover_generic.tga.ckd"
    coach_1 = root / "mapx_coach_1.tga.ckd"
    cover_generic.write_bytes(b"ckd")
    coach_1.write_bytes(b"ckd")

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)
    widget._manual_source_combo.setCurrentIndex(0)  # JDU

    widget._on_manual_root_changed(str(root))

    assert not widget._manual_required_group.isHidden()
    assert widget._manual_tapes_group.isHidden()
    assert not widget._manual_assets_group.isHidden()
    assert widget._manual_row_amb.isHidden()
    assert widget._manual_row_menuart.isHidden()
    assert not widget._manual_menuart_group.isHidden()
    assert not widget._manual_jdu_menuart_rows["jdu_menuart_cover_generic"].isHidden()
    assert not widget._manual_jdu_menuart_rows["jdu_menuart_coach1"].isHidden()
    assert widget._manual_jdu_menuart_rows["jdu_menuart_banner"].isHidden()
    assert widget._manual_jdu_menuart_rows["jdu_menuart_coach2"].isHidden()


def test_manual_layout_detection_shows_ipk_fields_and_autofills_scene_files(qtbot, tmp_path: Path):
    root = tmp_path / "ipk_source"
    (root / "world" / "maps" / "mapx").mkdir(parents=True)

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)
    widget._manual_source_combo.setCurrentIndex(1)  # IPK

    widget._on_manual_root_changed(str(root))

    assert not widget._manual_required_group.isHidden()
    assert not widget._manual_tapes_group.isHidden()
    assert not widget._manual_assets_group.isHidden()
    assert not widget._manual_row_amb.isHidden()
    assert not widget._manual_row_menuart.isHidden()
    assert widget._manual_menuart_group.isHidden()
    assert widget._manual_jdu_menuart_rows["jdu_menuart_cover_generic"].isHidden()


def test_manual_source_mixed_shows_jdu_and_ipk_relevant_controls(qtbot, tmp_path: Path):
    root = tmp_path / "mixed_source"
    (root / "world" / "maps" / "mapx").mkdir(parents=True)
    (root / "asset_mapx.html").write_text("<html></html>", encoding="utf-8")
    (root / "nohud_mapx.html").write_text("<html></html>", encoding="utf-8")

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)
    widget._manual_source_combo.setCurrentIndex(2)  # Mixed

    widget._on_manual_root_changed(str(root))

    assert not widget._manual_menuart_group.isHidden()
    assert not widget._manual_tapes_group.isHidden()
    assert not widget._manual_row_amb.isHidden()
    assert not widget._manual_row_menuart.isHidden()


def test_manual_root_change_clears_previous_values(qtbot, tmp_path: Path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir(parents=True)
    second_root.mkdir(parents=True)

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    widget.inputs["manual"]["audio"].setText("C:/tmp/old.ogg")
    widget.inputs["manual"]["menuart"].setText("C:/tmp/old_menuart")
    widget.inputs["manual"]["jdu_menuart_coach1"].setText("C:/tmp/old_coach.tga.ckd")

    widget._on_manual_root_changed(str(first_root))
    widget._on_manual_root_changed(str(second_root))

    assert widget.inputs["manual"]["audio"].text() == ""
    assert widget.inputs["manual"]["menuart"].text() == ""
    assert widget.inputs["manual"]["jdu_menuart_coach1"].text() == ""


def test_manual_root_clear_does_not_crash_or_leave_stale_values(qtbot, tmp_path: Path):
    root = tmp_path / "source"
    root.mkdir(parents=True)

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    widget.inputs["manual"]["audio"].setText("C:/tmp/old.ogg")
    widget.inputs["manual"]["menuart"].setText("C:/tmp/old_menuart")
    widget.inputs["manual"]["root"].setText(str(root))
    widget._on_manual_root_changed("")

    assert widget.inputs["manual"]["root"].text() == ""
    assert widget.inputs["manual"]["audio"].text() == ""
    assert widget.inputs["manual"]["menuart"].text() == ""


def test_file_row_clear_button_clears_value_and_emits_empty(qtbot):
    row = FileRowWidget("Audio File:")
    qtbot.addWidget(row)

    emitted: list[str] = []
    row.path_changed.connect(emitted.append)

    row.line_edit.setText("C:/tmp/test.ogg")
    row._clear()

    assert row.line_edit.text() == ""
    assert emitted and emitted[-1] == ""


def test_jdnext_mode_reports_codenames_as_target(qtbot):
    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    widget._mode_combo.setCurrentIndex(MODE_JDNEXT)
    widget.inputs["jdnext"]["codenames"].setText("TelephoneALT,MapB")

    state = widget.get_current_state()
    assert state["mode_key"] == "jdnext"
    assert state["target"] == "TelephoneALT,MapB"


def test_set_mode_codenames_updates_jdnext_input(qtbot):
    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)

    widget.set_mode_codenames("jdnext", "TelephoneALT")

    assert widget.inputs["jdnext"]["codenames"].text() == "TelephoneALT"


def test_html_autofill_updates_counterpart_on_second_selection(qtbot, tmp_path: Path, monkeypatch):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir(parents=True)
    second.mkdir(parents=True)

    first_asset = first / "asset_mapx.html"
    first_nohud = first / "nohud_mapx.html"
    second_asset = second / "asset_mapy.html"
    second_nohud = second / "nohud_mapy.html"
    for path in (first_asset, first_nohud, second_asset, second_nohud):
        path.write_text("<html></html>", encoding="utf-8")

    widget = ModeSelectorWidget()
    qtbot.addWidget(widget)
    widget._mode_combo.setCurrentIndex(MODE_HTML)

    html_page = widget._stack.widget(MODE_HTML)
    rows = html_page.findChildren(FileRowWidget)
    assert len(rows) >= 2
    asset_row, nohud_row = rows[0], rows[1]

    selected_paths = iter(
        [
            (str(first_asset), "HTML Files (*.html *.htm)"),
            (str(second_asset), "HTML Files (*.html *.htm)"),
        ]
    )

    monkeypatch.setattr(
        "jd2021_installer.ui.widgets.mode_selector.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: next(selected_paths),
    )

    asset_row._browse()
    assert widget.inputs["html"]["asset"].text() == str(first_asset)
    assert widget.inputs["html"]["nohud"].text() == str(first_nohud)

    asset_row._browse()
    assert widget.inputs["html"]["asset"].text() == str(second_asset)
    assert widget.inputs["html"]["nohud"].text() == str(second_nohud)

    # NoHUD->Asset direction should also refresh after a new selection.
    selected_nohud_paths = iter(
        [
            (str(first_nohud), "HTML Files (*.html *.htm)"),
            (str(second_nohud), "HTML Files (*.html *.htm)"),
        ]
    )
    monkeypatch.setattr(
        "jd2021_installer.ui.widgets.mode_selector.QFileDialog.getOpenFileName",
        lambda *args, **kwargs: next(selected_nohud_paths),
    )

    nohud_row._browse()
    assert widget.inputs["html"]["asset"].text() == str(first_asset)
    assert widget.inputs["html"]["nohud"].text() == str(first_nohud)

    nohud_row._browse()
    assert widget.inputs["html"]["asset"].text() == str(second_asset)
    assert widget.inputs["html"]["nohud"].text() == str(second_nohud)
