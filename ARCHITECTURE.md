# Architecture: Zoom to YouTube End-to-End Flow

## Overview

An automated system that runs every 10 minutes via cron to:
1. Download new Zoom cloud recordings (best video per meeting)
2. Upload them to YouTube as unlisted videos
3. Transcribe video via Gemini API and generate a descriptive title
4. Update YouTube video title with the generated title
5. Save transcript to a GitHub repository
6. Track all operations in a CSV file
7. Post YouTube link + transcript link to Discord via webhook
8. Clean up old videos after retention period

## Project Structure

```
vaduz_zoom_to_youtube/
├── .env                          # Merged credentials (Zoom + YouTube + Discord + Gemini)
├── .gitignore                    # Updated to include CSV, transcripts/
├── config.py                     # Configuration settings
├── main.py                       # Main entry point (runs on cron)
├── zoom_client.py                # Zoom API client
├── youtube_client.py             # YouTube API client (upload + title update)
├── discord_client.py             # Discord webhook client (template-based)
├── transcription_client.py       # Gemini API client (transcription + title generation)
├── transcript_storage.py         # Git-based transcript storage (GitHub)
├── video_tracker.py              # CSV tracking logic
├── video_manager.py              # File cleanup logic
├── utils.py                      # Shared utilities (retry_with_backoff)
├── requirements.txt              # Dependencies
├── README.md                     # Documentation
├── prompts_examples/              # Anonymized prompt examples (committed to repo)
│   ├── transcription_prompt.txt.example  # Gemini transcription prompt example
│   ├── title_prompt.txt.example          # Gemini title generation prompt example
│   └── discord_notification.txt.example  # Discord message template example
├── processed_recordings.csv      # Tracking database (gitignored)
├── zoom_to_youtube.log           # Log file (gitignored)
├── transcripts/                  # Local clone of transcripts repo (gitignored)
├── prototype/                    # Prototypes and experiments
│   ├── vtt_speaker_hints/        # VTT speaker hints prototype
│   └── ...
└── downloaded_videos/            # Video storage (gitignored)
    └── {date} {time} - {title}/
        ├── {best_video}.mp4
        └── zoom_transcript.vtt   # Zoom VTT for speaker hints
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
   - Skip if already fully processed (downloaded + uploaded + transcribed + notified)
   - If partially processed, retry from failed step
   - Find best video file (gallery view preferred)
   - Check minimum length requirement
   - **Detect video readiness** → record `video_ready_at` in CSV
   - **Check VTT readiness** → if VTT not yet available, skip (wait for next run)
   - **Record VTT readiness** → record `vtt_ready_at` in CSV, log delay
   - Download video + VTT to `downloaded_videos/{meeting_folder}/`
   - Upload to YouTube (if not already uploaded)
   - Transcribe via Gemini API (chunked, 10-min segments with VTT speaker hints)
   - Generate descriptive title from transcript
   - Save transcript to GitHub repository
   - Update YouTube video title (date/time prefix + generated title)
   - Rename local folder to match new title
   - Post YouTube link + transcript link to Discord (if not already notified)
   - Record in CSV with all metadata
6. Clean up old videos (older than retention period)
7. Exit

**Graceful degradation:** Transcription failure does not block YouTube upload or Discord notification. If transcription fails, Discord message shows `[транскрипт недоступен]` instead of transcript link.

**Command-line arguments:**
- `--dry-run`: Test mode (no downloads/uploads, just logging)
- `--verbose`: Increase logging verbosity

### 3. `zoom_client.py`
Zoom API operations (extracted from prototype):

**Functions:**
- `get_access_token()` - Get/refresh OAuth token
- `list_recordings(limit=None, from_date=None, to_date=None)` - Fetch recordings
- `download_file(download_url, output_path)` - Download any recording file (video or VTT)
- `find_best_video(recording_files)` - Select best video (gallery view preferred)
- `find_transcript_file(recording_files)` - Find VTT audio transcript in recording files

**Token management:**
- Uses refresh token stored in `.zoom_refresh_token` (root)
- Handles token refresh automatically

### 4. `youtube_client.py`
YouTube API operations (extracted from prototype):

**Functions:**
- `get_credentials()` - Get/refresh OAuth credentials
- `upload_video(video_path, title, description, tags, category_id)` - Upload video, returns YouTube URL
- `update_video_title(youtube_url, new_title, description)` - Update title of uploaded video
- `extract_video_id(youtube_url)` - Parse video ID from youtu.be/youtube.com URLs

**Scopes:** `youtube.upload` + `youtube` (full scope needed for title updates)

**Token management:**
- Uses token stored in `youtube_token.json` (root)
- Handles token refresh automatically

### 5. `discord_client.py`
Discord webhook operations with customizable template:

**Functions:**
- `send_notification(youtube_url, transcript_url, generated_title, meeting_topic)` - Post notification to Discord
- `send_error_notification(error_message, error_details)` - Post error notification
- Returns success/failure status

**Message template:** Loaded from `meeting-transcripts/prompts/discord_notification.txt`, uses `str.format()` with variables `{title}`, `{youtube_url}`, `{transcript_url}`. Lines starting with `#` are stripped (comments).

