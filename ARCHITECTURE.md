# Architecture: Zoom to YouTube End-to-End Flow

## Overview

An automated system that runs every 10 minutes via cron to:
1. Download new Zoom cloud recordings (best video per meeting)
2. Upload them to YouTube as unlisted videos
3. Transcribe video via Gemini API and generate a descriptive title
4. Generate a structured meeting summary via Gemini API
5. Save transcript + summary to a private GitHub repository in a single commit, with cross-references between the two files
6. Update YouTube video title with the generated title
7. Track all operations in a CSV file
8. Post YouTube link + transcript link + summary link + total Gemini cost to Discord via webhook
9. Clean up old videos after retention period

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
├── summary_client.py             # Gemini API client (meeting summary generation)
├── transcript_storage.py         # Git-based transcript + summary storage (GitHub)
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
3. Validate credentials and prompt files
4. Get access tokens (refresh if needed)
5. Fetch recordings from Zoom (last N meetings)
6. For each recording:
   - Check if already processed (by UUID in CSV). Fully processed = all of: downloaded, uploaded, transcribed, summarized, notified
   - If partially processed, pick up at the first missing step
   - Find best video file (gallery view preferred) and check minimum length
   - **Detect video readiness** → record `video_ready_at` in CSV
   - **Check VTT readiness** → if VTT not yet available, skip (wait for next run)
   - **Record VTT readiness** → record `vtt_ready_at` in CSV, log delay
   - Download video + VTT to `downloaded_videos/{meeting_folder}/`
   - Upload to YouTube (if not already uploaded)
   - **Transcription + summary step (unified):**
     - If transcript missing: transcribe via Gemini (chunked, 10-min segments with VTT speaker hints), generate descriptive title, write raw transcript to the local clone at `meeting-transcripts/transcripts/{filename}.md`
     - Load transcript body from the local clone (stripping any existing header)
     - Generate a structured summary from the body via Gemini
     - Compute GitHub URLs for both files in advance
     - Build full transcript + summary content with headers and cross-references (`📋 [Саммари](...)` and `📝 [Транскрипт](...)` respectively)
     - Save both files in a single git commit to the `meeting-transcripts` repo
     - Update YouTube video title to the generated title (only on fresh transcription)
     - Rename local folder to match the generated title (only on fresh transcription)
     - Record `transcribed_at` + `summarized_at` in CSV
   - Post YouTube + transcript + summary + total Gemini cost to Discord (if not already notified)
7. Clean up old videos (older than retention period)
8. Exit

**No graceful degradation:** Transcription and summary are both mandatory. If either step fails, the record is marked as failed and the rest of the pipeline for that recording is aborted. The next run resumes from the failed step. Because the transcript is cached in the local clone, a missing-summary retry does not re-transcribe — it only regenerates the summary.

**Command-line arguments:**
- `--dry-run`: Test mode (no downloads/uploads, just logging)
- `--verbose`: Increase logging verbosity
- `--local`: Process pre-downloaded videos from `LOCAL_VIDEOS_DIR` instead of Zoom cloud (uses content-hash UUIDs)
- `--zoom-uuid UUID`: Process a single record by Zoom UUID. Tries to fetch it from Zoom cloud and runs `process_recording` on it (respects CSV state). If the record is no longer in Zoom but has a transcript in CSV, falls back to a summary-only reprocess via `reprocess_summary_by_uuid`.

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
- `send_notification(youtube_url, transcript_url, summary_url, generated_title, meeting_topic, meeting_datetime, transcription_cost)` - Post notification to Discord
- `send_error_notification(error_message, error_details)` - Post error notification
- Returns success/failure status

**Message template:** Loaded from `meeting-transcripts/prompts/discord_notification.txt`, uses `str.format()` with variables `{title}`, `{youtube_url}`, `{transcript_url}`, `{summary_url}`, `{datetime}`, `{cost}`. Lines starting with `#` are stripped (comments).

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

