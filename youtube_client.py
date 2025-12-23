"""YouTube API client for uploading videos."""
import logging
from pathlib import Path
from typing import List, Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def get_credentials() -> Credentials:
    """Get or refresh YouTube OAuth credentials."""
    token_file = config.YOUTUBE_TOKEN_FILE
    
    creds: Optional[Credentials] = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file.resolve()), scopes=SCOPES)
    
    if creds and creds.valid:
        return creds
    
    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing YouTube credentials...")
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
        return creds
    
    # Need to authorize
    logger.info("YouTube authorization required. Starting OAuth flow...")
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": config.YOUTUBE_CLIENT_ID,
                "client_secret": config.YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    
    # Use login_hint if provided to pre-select account
    # Otherwise use select_account to show account picker
    kwargs = {}
    if config.YOUTUBE_LOGIN_HINT:
        logger.info(f"Using login hint for account: {config.YOUTUBE_LOGIN_HINT}")
        kwargs['login_hint'] = config.YOUTUBE_LOGIN_HINT
        kwargs['prompt'] = 'consent'  # Just consent, no account picker needed
    else:
        logger.info("Opening browser for authorization.")
        kwargs['prompt'] = 'select_account consent'  # Show account picker
    
    creds = flow.run_local_server(port=8081, **kwargs)
    token_file.write_text(creds.to_json())
    logger.info("YouTube credentials saved")
    return creds


def upload_video(
    video_path: Path,
    title: str,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category_id: Optional[str] = None,
    privacy_status: str = "unlisted",
) -> str:
    """
    Upload a video to YouTube.
    
    Args:
        video_path: Path to video file
        title: Video title
        description: Video description (defaults to config value)
        tags: List of tags (defaults to config value)
        category_id: YouTube category ID (defaults to config value)
        privacy_status: Privacy status (defaults to "unlisted")
    
    Returns:
        YouTube video URL
    """
    if description is None:
        description = config.YOUTUBE_DEFAULT_DESCRIPTION
    if tags is None:
        tags = [t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()]
    if category_id is None:
        category_id = config.YOUTUBE_CATEGORY_ID
    
    logger.info(f"Uploading video: {video_path.name}")
    logger.info(f"Title: {title}")
    
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    
    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {"privacyStatus": privacy_status},
    }
    if tags:
        body["snippet"]["tags"] = tags
    
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %.2f%%", status.progress() * 100)
    
    video_id = response["id"]
    youtube_url = f"https://youtu.be/{video_id}"
    logger.info(f"Upload complete: {youtube_url}")
    return youtube_url

