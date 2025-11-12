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
```

### Download Recording
```
GET {download_url}
Headers:
  Authorization: Bearer {access_token}
```
- Download URLs are provided in the `recording_files` array
- Use streaming download for large files

## Recording File Types

### Priority Order (for selecting which file to download)
1. **`shared_screen_with_gallery_view`** - Preferred Gallery View with shared screen
2. **`gallery_view`** - Standard Gallery View
3. **`active_speaker`** - Fallback if no Gallery View available
4. **`shared_screen_with_speaker_view`** - Additional fallback

### Other File Types (skip these)
- `audio_only` - Audio track only
- `timeline` - Timeline metadata file
- `audio_transcript` - Transcript file
- `chat_file` - Chat messages
- `closed_caption` - Closed captions
- `shared_screen` - Shared screen without gallery/speaker

### Identification Logic
```python
def find_best_gallery_view_file(recording_files):
    # 1. Try shared_screen_with_gallery_view
    # 2. Try gallery_view
    # 3. Fall back to active_speaker
    # 4. Fall back to shared_screen_with_speaker_view
    # Return None if none found
```

## File Naming Convention

### Format
```
YYYY-MM-DD_HHMM_{recording_type}.mp4
```

### Examples
- `2025-11-11_1351_active_speaker.mp4`
- `2025-11-11_1317_shared_screen_with_gallery_view.mp4`
- `2025-11-11_1300_gallery_view.mp4`

### Notes
- Include date and time (HHMM) to ensure uniqueness for same-day meetings
- Exclude meeting topic from filename (it's always the same)
- Use `recording_type` as part of filename for easy identification

## Directory Structure

### Recommended Organization
```
downloads/
  YYYY-MM-DD/
    meeting-name/
      gallery_view.mp4
      active_speaker.mp4
      ...
```

### For Prototype (Simple)
```
test_downloads/
  YYYY-MM-DD_HHMM_{type}.mp4
```

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

### Download with Authentication
```python
headers = {"Authorization": f"Bearer {access_token}"}
response = requests.get(download_url, headers=headers, stream=True)
# Stream download for large files
```

### Date/Time Parsing
```python
from datetime import datetime
dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
date_str = dt.strftime("%Y-%m-%d")
time_str = dt.strftime("%H%M")
```

## Testing Results

### Successful Test Run
- ✅ Authentication works with refresh token
- ✅ Can list recordings (6 found in test)
- ✅ Can identify Gallery View files correctly
- ✅ Fallback to active_speaker works
- ✅ Downloads complete successfully
- ✅ Unique filenames prevent overwrites

### File Type Distribution (from test data)
- `gallery_view`: 4 files
- `shared_screen_with_gallery_view`: 2 files
- `active_speaker`: 6 files
- `shared_screen_with_speaker_view`: 1 file

## Next Steps for Full Implementation

1. **Add CSV Tracker** - Track processed recordings to avoid duplicates
2. **Organized Storage** - Use date/meeting directory structure
3. **Error Handling** - Retry logic, better error messages
4. **Logging** - File-based logging for debugging
5. **Scheduler** - Run every 10 minutes using `schedule` library
6. **YouTube Upload** - Integrate YouTube API for uploads
7. **Metadata Extraction** - Extract meeting info for YouTube titles/descriptions

## Key Files Reference

- `test_zoom_download.py` - Working prototype
- `gallery_identifier.py` - Gallery View identification logic
- `.zoom_refresh_token` - Saved refresh token (don't commit)
- `.env` - Credentials (don't commit)

## Important Notes

- Password-protected recordings require General OAuth app (not Server-to-Server)
- Refresh tokens are long-lived but can expire - handle re-authorization
- Always use streaming downloads for video files
- Include time in filenames to ensure uniqueness
- Test with real recordings to verify Gallery View identification