### 5b. `summary_client.py`
Gemini API client for generating structured meeting summaries:

**Functions:**
- `generate_summary(transcript)` - Generate a summary from a transcript. Returns `(summary_text, UsageStats)`. Raises on failure.

**Prompt:** Single universal prompt at `meeting-transcripts/prompts/summary_prompt.txt`. The prompt describes the possible meeting formats (check-in, technical discussion, forum, meditation, knowledge-sharing, vision/sense-making) and asks Gemini to adapt the output structure to what actually happened, in strict chronological order. The prompt also instructs Gemini to match the team's vocabulary and tone.

**Configuration:** `GEMINI_API_KEY`, `GEMINI_MODEL`, `SUMMARY_PROMPT_PATH`

### 5c. `transcript_storage.py`
Git-based storage for transcripts and summaries in a private GitHub repo.

**Functions:**
- `sync_clone()` - Ensure the repo is cloned, pulled to latest, and clean of dirty state. Call once at the start of the transcript+summary step.
- `write_transcript_raw(transcript_body, folder_name, title)` - Write a raw transcript to the local clone without committing. Used right after fresh transcription so that subsequent code paths can uniformly load the transcript from disk.
- `load_transcript_body(folder_name, title)` - Load a transcript from the local clone and strip any existing header (everything before the first `[MM:SS]` line). Unifies fresh-run and retry paths.
- `predict_urls(folder_name, title)` - Compute `(transcript_url, summary_url)` in advance so that each file can be written with a cross-reference header pointing at the other.
- `save_transcript_and_summary(transcript, summary, folder_name, title)` - Write both files to the clone, `git add` both, commit with a single message, and push. Returns `(transcript_url, summary_url)`. Raises on failure.
- `derive_filename(folder_name, title)` - Generate a stable filename (`{date_time} - {title}.md`) used for both transcripts/ and summaries/.

**Git strategy:** Persistent local clone of the private `meeting-transcripts` repo. The caller is expected to call `sync_clone()` once per step; individual write/load helpers do not touch git. Dirty state from failed runs is reset automatically at the next `sync_clone()` call.

**Configuration:** `TRANSCRIPTS_REPO_URL`, `TRANSCRIPTS_REPO_PATH`, `TRANSCRIPTS_GITHUB_REPO`

### 6. `video_tracker.py`
CSV tracking database.

**Functions:**
- `is_processed(uuid)` - Check if recording is fully processed. A recording is "processed" only when all of `zoom_downloaded_at`, `youtube_uploaded_at`, `transcribed_at`, `summarized_at`, `discord_notified_at` are set (or `status=skipped`).
- `record_video_ready(uuid, meeting_topic, start_time)` - Record when video first appeared in Zoom cloud
- `record_vtt_ready(uuid)` - Record when VTT transcript appeared (logs delay from video readiness)
- `record_download(uuid, meeting_topic, start_time, file_path)` - Record download
- `record_upload(uuid, youtube_url)` - Record upload
- `record_transcription(uuid, transcript_url, generated_title)` - Record transcription
- `record_summary(uuid, summary_url)` - Record summary
- `record_notification(uuid)` - Record Discord notification
- `record_error(uuid, error_message)` - Record error (increments failure_count, maybe triggers Discord alert)
- `record_skipped(uuid, reason)` - Mark recording as permanently skipped (e.g. too short)
- `get_all_records()` - Read all records (for cleanup)

**Deduplication:** Uses `zoom_uuid` as primary key; prevents reprocessing the same recording.

### 7. `video_manager.py`
File management and cleanup:

**Functions:**
- `cleanup_old_videos(retention_days)` - Delete videos older than retention period
- Uses CSV to track which videos to delete
- Removes both video files and empty folders

## CSV Tracking Schema

