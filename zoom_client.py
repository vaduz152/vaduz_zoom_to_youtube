"""Zoom API client for downloading cloud recordings."""
import base64
import logging
import os
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

import requests

import config
from gallery_identifier import find_best_gallery_view_file

logger = logging.getLogger(__name__)


def get_authorization_url() -> str:
    """Generate the authorization URL for user to visit."""
    params = {
        "response_type": "code",
        "client_id": config.ZOOM_CLIENT_ID,
        "redirect_uri": config.ZOOM_REDIRECT_URI
    }
    url = "https://zoom.us/oauth/authorize?" + urllib.parse.urlencode(params)
    return url


def exchange_code_for_tokens(authorization_code: str) -> Tuple[str, str]:
    """Exchange authorization code for access token and refresh token."""
    logger.info("Exchanging authorization code for tokens...")
    
    credentials = f"{config.ZOOM_CLIENT_ID}:{config.ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": config.ZOOM_REDIRECT_URI
    }
    
    response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    
    # Save refresh token for future use
    if refresh_token:
        config.ZOOM_REFRESH_TOKEN_FILE.write_text(refresh_token)
        logger.info("Refresh token saved")
    
    return access_token, refresh_token


def get_access_token_from_refresh(refresh_token: str) -> str:
    """Get a new access token using refresh token."""
    credentials = f"{config.ZOOM_CLIENT_ID}:{config.ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    
    # Update refresh token if a new one is provided
    if new_refresh_token and new_refresh_token != refresh_token:
        config.ZOOM_REFRESH_TOKEN_FILE.write_text(new_refresh_token)
    
    return access_token


def get_access_token() -> str:
    """Get OAuth access token using refresh token or guide user through authorization."""
    logger.info("Getting Zoom access token...")
    
    token_file = config.ZOOM_REFRESH_TOKEN_FILE
    
    # Check if we have a saved refresh token
    if token_file.exists():
        logger.debug("Found saved refresh token")
        refresh_token = token_file.read_text().strip()
        
        try:
            access_token = get_access_token_from_refresh(refresh_token)
            logger.info("Access token obtained from refresh token")
            return access_token
        except Exception as e:
            logger.warning(f"Refresh token expired or invalid: {e}")
            logger.info("Need to re-authorize...")
            token_file.unlink()
    
    # No valid refresh token, need to get authorization code
    logger.error("\n" + "="*60)
    logger.error("First-time authorization required!")
    logger.error("="*60)
    logger.error("\n1. Visit this URL in your browser to authorize the app:")
    logger.error(f"\n   {get_authorization_url()}\n")
    logger.error("2. After authorizing, you'll be redirected to your redirect URI.")
    logger.error("3. Copy the 'code' parameter from the redirect URL.")
    logger.error("   Example: http://localhost:8080/redirect?code=ABC123")
    logger.error("   The code is: ABC123")
    logger.error("\n" + "="*60)
    
    authorization_code = input("\nPaste the authorization code here: ").strip()
    
    if not authorization_code:
        raise Exception("No authorization code provided")
    
    access_token, refresh_token = exchange_code_for_tokens(authorization_code)
    logger.info("Access token obtained")
    return access_token


def list_recordings(
    access_token: str,
    limit: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page_size: int = 30
) -> List[dict]:
    """List recordings for the user."""
    logger.info("Fetching recordings from Zoom...")
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://zoom.us/v2/users/{config.ZOOM_USER_ID}/recordings"
    params = {"page_size": page_size}
    
    # Add date filters if provided
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        logger.error(f"Error: {response.status_code}")
        logger.error(f"Response: {response.text}")
        response.raise_for_status()
    
    data = response.json()
    recordings = data.get("meetings", [])
    
    logger.info(f"Found {len(recordings)} recordings in this page")
    
    # Handle pagination if next_page_token exists
    all_recordings = recordings.copy()
    next_page_token = data.get("next_page_token")
    page_number = 1
    
    while next_page_token:
        logger.debug(f"Fetching page {page_number + 1}...")
        next_params = {"page_size": page_size, "next_page_token": next_page_token}
        if from_date:
            next_params["from"] = from_date
        if to_date:
            next_params["to"] = to_date
            
        response = requests.get(url, headers=headers, params=next_params)
        response.raise_for_status()
        
        page_data = response.json()
        page_recordings = page_data.get("meetings", [])
        all_recordings.extend(page_recordings)
        next_page_token = page_data.get("next_page_token")
        page_number += 1
        
        logger.debug(f"Found {len(page_recordings)} recordings in page {page_number}")
    
    if page_number > 1:
        logger.info(f"Total recordings across all pages: {len(all_recordings)}")
    
    # Apply limit if specified
    if limit:
        all_recordings = all_recordings[:limit]
    
    return all_recordings


def is_video_file(recording_file: dict) -> bool:
    """Check if a recording file is a video file (not audio, transcript, etc.)."""
    recording_type = recording_file.get("recording_type", "").lower()
    
    skip_types = [
        'audio_only',
        'timeline',
        'audio_transcript',
        'chat_file',
        'closed_caption'
    ]
    
    return recording_type not in skip_types


def find_best_video(recording_files: List[dict]) -> Optional[dict]:
    """
    Find the best video file from a list of recording files.
    Uses gallery_identifier logic: prefers gallery view, falls back to speaker view.
    """
    return find_best_gallery_view_file(recording_files)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be safe for use as a filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = name.strip(' .')
    if len(name) > 200:
        name = name[:200]
    return name


def generate_folder_name(recording: dict, template: str = "{date} {time} - {topic}") -> str:
    """Generate folder name for a recording based on template."""
    meeting_topic = recording.get('topic', 'Untitled Meeting')
    start_time = recording.get('start_time', '')
    
    # Parse start_time
    try:
        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H-%M")
        date_time_str = f"{date_str} {time_str}"
    except (ValueError, AttributeError):
        dt = datetime.now()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H-%M")
        date_time_str = f"{date_str} {time_str}"
    
    # Replace placeholders in template
    folder_name = template.format(
        date=date_str,
        time=time_str,
        date_time=date_time_str,
        topic=meeting_topic
    )
    
    # Sanitize folder name for filesystem
    return sanitize_filename(folder_name)


def download_video(download_url: str, access_token: str, output_path: Path) -> None:
    """Download a video file."""
    logger.info(f"Downloading to {output_path}...")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(download_url, headers=headers, stream=True, timeout=300)
    response.raise_for_status()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    file_size = output_path.stat().st_size
    logger.info(f"Downloaded {file_size / (1024*1024):.2f} MB")


def get_recording_duration_seconds(recording: dict, video_file: Optional[dict] = None) -> int:
    """
    Get recording duration in seconds.
    Tries recording duration first, then calculates from video file timestamps.
    """
    # Try recording duration (in minutes)
    recording_duration_minutes = recording.get('duration', 0)
    if recording_duration_minutes > 0:
        return recording_duration_minutes * 60
    
    # Fallback: calculate from video file timestamps
    if video_file:
        try:
            file_start = video_file.get('recording_start')
            file_end = video_file.get('recording_end')
            
            if file_start and file_end:
                start_dt = datetime.fromisoformat(file_start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(file_end.replace('Z', '+00:00'))
                return int((end_dt - start_dt).total_seconds())
        except (ValueError, AttributeError, TypeError):
            pass
    
    return 0