### 5a. `transcription_client.py`
Gemini API client for video transcription with VTT speaker hints:

**Functions:**
- `transcribe_video(video_path, duration_seconds, vtt_path)` - Transcribe video with optional VTT speaker hints (chunked, 10-min segments with 15s overlap). Returns transcript text or `None`
- `generate_title(transcript)` - Generate descriptive title from transcript. Returns title or `None`
- `parse_vtt(vtt_text)` - Parse VTT content into structured entries with speaker names and timestamps

**VTT Speaker Hints:** Zoom's audio transcript (VTT) has accurate speaker names from audio channels but garbled text. Gemini has good speech recognition but misidentifies speakers. Combining both: VTT fragments are extracted per-chunk and passed alongside the video for speaker attribution. This fixes ~90% of speaker attribution errors.

**Timestamp handling:** Gemini writes timestamps relative to chunk start (00:00). The script applies absolute offsets post-hoc via `_add_offset_to_transcript()`.

**Prompt template:** Uses `{chunk_info}` and `{vtt_segment}` placeholders, filled per-chunk from the VTT data.

**Chunking:** Videos are split into 10-minute chunks via ffmpeg. Each chunk is uploaded to Gemini File API, transcribed, then deleted. Chunks overlap by 15 seconds for continuity.

**Configuration:** `GEMINI_API_KEY`, `GEMINI_MODEL`, `TRANSCRIPTION_PROMPT_PATH`, `TITLE_PROMPT_PATH`, `MAX_TRANSCRIPTION_DURATION`

### 5b. `transcript_storage.py`
Git-based transcript storage:

**Functions:**
- `save_transcript(transcript, folder_name, title)` - Save transcript to GitHub repo, returns GitHub URL or `None`
- `derive_filename(folder_name, title)` - Generate filename from folder name and title

**Git strategy:** Persistent local clone in `./transcripts/`. On each run: `git pull --rebase` → write file → `git add` + `git commit` + `git push`. Dirty state from failed runs is reset automatically.

**Configuration:** `TRANSCRIPTS_REPO_URL`, `TRANSCRIPTS_REPO_PATH`, `TRANSCRIPTS_GITHUB_REPO`

### 6. `video_tracker.py`
CSV tracking database:

**CSV Structure:**
```csv
zoom_uuid,meeting_topic,start_time,file_path,zoom_downloaded_at,youtube_uploaded_at,youtube_url,discord_notified_at,status,error_message,transcribed_at,transcript_url,generated_title
```

