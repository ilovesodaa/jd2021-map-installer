"""Custom exception hierarchy for the JD2021 Map Installer.

All pipeline stages raise these typed exceptions so the GUI/controller
layer can present precise error messages to the user.
"""


class JDInstallerError(Exception):
    """Base exception for all installer errors."""


# ---------------------------------------------------------------------------
# Extraction errors
# ---------------------------------------------------------------------------

class ExtractionError(JDInstallerError):
    """Failed to extract map data from a source."""


class IPKExtractionError(ExtractionError):
    """Failed to extract or parse an IPK archive."""


class WebExtractionError(ExtractionError):
    """Failed to scrape map data from the web."""


class DownloadError(ExtractionError):
    """Network download failed (timeout, 403, 404, rate-limit, etc.)."""

    def __init__(self, message: str, url: str = "", http_code: int = 0):
        super().__init__(message)
        self.url = url
        self.http_code = http_code


# ---------------------------------------------------------------------------
# Parsing / normalization errors
# ---------------------------------------------------------------------------

class ParseError(JDInstallerError):
    """Failed to parse a CKD or other data file."""


class BinaryCKDParseError(ParseError):
    """Binary CKD decompilation failed."""


class NormalizationError(JDInstallerError):
    """Failed to normalize extracted data into NormalizedMapData."""


class ValidationError(NormalizationError):
    """Normalized data failed validation (missing required fields)."""


# ---------------------------------------------------------------------------
# Installation errors
# ---------------------------------------------------------------------------

class InstallationError(JDInstallerError):
    """Failed to write installable game files."""


class MediaProcessingError(InstallationError):
    """FFmpeg or Pillow processing failed."""


class GameWriterError(InstallationError):
    """Failed to write .trk/.tpl/.isc files to game directory."""


class InsufficientDiskSpaceError(InstallationError):
    """Not enough free disk space to install the map."""
