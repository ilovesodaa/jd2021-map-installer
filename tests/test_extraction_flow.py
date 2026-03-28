import pytest
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from jd2021_installer.core.config import AppConfig
from jd2021_installer.extractors.web_playwright import (
    WebPlaywrightExtractor,
    _classify_urls,
    download_files,
)

def test_extract_scene_zips_unpacks_ipk(tmp_path):
    """Verify that _extract_scene_zips unpacks any .ipk files found after ZIP extraction."""
    # Setup: Create a dummy ZIP file
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    
    zip_filename = "Test_MAIN_SCENE_DURANGO.zip"
    zip_path = output_dir / zip_filename
    
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("dummy.txt", "content")
    
    # Create a dummy IPK file in the output_dir to simulate it being extracted from the ZIP
    ipk_path = output_dir / "Test.ipk"
    ipk_path.write_text("dummy ipk content")
    
    with patch("zipfile.ZipFile") as mock_zip, \
         patch("jd2021_installer.extractors.web_playwright.extract_ipk") as mock_extract_ipk:
        
        # Mock zipfile behavior
        mock_zip_instance = mock_zip.return_value.__enter__.return_value
        
        # Execute the extraction logic
        WebPlaywrightExtractor._extract_scene_zips(output_dir)
        
        # Verify ZIP was "extracted" (mocked)
        mock_zip.assert_called()
        mock_zip_instance.extractall.assert_called_with(output_dir)
        
        # Verify IPK was unpacked
        mock_extract_ipk.assert_called_once_with(ipk_path, output_dir)
        
        # Verify IPK was deleted after extraction
        assert not ipk_path.exists()

def test_extract_scene_zips_no_ipk(tmp_path):
    """Verify that _extract_scene_zips does nothing if no .ipk files are found."""
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    zip_path = output_dir / "Test_MAIN_SCENE_DURANGO.zip"
    
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("dummy.txt", "content")

    with patch("zipfile.ZipFile"), \
         patch("jd2021_installer.extractors.web_playwright.extract_ipk") as mock_extract_ipk:
        
        WebPlaywrightExtractor._extract_scene_zips(output_dir)
        
        # No IPK should be extracted
        mock_extract_ipk.assert_not_called()


def test_classify_urls_prefers_x360_scene_zip():
    urls = [
        "https://jd-s3.cdn.ubi.com/public/map/TestMap/TestMap_MAIN_SCENE_DURANGO.zip",
        "https://jd-s3.cdn.ubi.com/public/map/TestMap/TestMap_MAIN_SCENE_X360.zip",
        "https://jd-s3.cdn.ubi.com/public/map/TestMap/TestMap_MAIN_SCENE_NX.zip",
    ]

    classified = _classify_urls(urls, "ULTRA_HD")
    assert classified["mainscene"] is not None
    assert "MAIN_SCENE_X360" in classified["mainscene"]


def test_extract_scene_zips_prefers_x360(tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    (output_dir / "Test_MAIN_SCENE_DURANGO.zip").write_bytes(b"dummy")
    (output_dir / "Test_MAIN_SCENE_X360.zip").write_bytes(b"dummy")

    with patch("zipfile.ZipFile") as mock_zip:
        WebPlaywrightExtractor._extract_scene_zips(output_dir)

    called_path = mock_zip.call_args[0][0]
    assert Path(called_path).name == "Test_MAIN_SCENE_X360.zip"


def test_download_files_respects_retry_after_header(tmp_path, monkeypatch):
    class FakeResponse:
        def __init__(self, status_code, headers=None, chunks=None):
            self.status_code = status_code
            self.headers = headers or {}
            self._chunks = chunks or []

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def iter_content(self, chunk_size=1024 * 1024):
            return iter(self._chunks)

    class FakeSession:
        def __init__(self):
            self.headers = {}
            self._responses = iter(
                [
                    FakeResponse(429, headers={"Retry-After": "7"}),
                    FakeResponse(
                        200,
                        headers={"content-length": "2048"},
                        chunks=[b"x" * 2048],
                    ),
                ]
            )

        def get(self, *args, **kwargs):
            return next(self._responses)

    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))
    monkeypatch.setattr("requests.Session", FakeSession)

    cfg = AppConfig(max_retries=3, retry_base_delay_s=2, inter_request_delay_s=0.0)
    urls = ["https://jd-s3.cdn.ubi.com/public/map/TestMap/TestMap_musictrack.tpl.ckd"]

    downloaded = download_files(urls, tmp_path, "ULTRA_HD", cfg)

    assert "TestMap_musictrack.tpl.ckd" in downloaded
    assert 7 in sleep_calls
