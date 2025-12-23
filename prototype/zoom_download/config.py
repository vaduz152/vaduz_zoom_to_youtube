"""Configuration settings for Zoom to YouTube downloader."""
import os
from datetime import timedelta
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in this directory
# This ensures .env in prototype/zoom_download/ is loaded
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Date range for fetching recordings (depth of meetings requested)
# Number of days to look back from today
RECORDINGS_DATE_RANGE_DAYS = int(os.getenv("RECORDINGS_DATE_RANGE_DAYS", "365"))

# How many last meetings to process
# Set to None or empty string to process all available recordings
_last_meetings = os.getenv("LAST_MEETINGS_TO_PROCESS", "3")
LAST_MEETINGS_TO_PROCESS = int(_last_meetings) if _last_meetings and _last_meetings.lower() != "none" else None

# Folder name template for meeting directories
# Available placeholders:
#   {date} - Date in YYYY-MM-DD format
#   {time} - Time in HH-MM format (Windows-compatible)
#   {topic} - Meeting topic/title
#   {date_time} - Date and time combined (YYYY-MM-DD HH-MM)
FOLDER_NAME_TEMPLATE = os.getenv(
    "FOLDER_NAME_TEMPLATE",
    "{date} {time} - {topic}"
)

# Output directory for downloads
# Default is "../../test_downloads" (relative to this file, pointing to repo root)
# Or set DOWNLOAD_DIR env var to override
_default_download_dir = os.getenv("DOWNLOAD_DIR")
if _default_download_dir is None:
    # Resolve relative to repo root (two levels up from prototype/zoom_download/)
    repo_root = Path(__file__).parent.parent.parent
    _default_download_dir = str(repo_root / "test_downloads")
DOWNLOAD_DIR = _default_download_dir

# Minimum video length in seconds
# Videos shorter than this will be skipped
# Set to 0 to download all videos regardless of length
MIN_VIDEO_LENGTH_SECONDS = int(os.getenv("MIN_VIDEO_LENGTH_SECONDS", "60"))

