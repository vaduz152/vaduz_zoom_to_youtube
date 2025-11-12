# Zoom to YouTube Uploader - Prototype Plan

## Overview
A simple Python script that automatically polls Zoom cloud recordings every 10 minutes, downloads videos, identifies Gallery View recordings, and uploads them to YouTube with metadata extracted from Zoom.

## Architecture

### Core Components
1. **Zoom API Client** - Authenticates and fetches recordings using Client-to-Server OAuth
2. **Video Downloader** - Downloads all recordings to organized local storage
3. **Gallery View Identifier** - Determines which recordings are Gallery View (to be discovered)
4. **YouTube Uploader** - Uploads Gallery View videos with extracted metadata
5. **Processing Tracker** - CSV log to prevent duplicate processing
6. **Scheduler** - Runs the main loop every 10 minutes

### File Structure
```
vaduz_zoom_to_youtube/
├── main.py                 # Main entry point with scheduler
├── zoom_client.py          # Zoom API authentication and fetching
├── video_downloader.py     # Download logic with organized storage
├── gallery_identifier.py   # Logic to identify Gallery View recordings
├── youtube_uploader.py     # YouTube API upload with metadata
├── tracker.py              # CSV-based processing tracker
├── config.py               # Configuration and .env loading
├── .env                    # Credentials (not in git)
├── .env.example            # Example env file
├── processed_recordings.csv # Tracking log
├── requirements.txt        # Python dependencies
└── downloads/              # Local video storage
    └── YYYY-MM-DD/
        └── meeting-name/
            ├── gallery_view.mp4
            └── speaker_view.mp4
```

## Implementation Details

### 1. Configuration (`config.py`)
- Load credentials from `.env` file using `python-dotenv`
- Required env variables:
  - `ZOOM_CLIENT_ID`
  - `ZOOM_CLIENT_SECRET`
  - `ZOOM_ACCOUNT_ID`
  - `YOUTUBE_CLIENT_ID`
  - `YOUTUBE_CLIENT_SECRET`
  - `YOUTUBE_REFRESH_TOKEN`
  - `ZOOM_USER_ID` (user whose recordings to fetch)

### 2. Zoom Client (`zoom_client.py`)
- Implement Client-to-Server OAuth flow for password-protected videos
- Function: `get_access_token()` - Obtain OAuth token
- Function: `list_recordings()` - Fetch recordings from `/users/{userId}/recordings`
- Function: `get_recording_details()` - Get full recording metadata
- Handle pagination if needed
- Return recording objects with: id, meeting_topic, start_time, download_url, recording_files

### 3. Gallery View Identifier (`gallery_identifier.py`)
- **Discovery phase**: Examine Zoom API response structure for recording files
- Check `recording_type` field in recording_files array
- Check filename patterns (e.g., "gallery", "gv", etc.)
- Check file metadata (size, duration hints)
- Function: `is_gallery_view(recording_file)` - Returns boolean
- Log findings for debugging

### 4. Video Downloader (`video_downloader.py`)
- Function: `download_recording(recording, base_path)` - Downloads all files
- Create directory structure: `downloads/YYYY-MM-DD/meeting-name/`
- Sanitize meeting names for filesystem safety
- Download with authentication headers (OAuth token)
- Handle download errors and retries
- Return local file paths

### 5. Processing Tracker (`tracker.py`)
- CSV format: `recording_id,meeting_topic,start_time,processed_at,status`
- Function: `is_processed(recording_id)` - Check if already processed
- Function: `mark_processed(recording_id, metadata)` - Add to CSV
- Load CSV on startup, append on each processing

### 6. YouTube Uploader (`youtube_uploader.py`)
- Authenticate using OAuth 2.0 with refresh token
- Function: `upload_video(file_path, metadata)` - Upload to YouTube
- Extract metadata from Zoom recording:
  - Title: `{meeting_topic} - {date}`
  - Description: Meeting details, date, time
  - Privacy: Unlisted
- Use `google-api-python-client` library
- Handle upload errors and retries

### 7. Main Script (`main.py`)
- Main function: `process_new_recordings()`
  - Fetch recordings from Zoom
  - Filter out already processed (using tracker)
  - Download all recordings
  - Identify Gallery View
  - Upload Gallery View to YouTube
  - Mark as processed
- Scheduler: Use `schedule` library for 10-minute intervals
- Error handling and logging to console/file
- Graceful shutdown handling

## Dependencies
- `requests` - HTTP requests
- `python-dotenv` - Environment variables
- `google-api-python-client` - YouTube API
- `google-auth-httplib2` - Google auth
- `google-auth-oauthlib` - OAuth flow
- `schedule` - Simple scheduling

## Development Steps

1. **Setup project structure** - Create files, requirements.txt, .env.example
2. **Implement Zoom authentication** - Client-to-Server OAuth flow
3. **Implement recording fetcher** - List and fetch recording details
4. **Discover Gallery View identification** - Test with real API responses
5. **Implement downloader** - Organized storage structure
6. **Implement tracker** - CSV-based duplicate prevention
7. **Implement YouTube uploader** - OAuth and upload with metadata
8. **Wire everything together** - Main script with scheduler
9. **Testing** - Test with real Zoom recordings

## Notes
- Prototype approach: Simple, fast, functional
- No complex error recovery - basic retries and logging
- CSV tracking is simple but sufficient for prototype
- Gallery View identification will be refined during development
- All videos downloaded locally for debugging/inspection