**Functions:**
- `is_processed(uuid)` - Check if recording already processed (transcription is optional — not required for "processed")
- `record_video_ready(uuid, meeting_topic, start_time)` - Record when video first appeared in Zoom cloud
- `record_vtt_ready(uuid)` - Record when VTT transcript appeared (logs delay from video readiness)
- `record_download(uuid, meeting_topic, start_time, file_path)` - Record download
- `record_upload(uuid, youtube_url)` - Record upload
- `record_transcription(uuid, transcript_url, generated_title)` - Record transcription
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
zoom_uuid,meeting_topic,start_time,file_path,zoom_downloaded_at,youtube_uploaded_at,youtube_url,discord_notified_at,status,error_message,transcribed_at,transcript_url,generated_title,failure_count,error_notified_at,last_notified_error,video_ready_at,vtt_ready_at
```

**Fields:**
- `zoom_uuid`: Unique Zoom recording ID (primary key)
- `meeting_topic`: Meeting name/title
- `start_time`: ISO 8601 timestamp
- `file_path`: Local file path relative to repo root
- `zoom_downloaded_at`: ISO timestamp when downloaded
- `youtube_uploaded_at`: ISO timestamp when uploaded (empty if failed)
- `youtube_url`: YouTube video URL (empty if not uploaded)
- `discord_notified_at`: ISO timestamp when Discord notification sent (empty if failed)
- `status`: `waiting_for_vtt`, `downloaded`, `uploaded`, `notified`, `failed`
- `error_message`: Error details if any step failed
- `transcribed_at`: ISO timestamp when transcribed (empty if not transcribed)
- `transcript_url`: GitHub URL to transcript (empty if not saved)
- `generated_title`: Title generated by Gemini (empty if not generated)
- `failure_count`: Number of consecutive failures (resets on success)
- `error_notified_at`: Timestamp when error notification was last sent
- `last_notified_error`: Last error message that triggered a notification
- `video_ready_at`: ISO timestamp when video first appeared in Zoom cloud
- `vtt_ready_at`: ISO timestamp when VTT transcript first appeared in Zoom cloud

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
- **Transcription failure**: Log warning, continue to Discord notification with `[транскрипт недоступен]`. Send error notification if error threshold reached
- **Discord failure**: Record error in CSV, but don't fail entire process, retry on next run if upload succeeded
- **Token refresh failure**: Log error, exit (requires manual intervention)

**Retry Logic:**
- On each run, check CSV for records with `status=failed` or missing `youtube_url`
- If video file still exists, retry the failed operation
- Prevents permanent failures due to transient network issues

## Cron Configuration

```bash
# Run every 10 minutes
*/10 * * * * cd /path/to/vaduz_zoom_to_youtube && /path/to/venv/bin/python main.py >> /path/to/zoom_to_youtube.log 2>&1
```

Frequent runs are needed because the Zoom VTT transcript appears with a delay after the video is ready. The script detects video readiness first, then waits for the VTT on subsequent runs before downloading and processing.

Note: The script also writes to its own log file configured in `LOG_FILE` environment variable. File locking (`fcntl`) prevents concurrent runs.

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
YOUTUBE_LOGIN_HINT=your_google_email@gmail.com

# Discord Webhook
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...

# Processing Configuration
LAST_MEETINGS_TO_PROCESS=3
MIN_VIDEO_LENGTH_SECONDS=60
VIDEO_RETENTION_DAYS=10
ERROR_NOTIFICATION_THRESHOLD=5
DOWNLOAD_DIR=./downloaded_videos
CSV_TRACKER_PATH=./processed_recordings.csv
LOG_FILE=./zoom_to_youtube.log

# Gemini API (transcription & title generation)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3-pro-preview
TRANSCRIPTION_PROMPT_PATH=./meeting-transcripts/prompts/transcription_prompt.txt
TITLE_PROMPT_PATH=./meeting-transcripts/prompts/title_prompt.txt
MAX_TRANSCRIPTION_DURATION=7200

# Transcript storage (GitHub repo)
TRANSCRIPTS_REPO_URL=git@github.com:user/meeting-transcripts.git
TRANSCRIPTS_REPO_PATH=./transcripts
TRANSCRIPTS_GITHUB_REPO=user/meeting-transcripts

# Discord notification template
DISCORD_NOTIFICATION_TEMPLATE_PATH=./meeting-transcripts/prompts/discord_notification.txt
```

## Dependencies

- `requests` - HTTP requests (Zoom API, Discord webhook)
- `google-auth` - YouTube OAuth
- `google-auth-oauthlib` - YouTube OAuth flow
- `google-api-python-client` - YouTube API
- `google-genai` - Gemini API (transcription, title generation)
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

