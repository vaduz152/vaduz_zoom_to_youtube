# Zoom Cloud Recording Download - Development Findings

This document summarizes all valuable findings from developing the Zoom cloud recording download prototype. Use this as a reference to build the full production script.

## Authentication

### App Type
- **Use "General App" (OAuth)** - NOT "Server-to-Server OAuth App"
- General OAuth apps are required for password-protected recordings
- Server-to-Server OAuth apps don't work with password-protected videos

### OAuth Flow
- **Authorization Code Flow** (not account_credentials or client_credentials)
- Requires one-time user authorization to get a refresh token
- Refresh token can be reused for automated access
- Refresh tokens should be saved to `.zoom_refresh_token` file

### Required Scopes
Add these scopes in Zoom Marketplace app settings:
1. `cloud_recording:read:recording` - "View a recording" (for downloading videos)
2. `cloud_recording:read:list_user_recordings` - "View all user recordings" (for listing recordings)

### Redirect URI
- Configure in app settings: `http://localhost:8080/redirect` (or any URL)
- Used during initial authorization flow

### Credentials Needed
- `ZOOM_CLIENT_ID` - From App Credentials page
- `ZOOM_CLIENT_SECRET` - From App Credentials page  
- `ZOOM_REDIRECT_URI` - Must match what's configured in app settings
- `ZOOM_USER_ID` - User email address whose recordings to fetch
- `ZOOM_ACCOUNT_ID` - NOT needed for General OAuth apps

## API Endpoints

### Get Access Token (using refresh token)
```
POST https://zoom.us/oauth/token
Headers:
  Authorization: Basic {base64(client_id:client_secret)}
  Content-Type: application/x-www-form-urlencoded
Body:
  grant_type=refresh_token
  refresh_token={refresh_token}
```

### List Recordings
```
GET https://zoom.us/v2/users/{user_id}/recordings
Headers:
  Authorization: Bearer {access_token}
Query Params:
  page_size=30
  from={YYYY-MM-DD} (optional)
  to={YYYY-MM-DD} (optional)
  next_page_token={token} (for pagination)
```

**IMPORTANT: Date Range Filtering**
- **Zoom API applies a default date filter** when `from` and `to` parameters are not specified
- Default filter is very restrictive (typically only 1-2 days)
- **Always specify explicit date range** to get all available recordings
- Recommended: Use 1 year back (`from` = 365 days ago, `to` = today)
- Example: Without date filter → 1 recording; With 6-month range → 28 recordings

**Pagination**
- API supports pagination via `next_page_token`
- Response includes: `page_count`, `page_size`, `total_records`, `next_page_token`
- If `next_page_token` exists, make additional requests with `next_page_token` parameter
- Continue until `next_page_token` is null/empty

### Download Recording
```
GET {download_url}
Headers:
  Authorization: Bearer {access_token}
```
- Download URLs are provided in the `recording_files` array
- Use streaming download for large files

## Recording Metadata

### Recording Object Fields (for YouTube Title Generation)

Each recording object from the Zoom API contains the following metadata fields:

#### Core Fields (Most Useful for YouTube)
- **`topic`** (string) - Meeting name/title - **PRIMARY FIELD FOR YOUTUBE TITLE**
- **`start_time`** (string) - ISO 8601 format: `2025-12-02T17:29:28Z` - **USEFUL FOR DATE IN TITLE**
- **`duration`** (integer) - Meeting duration in minutes (0 if not available)
- **`timezone`** (string) - Timezone of the meeting: `Europe/Moscow`, `America/New_York`, etc.
- **`uuid`** (string) - Unique recording identifier: `DqClgwqMRYmwXuDfFFAkog==`
- **`id`** (integer) - Meeting ID: `87542522271`

#### Additional Metadata Fields
- **`account_id`** (string) - Zoom account ID
- **`host_id`** (string) - Host user ID
- **`type`** (integer) - Meeting type (e.g., `8` for recurring meetings)
- **`recording_count`** (integer) - Number of recording files in this meeting
- **`total_size`** (integer) - Total size of all recording files in bytes
- **`auto_delete`** (boolean) - Whether recording will auto-delete
- **`auto_delete_date`** (string) - Date when recording will be auto-deleted: `2026-01-31`
- **`share_url`** (string) - Public share URL for the recording
- **`recording_play_passcode`** (string) - Passcode for accessing the recording