```csv
zoom_uuid,meeting_topic,start_time,file_path,video_ready_at,vtt_ready_at,zoom_downloaded_at,youtube_uploaded_at,youtube_url,discord_notified_at,status,error_message,failure_count,error_notified_at,last_notified_error,transcribed_at,transcript_url,generated_title,summarized_at,summary_url
```

**Fields:**
- `zoom_uuid`: Unique Zoom recording ID (primary key)
- `meeting_topic`: Meeting name/title
- `start_time`: ISO 8601 timestamp
- `file_path`: Local file path
- `video_ready_at`: ISO timestamp when video first appeared in Zoom cloud
- `vtt_ready_at`: ISO timestamp when VTT transcript first appeared in Zoom cloud
- `zoom_downloaded_at`: ISO timestamp when downloaded
- `youtube_uploaded_at`: ISO timestamp when uploaded (empty if failed)
- `youtube_url`: YouTube video URL (empty if not uploaded)
- `discord_notified_at`: ISO timestamp when Discord notification sent (empty if failed)
- `status`: `waiting_for_vtt`, `downloaded`, `uploaded`, `transcribed`, `summarized`, `notified`, `failed`, `skipped`
- `error_message`: Error details if any step failed
- `failure_count`: Number of consecutive failures (resets on success)
- `error_notified_at`: Timestamp when error notification was last sent
- `last_notified_error`: Last error message that triggered a notification
- `transcribed_at`: ISO timestamp when transcribed (empty if not transcribed)
- `transcript_url`: GitHub URL to transcript (empty if not saved)
- `generated_title`: Title generated by Gemini (empty if not generated)
- `summarized_at`: ISO timestamp when summary generated (empty if not done)
- `summary_url`: GitHub URL to summary (empty if not saved)

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

The pipeline is stepwise: each step is guarded by a CSV flag, so the next run always resumes from the first missing step. A step that fails stops the pipeline for that recording and sets its status to `failed`. No Discord notification is sent until everything (download, upload, transcription, summary) succeeds.

- **Transient HTTP errors (5xx, 429, connection/timeout)**: API clients retry with exponential backoff via `utils.retry_with_backoff`. The Zoom OAuth token refresh distinguishes `invalid_grant` (token genuinely expired → trigger re-auth) from transient 5xx (retry and propagate without touching the token file). YouTube uploads, Gemini calls, GitHub pushes, and Discord webhooks all use the same retry helper.
- **Download failure**: Record error in CSV; retried on next run.
- **Upload failure**: Keep video file; status `failed`; retried on next run if file still exists.
- **Transcription / summary failure**: Both steps are mandatory and treated as a single unit. If either one fails, the record is marked failed and the pipeline stops. On retry, if the transcript already exists in the local clone it is loaded via `load_transcript_body` and only the summary is regenerated — no re-transcription cost.
- **Discord failure**: Record error in CSV; retried on next run (no earlier step is re-run).
- **Token refresh failure**: Distinguishes token-expired (re-auth flow) from transient errors (retry with backoff).

**Retry Logic:**
- On each run, `retry_failed_recordings` in `main.py` finds records with `status=failed` or an incomplete stage (e.g. uploaded but not notified) and retries them.
- `--zoom-uuid UUID` lets you manually target a single record for retry / reprocessing.
- Because every completed step is flagged in the CSV, retries never re-do completed work (no duplicate YouTube uploads, no duplicate Discord notifications, no wasted transcription tokens).

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

# Gemini API (transcription, title, summary)
GEMINI_API_KEY=your_gemini_api_key
GEMINI_MODEL=gemini-3-pro-preview
TRANSCRIPTION_PROMPT_PATH=./meeting-transcripts/prompts/transcription_prompt.txt
TITLE_PROMPT_PATH=./meeting-transcripts/prompts/title_prompt.txt
SUMMARY_PROMPT_PATH=./meeting-transcripts/prompts/summary_prompt.txt
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
- `google-genai` - Gemini API (transcription, title, summary)
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

