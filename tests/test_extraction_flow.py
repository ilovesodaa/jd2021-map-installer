import pytest
import os
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch
from jd2021_installer.extractors.web_playwright import WebPlaywrightExtractor

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