### Recording File Object Fields

Each file in the `recording_files` array contains:

#### Core Fields
- **`recording_type`** (string) - Type of recording: `gallery_view`, `active_speaker`, `shared_screen_with_gallery_view`, etc.
- **`file_size`** (integer) - File size in bytes
- **`file_type`** (string) - File format: `MP4`, `M4A`, etc.
- **`file_extension`** (string) - File extension: `MP4`, `M4A`, etc.
- **`status`** (string) - Recording status: `completed`, `processing`, etc.

#### Time Information
- **`recording_start`** (string) - ISO 8601 format: `2025-12-02T17:29:29Z`
- **`recording_end`** (string) - ISO 8601 format: `2025-12-02T17:29:34Z`

#### Identifiers
- **`id`** (string) - Unique file identifier: `4a4ff5d0-f599-4713-9e41-215f5b8efa1b`
- **`meeting_id`** (string) - Meeting UUID (same as recording `uuid`)

#### URLs
- **`download_url`** (string) - URL to download the file (requires authentication)
- **`play_url`** (string) - URL to play the file in browser

### Recommended YouTube Title Format

Based on available metadata, recommended title formats:

**Format 1: Simple**
```
{topic} - {date}
```
Example: `Вместе на полянке - 2025-12-02`

**Format 2: With Time**
```
{topic} - {date} {time}
```
Example: `Вместе на полянке - 2025-12-02 17:29`

**Format 3: With Duration**
```
{topic} - {date} ({duration} min)
```
Example: `Вместе на полянке - 2025-12-02 (45 min)`

**Format 4: Full**
```
{topic} - {date} {time} ({duration} min)
```
Example: `Вместе на полянке - 2025-12-02 17:29 (45 min)`

### Date/Time Parsing Example

```python
from datetime import datetime

# Parse start_time
start_time = recording.get('start_time')  # "2025-12-02T17:29:28Z"
dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))

# Format for YouTube title
date_str = dt.strftime("%Y-%m-%d")  # "2025-12-02"
time_str = dt.strftime("%H:%M")      # "17:29"
date_time_str = dt.strftime("%Y-%m-%d %H:%M")  # "2025-12-02 17:29"

# Get duration
duration = recording.get('duration', 0)  # minutes

# Build title
topic = recording.get('topic', 'Untitled Meeting')
title = f"{topic} - {date_str} {time_str}"
if duration > 0:
    title = f"{topic} - {date_str} {time_str} ({duration} min)"
```

## Recording File Types

### Download Strategy
- **Download ALL video files** from each recording
- Then select the best file for YouTube upload based on priority
- This ensures all videos are available locally for reference/backup

### Video Files (download these)
1. **`shared_screen_with_gallery_view`** - Preferred Gallery View with shared screen
2. **`gallery_view`** - Standard Gallery View
3. **`active_speaker`** - Speaker view
4. **`shared_screen_with_speaker_view`** - Shared screen with speaker view
5. **`shared_screen`** - Shared screen only

### Non-Video Files (skip these)
- `audio_only` - Audio track only
- `timeline` - Timeline metadata file
- `audio_transcript` - Transcript file
- `chat_file` - Chat messages
- `closed_caption` - Closed captions

### Priority Order (for selecting which file to upload to YouTube)
1. **`shared_screen_with_gallery_view`** - Preferred Gallery View with shared screen
2. **`gallery_view`** - Standard Gallery View
3. **`active_speaker`** - Fallback if no Gallery View available
4. **`shared_screen_with_speaker_view`** - Additional fallback

### Identification Logic
```python
def is_video_file(recording_file):
    # Returns True if file is a video (not audio_only, timeline, etc.)

def get_all_video_files(recording_files):
    # Returns all video files from a recording

def find_best_gallery_view_file(recording_files):
    # 1. Try shared_screen_with_gallery_view
    # 2. Try gallery_view
    # 3. Fall back to active_speaker
    # 4. Fall back to shared_screen_with_speaker_view
    # Returns best file for YouTube upload (for reference)
```

