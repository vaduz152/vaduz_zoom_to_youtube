"""Configuration settings for Zoom to YouTube automation."""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file in root directory
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)


def get_env(name: str, default: str = None) -> str:
    """Get environment variable with optional default."""
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


# Zoom OAuth settings
ZOOM_CLIENT_ID = get_env("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = get_env("ZOOM_CLIENT_SECRET")
ZOOM_REDIRECT_URI = get_env("ZOOM_REDIRECT_URI", "http://localhost:8080/redirect")
ZOOM_USER_ID = get_env("ZOOM_USER_ID")
ZOOM_REFRESH_TOKEN_FILE = Path(".zoom_refresh_token").resolve()

# YouTube OAuth settings
YOUTUBE_CLIENT_ID = get_env("YOUTUBE_CLIENT_ID")
YOUTUBE_CLIENT_SECRET = get_env("YOUTUBE_CLIENT_SECRET")
YOUTUBE_TOKEN_FILE = Path("youtube_token.json").resolve()
YOUTUBE_DEFAULT_DESCRIPTION = get_env("YOUTUBE_DEFAULT_DESCRIPTION", "Uploaded via automation")
YOUTUBE_DEFAULT_TAGS = get_env("YOUTUBE_DEFAULT_TAGS", "zoom,meeting,recording")
YOUTUBE_CATEGORY_ID = get_env("YOUTUBE_CATEGORY_ID", "22")
# Optional: Pre-select a specific Google account (email address)
# This helps when you have multiple Google accounts logged in
YOUTUBE_LOGIN_HINT = os.getenv("YOUTUBE_LOGIN_HINT", None)

# Discord webhook settings
DISCORD_WEBHOOK_URL = get_env("DISCORD_WEBHOOK_URL")

# Processing configuration
LAST_MEETINGS_TO_PROCESS = int(get_env("LAST_MEETINGS_TO_PROCESS", "3"))
MIN_VIDEO_LENGTH_SECONDS = int(get_env("MIN_VIDEO_LENGTH_SECONDS", "60"))
VIDEO_RETENTION_DAYS = int(get_env("VIDEO_RETENTION_DAYS", "10"))
ERROR_NOTIFICATION_THRESHOLD = int(get_env("ERROR_NOTIFICATION_THRESHOLD", "2"))

# Paths
DOWNLOAD_DIR = Path(get_env("DOWNLOAD_DIR", "./downloaded_videos")).resolve()
CSV_TRACKER_PATH = Path(get_env("CSV_TRACKER_PATH", "./processed_recordings.csv")).resolve()
LOG_FILE = Path(get_env("LOG_FILE", "./zoom_to_youtube.log")).resolve()

# Gemini API (transcription & title generation)
GEMINI_API_KEY = get_env("GEMINI_API_KEY", "")
GEMINI_MODEL = get_env("GEMINI_MODEL", "gemini-3.1-pro-preview")
TRANSCRIPTION_PROMPT_PATH = Path(get_env("TRANSCRIPTION_PROMPT_PATH", "./meeting-transcripts/prompts/transcription_prompt.txt")).resolve()
TITLE_PROMPT_PATH = Path(get_env("TITLE_PROMPT_PATH", "./meeting-transcripts/prompts/title_prompt.txt")).resolve()
SUMMARY_PROMPT_PATH = Path(get_env("SUMMARY_PROMPT_PATH", "./meeting-transcripts/prompts/summary_prompt.txt")).resolve()
MAX_TRANSCRIPTION_DURATION = int(get_env("MAX_TRANSCRIPTION_DURATION", "7200"))
GEMINI_INPUT_PRICE_PER_MTOK = float(get_env("GEMINI_INPUT_PRICE_PER_MTOK", "1.25"))
GEMINI_OUTPUT_PRICE_PER_MTOK = float(get_env("GEMINI_OUTPUT_PRICE_PER_MTOK", "10.0"))

# Transcript storage (GitHub repo)
TRANSCRIPTS_REPO_URL = get_env("TRANSCRIPTS_REPO_URL", "")
TRANSCRIPTS_REPO_PATH = Path(get_env("TRANSCRIPTS_REPO_PATH", "./meeting-transcripts")).resolve()
TRANSCRIPTS_GITHUB_REPO = get_env("TRANSCRIPTS_GITHUB_REPO", "")

# Discord notification template
DISCORD_NOTIFICATION_TEMPLATE_PATH = Path(get_env(
    "DISCORD_NOTIFICATION_TEMPLATE_PATH", "./meeting-transcripts/prompts/discord_notification.txt"
)).resolve()

# Local video processing
LOCAL_VIDEOS_DIR = Path(get_env("LOCAL_VIDEOS_DIR", "./videos_to_process")).resolve()

# Ensure download directory exists
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

