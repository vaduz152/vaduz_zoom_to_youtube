"""
Independent YouTube uploader: picks a video from a folder and uploads it as Unlisted.
Credentials and defaults come from .env to avoid touching existing Zoom settings.
"""

import argparse
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")
DEFAULT_TOKEN_PATH = "youtube_token.json"
DEFAULT_LOG_PATH = "youtube_uploads.txt"


def load_env() -> None:
    # Load .env from script directory (same directory as this file)
    env_path = Path(__file__).parent / ".env"
    load_dotenv(env_path)


def get_env(name: str, default: Optional[str] = None) -> str:
    value = os.getenv(name, default)
    if value is None:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


def ensure_credentials() -> Credentials:
    token_path = os.getenv("YOUTUBE_TOKEN_PATH", DEFAULT_TOKEN_PATH)
    client_id = get_env("YOUTUBE_CLIENT_ID")
    client_secret = get_env("YOUTUBE_CLIENT_SECRET")

    creds: Optional[Credentials] = None
    token_file = Path(token_path)
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(token_path, scopes=SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
        return creds

    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": client_id,
                "client_secret": client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
            }
        },
        scopes=SCOPES,
    )
    creds = flow.run_local_server(port=8081, prompt="consent")
    token_file.write_text(creds.to_json())
    return creds


def get_videos(folder: Path) -> list[Path]:
    """Get all video files from a folder, sorted by modification time (newest first).
    
    Returns:
        list: List of video file paths
    """
    if not folder.exists() or not folder.is_dir():
        raise FileNotFoundError(f"Folder not found: {folder}")
    candidates = [
        p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
    ]
    if not candidates:
        raise FileNotFoundError(f"No video files found in {folder}")
    # Sort by modification time, newest first
    return sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)


def upload_video(
    youtube,
    video_path: Path,
    title: str,
    description: str,
    tags: Optional[List[str]],
    category_id: str,
    privacy_status: str = "unlisted",
) -> str:
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
            logging.info("Upload progress: %.2f%%", status.progress() * 100)
    video_id = response["id"]
    return f"https://youtu.be/{video_id}"


def save_upload_result(folder: Path, youtube_url: str, log_path: str) -> None:
    """Save upload result to a text file."""
    log_file = Path(log_path)
    timestamp = datetime.now().isoformat()
    # Use absolute path for folder to ensure consistency
    folder_abs = str(folder.resolve())
    
    with log_file.open("a", encoding="utf-8") as f:
        f.write(f"{timestamp}\t{folder_abs}\t{youtube_url}\n")
    logging.info("Upload result saved to %s", log_file)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    load_env()

    parser = argparse.ArgumentParser(
        description="Upload the newest video in a folder to YouTube as Unlisted."
    )
    parser.add_argument(
        "--folder",
        default=os.getenv("YOUTUBE_UPLOAD_DIR", "./test_downloads"),
        help="Folder to search for video files.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Title to use for the video (defaults to folder name if not specified).",
    )
    parser.add_argument(
        "--description",
        default=os.getenv("YOUTUBE_DEFAULT_DESCRIPTION", "Uploaded via script."),
        help="Description for the video.",
    )
    parser.add_argument(
        "--tags",
        default=os.getenv("YOUTUBE_DEFAULT_TAGS"),
        help="Comma-separated tags.",
    )
    parser.add_argument(
        "--category",
        default=os.getenv("YOUTUBE_CATEGORY_ID", "22"),
        help="YouTube category ID (default 22: People & Blogs).",
    )
    parser.add_argument(
        "--log-file",
        default=os.getenv("YOUTUBE_LOG_FILE", DEFAULT_LOG_PATH),
        help="Path to log file for upload results.",
    )
    args = parser.parse_args()

    tags_list = [t.strip() for t in args.tags.split(",")] if args.tags else None
    folder = Path(args.folder).expanduser()

    try:
        video_files = get_videos(folder)
        video_count = len(video_files)
        logging.info("Found %d video(s) in folder: %s", video_count, folder)

        creds = ensure_credentials()
        youtube = build("youtube", "v3", credentials=creds)

        uploaded_urls = []
        for video_path in video_files:
            logging.info("Processing video: %s", video_path.name)
            
            # Determine title: use "[folder name] - [file name]" if multiple videos, 
            # otherwise just use folder name (unless explicitly provided)
            if args.title:
                # If title is provided and multiple videos, append filename
                if video_count > 1:
                    video_name = video_path.stem
                    title = f"{args.title} - {video_name}"
                else:
                    title = args.title
            elif video_count > 1:
                # Multiple videos: use "[folder name] - [file name]"
                video_name = video_path.stem  # filename without extension
                title = f"{folder.name} - {video_name}"
            else:
                # Single video: use folder name
                title = folder.name

            url = upload_video(
                youtube,
                video_path,
                title=title,
                description=args.description,
                tags=tags_list,
                category_id=args.category,
                privacy_status="unlisted",
            )
            logging.info("Upload complete: %s", url)
            print(url)
            uploaded_urls.append(url)
            
            # Save upload result to log file
            save_upload_result(folder, url, args.log_file)
        
        logging.info("All uploads complete. Uploaded %d video(s).", len(uploaded_urls))
    except (HttpError, FileNotFoundError, RuntimeError) as exc:
        logging.error("Upload failed: %s", exc)


if __name__ == "__main__":
    main()

