# Architecture: Zoom to YouTube End-to-End Flow

## Overview

An automated system that runs hourly via cron to:
1. Download new Zoom cloud recordings (best video per meeting)
2. Upload them to YouTube as unlisted videos
3. Track all operations in a CSV file
4. Post YouTube links to Discord via webhook
5. Clean up old videos after retention period

## Project Structure

```
vaduz_zoom_to_youtube/
├── .env                          # Merged credentials (Zoom + YouTube + Discord)
├── .gitignore                    # Updated to include CSV
├── config.py                     # Configuration settings
├── main.py                       # Main entry point (runs on cron)
├── zoom_client.py                # Zoom API client
├── youtube_client.py             # YouTube API client
├── discord_client.py             # Discord webhook client
├── video_tracker.py              # CSV tracking logic
├── video_manager.py              # File cleanup logic
├── requirements.txt              # Dependencies
├── README.md                     # Updated documentation
├── processed_recordings.csv      # Tracking database (gitignored)
├── zoom_to_youtube.log           # Log file (gitignored)
└── downloaded_videos/            # Video storage (gitignored)
    └── {meeting_folder}/
        └── {best_video}.mp4
```

## Components

### 1. `config.py`
Configuration settings loaded from environment variables:

```python
# Zoom settings
ZOOM_CLIENT_ID
ZOOM_CLIENT_SECRET
ZOOM_REDIRECT_URI
ZOOM_USER_ID

# YouTube settings
YOUTUBE_CLIENT_ID
YOUTUBE_CLIENT_SECRET
YOUTUBE_DEFAULT_DESCRIPTION
YOUTUBE_DEFAULT_TAGS
YOUTUBE_CATEGORY_ID

# Discord settings
DISCORD_WEBHOOK_URL

# Processing settings
LAST_MEETINGS_TO_PROCESS = 3          # Limit to last N meetings
MIN_VIDEO_LENGTH_SECONDS = 60         # Minimum video length
VIDEO_RETENTION_DAYS = 10             # Delete videos after N days
DOWNLOAD_DIR = "./downloaded_videos"  # Storage location
CSV_TRACKER_PATH = "./processed_recordings.csv"
LOG_FILE = "./zoom_to_youtube.log"    # Log file path
```

### 2. `main.py`
Main entry point - orchestrates the entire flow:

**Flow:**
1. Load configuration
2. Initialize clients (Zoom, YouTube, Discord, Tracker)
3. Get access tokens (refresh if needed)
4. Fetch recordings from Zoom (last N meetings)
5. For each recording:
   - Check if already processed (by UUID in CSV)
   - Skip if already fully processed (downloaded + uploaded + notified)
   - If partially processed (e.g., downloaded but upload failed), retry from failed step
   - Find best video file (gallery view preferred)
   - Check minimum length requirement
   - Download video to `downloaded_videos/{meeting_folder}/` (if not already downloaded)
   - Upload to YouTube (if not already uploaded)
   - Post YouTube link to Discord (if not already notified)
   - Record in CSV with all metadata
6. Clean up old videos (older than retention period)
7. Exit

**Command-line arguments:**
- `--dry-run`: Test mode (no downloads/uploads, just logging)
- `--verbose`: Increase logging verbosity

### 3. `zoom_client.py`
Zoom API operations (extracted from prototype):

**Functions:**
- `get_access_token()` - Get/refresh OAuth token
- `list_recordings(limit=None, from_date=None, to_date=None)` - Fetch recordings
- `download_video(download_url, output_path)` - Download video file
- `find_best_video(recording_files)` - Select best video (gallery view preferred)

**Token management:**
- Uses refresh token stored in `.zoom_refresh_token` (root)
- Handles token refresh automatically

### 4. `youtube_client.py`
YouTube API operations (extracted from prototype):

**Functions:**
- `get_credentials()` - Get/refresh OAuth credentials
- `upload_video(video_path, title, description, tags, category_id)` - Upload video
- Returns YouTube URL

**Token management:**
- Uses token stored in `youtube_token.json` (root)
- Handles token refresh automatically

### 5. `discord_client.py`
Discord webhook operations (new):

**Functions:**
- `send_notification(youtube_url)` - Post YouTube link to Discord
- Returns success/failure status

**Message format:**
- Formatted message: `"New video: {youtube_url}"`

### 6. `video_tracker.py`
CSV tracking database:

**CSV Structure:**
```csv
zoom_uuid,meeting_topic,start_time,file_path,zoom_downloaded_at,youtube_uploaded_at,youtube_url,discord_notified_at,status,error_message
```

**Functions:**
- `is_processed(uuid)` - Check if recording already processed
- `record_download(uuid, meeting_topic, start_time, file_path)` - Record download
- `record_upload(uuid, youtube_url)` - Record upload
- `record_notification(uuid)` - Record Discord notification
- `record_error(uuid, error_message)` - Record error
- `get_all_records()` - Read all records (for cleanup)