## File Naming Convention

### Directory Structure
```
test_downloads/
  YYYY-MM-DD_HHMM/
    {recording_type}.mp4
    {recording_type}.mp4
    ...
```

### File Format
```
{recording_type}.mp4
```

### Examples
```
test_downloads/
  2025-11-13_1401/
    active_speaker.mp4
    shared_screen_with_speaker_view.mp4
    shared_screen.mp4
    gallery_view.mp4
    shared_screen_with_gallery_view.mp4  ← Best for YouTube
```

### Notes
- Each recording gets its own directory: `YYYY-MM-DD_HHMM/`
- Include date and time in directory name to ensure uniqueness for same-day meetings
- Files are named by their `recording_type` for easy identification
- Exclude meeting topic from filename (it's always the same)
- All video files are downloaded, best file for YouTube is identified separately

## Directory Structure

### Current Implementation
```
test_downloads/
  YYYY-MM-DD_HHMM/
    active_speaker.mp4
    shared_screen_with_speaker_view.mp4
    shared_screen.mp4
    gallery_view.mp4
    shared_screen_with_gallery_view.mp4
```

### Recommended for Production
```
downloads/
  YYYY-MM-DD/
    HHMM/
      active_speaker.mp4
      shared_screen_with_speaker_view.mp4
      shared_screen.mp4
      gallery_view.mp4
      shared_screen_with_gallery_view.mp4
```

### Notes
- Each recording gets its own directory based on date and time
- All video files are stored together for easy access
- Best file for YouTube upload is identified but all files are kept

## Common Issues & Solutions

### Issue: "unsupported_grant_type"
- **Cause**: Trying to use `account_credentials` or `client_credentials` with General OAuth app
- **Solution**: Use authorization code flow with refresh token

### Issue: "Invalid access token, does not contain scopes"
- **Cause**: Missing required scopes in app configuration
- **Solution**: Add `cloud_recording:read:list_user_recordings` scope in Zoom Marketplace

### Issue: "This API does not support client credentials"
- **Cause**: Trying to use client_credentials grant type
- **Solution**: Use refresh token flow instead

### Issue: Refresh token expired
- **Cause**: Token expired or invalidated
- **Solution**: Re-run authorization flow to get new refresh token

### Issue: Duplicate filenames
- **Cause**: Multiple meetings on same day with same topic
- **Solution**: Include time (HHMM) in filename

### Issue: API returns only 1 recording when more are available
- **Cause**: Zoom API applies a restrictive default date filter (1-2 days) when no date range is specified
- **Solution**: Always explicitly set `from` and `to` date parameters when calling the API
- **Example**: 
  - Without date filter: Returns only recordings from last 1-2 days
  - With 6-month range: Returns all recordings from that period
  - Recommended: Use 1 year range (`from` = 365 days ago, `to` = today) to capture all available recordings

## Code Patterns

### Refresh Token Management
```python
# Check for saved refresh token
if os.path.exists('.zoom_refresh_token'):
    refresh_token = read_from_file('.zoom_refresh_token')
    access_token = get_access_token_from_refresh(refresh_token)
else:
    # Guide user through authorization code flow
    authorization_code = get_from_user()
    access_token, refresh_token = exchange_code_for_tokens(authorization_code)
    save_refresh_token(refresh_token)
```

### Download All Video Files
```python
def is_video_file(recording_file):
    # Skip non-video files: audio_only, timeline, audio_transcript, etc.
    skip_types = ['audio_only', 'timeline', 'audio_transcript', 'chat_file', 'closed_caption']
    return recording_file.get('recording_type', '').lower() not in skip_types

def get_all_video_files(recording_files):
    return [f for f in recording_files if is_video_file(f)]

# Download all video files
video_files = get_all_video_files(recording_files)
for video_file in video_files:
    download_video(video_file['download_url'], access_token, output_path)

# Identify best file for YouTube upload
best_file = find_best_gallery_view_file(recording_files)
```

### Download with Authentication
```python
headers = {"Authorization": f"Bearer {access_token}"}
response = requests.get(download_url, headers=headers, stream=True, timeout=300)
# Stream download for large files
# Skip if file already exists
if os.path.exists(output_path):
    continue
```

### Date/Time Parsing and Directory Creation
```python
from datetime import datetime
dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
date_str = dt.strftime("%Y-%m-%d")
time_str = dt.strftime("%H%M")

# Create directory for recording
recording_dir = f"downloads/{date_str}_{time_str}"
os.makedirs(recording_dir, exist_ok=True)
```

### List Recordings with Date Range and Pagination
```python
def list_recordings(access_token, page_size=30, from_date=None, to_date=None):
    url = f"https://zoom.us/v2/users/{user_id}/recordings"
    params = {"page_size": page_size}
    
    # IMPORTANT: Always set date range to avoid Zoom's restrictive default filter
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    
    all_recordings = []
    next_page_token = None
    
    while True:
        if next_page_token:
            params["next_page_token"] = next_page_token
        
        response = requests.get(url, headers=headers, params=params)
        data = response.json()
        
        recordings = data.get("meetings", [])
        all_recordings.extend(recordings)
        
        next_page_token = data.get("next_page_token")
        if not next_page_token:
            break
    
    return all_recordings

# Usage: Always specify date range
from datetime import timedelta
to_date = datetime.now().strftime("%Y-%m-%d")
from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
recordings = list_recordings(access_token, from_date=from_date, to_date=to_date)
```

## Testing Results

### Successful Test Run
- ✅ Authentication works with refresh token
- ✅ Can list recordings (4 found in test)
- ✅ Downloads ALL video files from each recording
- ✅ Can identify best file for YouTube upload correctly
- ✅ Fallback to active_speaker works
- ✅ Downloads complete successfully
- ✅ Organized by recording directory prevents overwrites
- ✅ Skips already downloaded files

### Example Test Results
- **Recording 1**: Downloaded 5 video files (including `shared_screen_with_gallery_view` - best for YouTube)
- **Recording 2**: Downloaded 1 video file (`active_speaker`)
- **Recording 3**: Downloaded 1 video file (`active_speaker`)
- **Total**: 7 video files downloaded across 3 recordings

### File Type Distribution (from test data)
- `gallery_view`: Found in recordings
- `shared_screen_with_gallery_view`: Found in recordings (preferred)
- `active_speaker`: Found in all recordings
- `shared_screen_with_speaker_view`: Found in some recordings
- `shared_screen`: Found in some recordings

## Next Steps for Full Implementation

1. **Add CSV Tracker** - Track processed recordings to avoid duplicates
2. **Select Best File for Upload** - Use `find_best_gallery_view_file()` to identify which file to upload to YouTube
3. **Error Handling** - Retry logic, better error messages
4. **Logging** - File-based logging for debugging
5. **Scheduler** - Run every 10 minutes using `schedule` library
6. **YouTube Upload** - Integrate YouTube API for uploads (upload only the best file, keep all files locally)
7. **Metadata Extraction** - Extract meeting info for YouTube titles/descriptions
8. **Cleanup** - Optionally delete local files after successful YouTube upload (or keep as backup)

## Key Files Reference

- `test_zoom_download.py` - Working prototype
- `gallery_identifier.py` - Gallery View identification logic
- `.zoom_refresh_token` - Saved refresh token (don't commit)
- `.env` - Credentials (don't commit)

## Important Notes

- Password-protected recordings require General OAuth app (not Server-to-Server)
- Refresh tokens are long-lived but can expire - handle re-authorization
- Always use streaming downloads for large video files
- Download ALL video files from each recording, then select best for YouTube upload
- Organize files by recording directory (date_time) to prevent overwrites
- Skip already downloaded files to avoid re-downloading
- Include time in directory names to ensure uniqueness for same-day meetings
- Test with real recordings to verify Gallery View identification
- Keep all downloaded files locally even after YouTube upload (for backup/reference)

