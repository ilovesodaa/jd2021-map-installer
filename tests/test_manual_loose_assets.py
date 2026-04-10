from pathlib import Path

import pytest

from jd2021_installer.installers.tape_converter import auto_convert_tapes
from jd2021_installer.installers.texture_decoder import decode_pictograms


def test_auto_convert_tapes_accepts_loose_dtape_and_ktape(tmp_path: Path):
    source = tmp_path / "src" / "world" / "maps" / "mapx" / "timeline"
    source.mkdir(parents=True)

    dance_src = source / "mapx_TML_Dance.dtape"
    karaoke_src = source / "mapx_TML_Karaoke.ktape"
    dance_src.write_text('params = { NAME = "Tape" }', encoding="utf-8")
    karaoke_src.write_text('params = { NAME = "Tape" }', encoding="utf-8")

    target = tmp_path / "out"

    converted = auto_convert_tapes(tmp_path / "src", target, "mapx")

    dance_out = target / "timeline" / "mapx_TML_Dance.dtape"
    karaoke_out = target / "timeline" / "mapx_TML_Karaoke.ktape"

    assert converted == 2
    assert dance_out.exists()
    assert karaoke_out.exists()
    assert dance_out.read_text(encoding="utf-8") == dance_src.read_text(encoding="utf-8")
    assert karaoke_out.read_text(encoding="utf-8") == karaoke_src.read_text(encoding="utf-8")


def test_decode_pictograms_copies_loose_png(tmp_path: Path):
    picto_dir = tmp_path / "pictos"
    picto_dir.mkdir(parents=True)

    # Minimal valid PNG file header + IHDR/IEND chunk sequence for test purposes.
    png_bytes = (
        b"\x89PNG\r\n\x1a\n"
        b"\x00\x00\x00\rIHDR"
        b"\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00"
        b"\x90wS\xde"
        b"\x00\x00\x00\x0cIDAT\x08\xd7c\xf8\xff\xff?\x00\x05\xfe\x02\xfeA\x0b\xb5\x9d"
        b"\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    src = picto_dir / "mapx_picto_001.png"
    src.write_bytes(png_bytes)

    out_dir = tmp_path / "timeline" / "pictos"
    decoded = decode_pictograms(picto_dir, out_dir)

    pil_image = pytest.importorskip("PIL.Image")

    out_file = out_dir / "mapx_picto_001.png"
    assert decoded == 1
    assert out_file.exists()
    with pil_image.open(src) as src_img, pil_image.open(out_file) as out_img:
        assert out_img.size == src_img.size == (1, 1)
        assert list(out_img.getdata()) == list(src_img.getdata())


def test_decode_pictograms_can_place_on_bottom_center_canvas(tmp_path: Path):
    pil_image = pytest.importorskip("PIL.Image")

    picto_dir = tmp_path / "pictos"
    picto_dir.mkdir(parents=True)

    src = picto_dir / "mapx_picto_001.png"
    img = pil_image.new("RGBA", (200, 400), (255, 255, 255, 255))
    img.save(src)

    out_dir = tmp_path / "timeline" / "pictos"
    decoded = decode_pictograms(picto_dir, out_dir, canvas_size=512)

    out_file = out_dir / "mapx_picto_001.png"
    assert decoded == 1
    assert out_file.exists()

    with pil_image.open(out_file) as out_img:
        assert out_img.size == (512, 512)
        bbox = out_img.getbbox()
        assert bbox == (156, 112, 356, 512)


def test_decode_pictograms_temporarily_normalizes_judas_to_512_max(tmp_path: Path):
    pil_image = pytest.importorskip("PIL.Image")

    picto_dir = tmp_path / "pictos"
    picto_dir.mkdir(parents=True)

    src = picto_dir / "judas_picto_test.png"
    img = pil_image.new("RGBA", (200, 400), (255, 255, 255, 255))
    img.save(src)

    # Output path shape mirrors real install layout expected by temporary Judas scope.
    out_dir = tmp_path / "Judas" / "timeline" / "pictos"
    decoded = decode_pictograms(picto_dir, out_dir, canvas_size=512)

    out_file = out_dir / "judas_picto_test.png"
    assert decoded == 1
    assert out_file.exists()

    with pil_image.open(out_file) as out_img:
        assert out_img.size == (512, 512)
        assert out_img.getbbox() == (156, 112, 356, 512)