**Deduplication:**
- Uses `zoom_uuid` as primary key
- Prevents reprocessing same recording

### 7. `video_manager.py`
File management and cleanup:

**Functions:**
- `cleanup_old_videos(retention_days)` - Delete videos older than retention period
- Uses CSV to track which videos to delete
- Removes both video files and empty folders

## CSV Tracking Schema

```csv
zoom_uuid,meeting_topic,start_time,file_path,zoom_downloaded_at,youtube_uploaded_at,youtube_url,discord_notified_at,status,error_message
```

**Fields:**
- `zoom_uuid`: Unique Zoom recording ID (primary key)
- `meeting_topic`: Meeting name/title
- `start_time`: ISO 8601 timestamp
- `file_path`: Local file path relative to repo root (e.g., `downloaded_videos/2025-12-02_1758 - Meeting/active_speaker.mp4`)
- `zoom_downloaded_at`: ISO timestamp when downloaded
- `youtube_uploaded_at`: ISO timestamp when uploaded (empty if failed)
- `youtube_url`: YouTube video URL (empty if not uploaded)
- `discord_notified_at`: ISO timestamp when Discord notification sent (empty if failed)
- `status`: `downloaded`, `uploaded`, `notified`, `failed`
- `error_message`: Error details if any step failed

## Video Selection Logic

1. Filter out non-video files (audio_only, timeline, transcripts, etc.)
2. Priority order:
   - `shared_screen_with_gallery_view` (preferred)
   - `gallery_view`
   - `active_speaker` (fallback)
   - `shared_screen_with_speaker_view` (fallback)
3. Check minimum length requirement
4. Download only the best video

## Error Handling

- **Download failure**: Record error in CSV, skip to next recording
- **Upload failure**: Keep video file, record error in CSV with status `failed`, retry on next run (if status is `failed` and file exists, attempt upload again)
- **Discord failure**: Record error in CSV, but don't fail entire process, retry on next run if upload succeeded
- **Token refresh failure**: Log error, exit (requires manual intervention)

**Retry Logic:**
- On each run, check CSV for records with `status=failed` or missing `youtube_url`
- If video file still exists, retry the failed operation
- Prevents permanent failures due to transient network issues

## Cron Configuration

```bash
# Run every hour at minute 0
0 * * * * cd /path/to/vaduz_zoom_to_youtube && /path/to/venv/bin/python main.py >> /path/to/zoom_to_youtube.log 2>&1
```

Note: The script also writes to its own log file configured in `LOG_FILE` environment variable.

## Dry Run Mode

When `--dry-run` is specified:
- Skip actual downloads/uploads
- Skip Discord notifications
- Still check CSV for duplicates
- Log what would be done
- Useful for testing without side effects

## First Run Behavior

- Processes all available recordings (up to `LAST_MEETINGS_TO_PROCESS` limit)
- Respects `MIN_VIDEO_LENGTH_SECONDS` filter
- Records all operations in CSV
- Subsequent runs only process new recordings (not in CSV)

## Environment Variables (.env)

```bash
# Zoom OAuth
ZOOM_CLIENT_ID=...
ZOOM_CLIENT_SECRET=...
ZOOM_REDIRECT_URI=http://localhost:8080/redirect
ZOOM_USER_ID=user@example.com

# YouTube OAuth
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_DEFAULT_DESCRIPTION=Uploaded via automation
YOUTUBE_DEFAULT_TAGS=zoom,meeting,recording
YOUTUBE_CATEGORY_ID=22

# Discord Webhook
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Processing Configuration
LAST_MEETINGS_TO_PROCESS=3
MIN_VIDEO_LENGTH_SECONDS=60
VIDEO_RETENTION_DAYS=10
DOWNLOAD_DIR=./downloaded_videos
CSV_TRACKER_PATH=./processed_recordings.csv
LOG_FILE=./zoom_to_youtube.log
```

## Dependencies

- `requests` - HTTP requests (Zoom API, Discord webhook)
- `google-auth` - YouTube OAuth
- `google-auth-oauthlib` - YouTube OAuth flow
- `google-api-python-client` - YouTube API
- `python-dotenv` - Environment variable loading

## Logging

- Minimal logging: Only important events (downloads, uploads, errors)
- Logs to separate log file: `zoom_to_youtube.log` (configurable via `LOG_FILE`)
- Also logs to stdout/stderr (captured by cron)
- Optional verbose mode with `--verbose` flag
- Log file location: Root directory (gitignored)

## Security Considerations

- All credentials in `.env` (gitignored)
- OAuth tokens stored locally (gitignored)
- CSV contains no sensitive data (only metadata)
- Discord webhook URL should be kept secret

