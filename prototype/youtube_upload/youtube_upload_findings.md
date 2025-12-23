# YouTube Upload Script Development Findings

This document captures all the critical nuances, requirements, and implementation details discovered while developing the YouTube upload script. It provides sufficient detail for another AI agent to recreate the script from scratch.

## Table of Contents

1. [Prerequisites & Account Requirements](#prerequisites--account-requirements)
2. [Google Cloud Platform Setup](#google-cloud-platform-setup)
3. [OAuth Implementation Details](#oauth-implementation-details)
4. [Video Selection Logic](#video-selection-logic)
5. [Title Generation Logic](#title-generation-logic)
6. [Upload Process Details](#upload-process-details)
7. [Logging & Result Tracking](#logging--result-tracking)
8. [Environment Variables](#environment-variables)
9. [Dependencies](#dependencies)
10. [Error Handling & Edge Cases](#error-handling--edge-cases)
11. [Common Issues & Solutions](#common-issues--solutions)

---

## Prerequisites & Account Requirements

### YouTube Channel Requirement

**Critical Discovery**: The Google account **must have a YouTube channel created** before uploading videos. This is not optional.

- **Error Encountered**: `HttpError 401` with message `"youtubeSignupRequired"`
- **Solution**: User must visit https://www.youtube.com and create a channel
- **Verification**: Check https://studio.youtube.com - if it loads, the channel exists
- **Implementation Note**: The script cannot detect this programmatically; it will fail with a 401 error if the channel doesn't exist

### Account Verification for Long Videos

**Critical Discovery**: YouTube requires **phone number verification** to upload videos longer than 15 minutes.

- **Error Encountered**: Video uploads successfully but YouTube removes it with message "This video was removed because it was too long"
- **Solution**: User must verify account at https://www.youtube.com/verify
- **Implementation Note**: The script cannot check video length or verification status before upload; this must be handled by the user

### OAuth Client Type Requirement

**Critical Discovery**: The OAuth client **must be of type "Desktop app"**, not "Web app".

- **Why**: The script uses `InstalledAppFlow` which requires desktop app credentials
- **Error**: Web app clients will fail during OAuth flow
- **Location**: Google Cloud Console → Credentials → Create Credentials → OAuth client ID → Application type: **Desktop app**

---

## Google Cloud Platform Setup

### Required Steps (in order)

1. **Create/Select Project**
   - Visit https://console.cloud.google.com/
   - Create new project or select existing

2. **Enable YouTube Data API v3**
   - Navigate: APIs & Services → Library
   - Search: "YouTube Data API v3"
   - Click "Enable"
   - **Note**: This must be done before creating OAuth credentials

3. **Configure OAuth Consent Screen**
   - **Navigation Path**: APIs & Services → OAuth consent screen
   - **Alternative Path**: If "Google Auth Platform" appears in sidebar, click it, then look for "Audience" or "OAuth consent screen"
   - **User Type**: Select "External" (for personal/testing)
   - **Required Fields**: App name, User support email, Developer contact
   - **Critical Scope**: Must add `https://www.googleapis.com/auth/youtube.upload`
   - **Test Users**: If in Testing mode, add your Google account email as a test user
   - **Important**: After adding scopes, you must re-authorize the app

4. **Create OAuth Client Credentials**
   - **Navigation Path**: APIs & Services → Credentials
   - **Alternative Path**: If in "Google Auth Platform", click "Clients" in sidebar
   - **Type**: Desktop app (NOT Web app)
   - **Output**: Client ID and Client Secret (or download JSON)

### OAuth Consent Screen Navigation Issue

**Discovery**: Google Cloud Console UI has changed, and the OAuth consent screen location varies:
- Sometimes under "APIs & Services → OAuth consent screen"
- Sometimes under "Google Auth Platform → Audience"
- The exact navigation depends on the Google Cloud Console version

**Solution**: Document both paths in instructions

---

## OAuth Implementation Details

### Required Scope

```python
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
```

**Critical**: This scope provides full upload permissions. Do not use read-only scopes.

### OAuth Flow Implementation

The script uses `InstalledAppFlow` from `google_auth_oauthlib.flow`:

```python
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
```

**Key Details**:
- **Port**: Uses port `8081` (must be available)
- **Prompt**: Uses `"consent"` to force re-authorization if needed
- **Method**: `run_local_server()` opens browser automatically
- **Redirect**: Google redirects to `http://localhost:8081/` with authorization code

### Token Management

**Token Storage**:
- **File**: `youtube_token.json` (default, configurable via `YOUTUBE_TOKEN_PATH`)
- **Format**: JSON file containing credentials
- **Location**: Script directory (same as script file)

**Token Lifecycle**:
1. **First Run**: No token exists → OAuth flow → Save token
2. **Subsequent Runs**: Load token → Check validity → Use if valid
3. **Expired Token**: Load token → Refresh using `refresh_token` → Save updated token
4. **Invalid Token**: Delete token file → Re-run OAuth flow

**Token Refresh Logic**:
```python
if creds and creds.expired and creds.refresh_token:
    creds.refresh(Request())
    token_file.write_text(creds.to_json())
    return creds
```

**Critical**: Always save the token after refresh, as the access token changes.

### Client Config Format

**Discovery**: When creating OAuth client manually (not using downloaded JSON), the config must match this exact structure:

```python
{
    "installed": {
        "client_id": "...",
        "client_secret": "...",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": "https://oauth2.googleapis.com/token",
    }
}
```

**Note**: The outer key must be `"installed"` (not `"web"` or `"client"`), matching the Desktop app type.

---

## Video Selection Logic

### Supported Video Formats

```python
VIDEO_EXTENSIONS = (".mp4", ".mov", ".mkv", ".webm")
```

**Case Handling**: Extension matching is case-insensitive (`.lower()` is used)

### File Discovery

**Method**: `folder.iterdir()` to list all files in directory

**Filtering**:
- Only files (not subdirectories): `p.is_file()`
- Extension match: `p.suffix.lower() in VIDEO_EXTENSIONS`

### Sorting Logic

**Critical Discovery**: Videos are sorted by **modification time** (newest first), not by filename.

```python
sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True)
```

**Rationale**: When multiple videos exist, upload the most recently modified one first (or all of them in order).

### Multiple Videos Behavior

**Discovery**: When multiple videos exist in a folder, the script uploads **ALL videos**, not just one.

**Implementation**:
- Get all videos: `get_videos(folder)` returns list of all video files
- Loop through all videos: `for video_path in video_files:`
- Upload each one sequentially

**Sorting**: Newest videos are processed first

---

## Title Generation Logic

### Title Rules (in priority order)

1. **Explicit Title Provided** (`--title` argument):
   - **Single video**: Use provided title as-is
   - **Multiple videos**: Append filename: `"{provided_title} - {filename}"`

2. **Multiple Videos (no explicit title)**:
   - Format: `"{folder_name} - {filename_without_extension}"`
   - Example: `"2025-12-02_1729 - active_speaker"`

3. **Single Video (no explicit title)**:
   - Format: `"{folder_name}"`
   - Example: `"2025-12-02_1729"`

### Filename Extraction

**Method**: Use `video_path.stem` (filename without extension)

**Why**: YouTube titles shouldn't include file extensions like `.mp4`

### Folder Name Source

**Method**: `folder.name` (just the folder name, not full path)

**Example**: 
- Path: `/path/to/test_downloads/2025-12-02_1729`
- Folder name: `2025-12-02_1729`

---

## Upload Process Details

### YouTube API Client

**Service**: YouTube Data API v3
**Build**: `build("youtube", "v3", credentials=creds)`

### Upload Method

**API Call**: `youtube.videos().insert(part="snippet,status", body=body, media_body=media)`

**Required Parts**: 
- `"snippet"`: Video metadata (title, description, tags, category)
- `"status"`: Privacy settings

### Media Upload Configuration

```python
MediaFileUpload(
    str(video_path), 
    chunksize=4 * 1024 * 1024,  # 4 MB chunks
    resumable=True
)
```

**Chunk Size**: 4 MB (4 * 1024 * 1024 bytes)
**Resumable**: `True` - allows resuming interrupted uploads

### Upload Progress Tracking

**Method**: `request.next_chunk()` returns `(status, response)` tuple

**Status Object**: Contains `progress()` method returning float 0.0-1.0

**Logging**: Progress logged as percentage: `logging.info("Upload progress: %.2f%%", status.progress() * 100)`

**Loop**: Continue until `response is not None` (upload complete)

### Response Handling

**Video ID**: Extracted from response: `response["id"]`

**URL Format**: `f"https://youtu.be/{video_id}"`

**Note**: YouTube provides short URL format (`youtu.be`) which is preferred over full URL

### Privacy Status

**Fixed Value**: `"unlisted"` (hardcoded in script)

**Why**: Requirement was to upload as unlisted, not public or private

**API Field**: `body["status"]["privacyStatus"] = "unlisted"`

### Category ID

**Default**: `"22"` (People & Blogs)

**Source**: Can be overridden via `--category` argument or `YOUTUBE_CATEGORY_ID` env var

**Note**: Must be string, not integer

### Tags Handling

**Format**: Comma-separated string from env var or argument

**Processing**: Split by comma, strip whitespace: `[t.strip() for t in args.tags.split(",")]`

**Optional**: If no tags provided, `tags` is `None` and not included in API request

**API Field**: `body["snippet"]["tags"] = tags_list` (only if tags exist)

---

## Logging & Result Tracking

### Log File Format

**Format**: Tab-separated values (TSV)

**Structure**: `{timestamp}\t{folder_path}\t{youtube_url}\n`

**Example**:
```
2025-12-23T15:17:40.415419	/absolute/path/to/folder	https://youtu.be/VIDEO_ID
```

### Timestamp Format

**Format**: ISO 8601 format

**Method**: `datetime.now().isoformat()`

**Example**: `2025-12-23T15:17:40.415419`

### Folder Path Format

**Critical**: Use **absolute path**, not relative

**Method**: `str(folder.resolve())`

**Why**: Ensures consistency regardless of current working directory

**Example**: `/Users/user/project/test_downloads/2025-12-02_1729`

### Log File Location

**Default**: `youtube_uploads.txt` (in script directory)

**Configurable**: Via `--log-file` argument or `YOUTUBE_LOG_FILE` env var

**Append Mode**: File opened with `"a"` mode (append), not `"w"` (overwrite)

**Encoding**: UTF-8 (explicitly specified)

### Multiple Uploads Logging

**Behavior**: Each video upload creates a separate log entry

**Order**: Log entries match upload order (newest videos first)

---

## Environment Variables

### Required Variables

**`YOUTUBE_CLIENT_ID`**
- **Source**: Google Cloud Console → OAuth Client credentials
- **Format**: String (e.g., `"24802794676-...apps.googleusercontent.com"`)
- **Error if missing**: `RuntimeError: Missing required environment variable: YOUTUBE_CLIENT_ID`

**`YOUTUBE_CLIENT_SECRET`**
- **Source**: Google Cloud Console → OAuth Client credentials
- **Format**: String (e.g., `"GOCSPX-..."`)
- **Error if missing**: `RuntimeError: Missing required environment variable: YOUTUBE_CLIENT_SECRET`

### Optional Variables

**`YOUTUBE_UPLOAD_DIR`**
- **Default**: `"./test_downloads"`
- **Purpose**: Default folder to search for videos
- **Format**: Relative or absolute path (expanded with `expanduser()`)

**`YOUTUBE_DEFAULT_DESCRIPTION`**
- **Default**: `"Uploaded via script."`
- **Purpose**: Default video description

**`YOUTUBE_DEFAULT_TAGS`**
- **Default**: `None` (no tags)
- **Format**: Comma-separated string (e.g., `"zoom,upload,automation"`)
- **Processing**: Split by comma and strip whitespace

**`YOUTUBE_CATEGORY_ID`**
- **Default**: `"22"` (People & Blogs)
- **Format**: String (must be string, not integer)
- **Purpose**: YouTube category ID

**`YOUTUBE_LOG_FILE`**
- **Default**: `"youtube_uploads.txt"`
- **Purpose**: Path to log file for upload results
- **Format**: Relative or absolute path

**`YOUTUBE_TOKEN_PATH`**
- **Default**: `"youtube_token.json"`
- **Purpose**: Path to OAuth token file
- **Format**: Relative or absolute path

### .env File Location

**Discovery**: `.env` file should be in the **script directory** (same directory as script)

**Implementation**: 
```python
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)
```

**Why**: Ensures script finds `.env` regardless of current working directory

---

## Dependencies

### Required Packages

```txt
google-api-python-client>=2.154.0
google-auth-httplib2>=0.2.0
google-auth-oauthlib>=1.2.0
python-dotenv>=1.0.0
```

### Optional Packages

```txt
tqdm>=4.67.1
```

**Note**: `tqdm` is listed but not actually used in the script (may have been planned for progress bars but not implemented)

### Python Version

**Requirement**: Python 3.10+

**Type Hints**: Uses modern syntax like `tuple[Path, int]` (Python 3.9+)

### Virtual Environment

**Recommendation**: Use isolated virtual environment

**Creation**:
```bash
python3 -m venv venv
source venv/bin/activate  # macOS/Linux
# or
venv\Scripts\activate  # Windows
```

---

## Error Handling & Edge Cases

### FileNotFoundError Cases

1. **Folder doesn't exist**:
   - **Error**: `FileNotFoundError(f"Folder not found: {folder}")`
   - **Check**: `folder.exists() and folder.is_dir()`

2. **No video files found**:
   - **Error**: `FileNotFoundError(f"No video files found in {folder}")`
   - **Check**: `len(candidates) == 0`

### RuntimeError Cases

**Missing Environment Variable**:
- **Error**: `RuntimeError(f"Missing required environment variable: {name}")`
- **Variables**: `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET`

### HttpError Cases

**401 Unauthorized**:
- **Cause**: Missing YouTube channel
- **Message**: `"youtubeSignupRequired"`
- **Solution**: User must create YouTube channel

**403 Forbidden**:
- **Cause**: Quota exceeded
- **Message**: `"quotaExceeded"`
- **Solution**: Wait or request quota increase

**Other HTTP Errors**:
- **Handling**: Caught and logged, script exits with error message

### Token Refresh Failures

**Scenario**: Token expired but refresh fails

**Current Behavior**: Script will attempt OAuth flow again (token file may need deletion)

**Note**: Script doesn't explicitly handle refresh failures; relies on OAuth flow retry

### Path Handling

**Relative Paths**: Expanded using `Path(args.folder).expanduser()`

**Why**: Handles `~/` home directory notation

**Absolute Paths**: Used for logging to ensure consistency

---

## Common Issues & Solutions

### Issue: "youtubeSignupRequired" Error

**Symptoms**: 
- `HttpError 401` during upload
- Message contains `"youtubeSignupRequired"`

**Root Cause**: Google account doesn't have YouTube channel

**Solution**:
1. Visit https://www.youtube.com
2. Sign in with the same Google account
3. Create a YouTube channel if prompted
4. Verify at https://studio.youtube.com

**Prevention**: Document this requirement in setup instructions

### Issue: Video Removed for Being Too Long

**Symptoms**:
- Upload succeeds
- Video appears briefly then disappears
- Error: "This video was removed because it was too long"

**Root Cause**: Account not verified for long videos (>15 minutes)

**Solution**:
1. Visit https://www.youtube.com/verify
2. Complete phone number verification
3. Re-upload video

**Prevention**: Document verification requirement in prerequisites

### Issue: OAuth Flow Fails

**Symptoms**: Browser opens but authorization fails

**Possible Causes**:
1. OAuth client is "Web app" type (should be "Desktop app")
2. Redirect URI mismatch
3. Scope not added to consent screen
4. Test user not added (if in Testing mode)

**Solutions**:
- Verify client type is "Desktop app"
- Ensure scope `https://www.googleapis.com/auth/youtube.upload` is added
- Add your email as test user if app is in Testing mode
- Delete `youtube_token.json` and retry

### Issue: Token File Not Found After Authorization

**Symptoms**: Authorization completes but token file doesn't appear

**Root Cause**: Script directory vs current working directory mismatch

**Solution**: Ensure `.env` file location logic uses `Path(__file__).parent`

### Issue: Multiple Videos Uploaded When Only One Expected

**Behavior**: Script uploads all videos in folder

**Expected**: This is intentional behavior (not a bug)

**Rationale**: When multiple videos exist, all should be uploaded with unique titles

**Override**: Use `--title` to customize, but filename will still be appended for multiple videos

### Issue: Port 8081 Already in Use

**Symptoms**: OAuth flow fails to start local server

**Solution**: 
- Change port in code: `flow.run_local_server(port=8082, ...)`
- Or kill process using port 8081

### Issue: Upload Progress Not Showing

**Behavior**: Progress logs appear during upload

**Note**: Progress is logged, not displayed in real-time UI

**Enhancement Opportunity**: Could use `tqdm` (already in requirements) for progress bar

---

## Implementation Notes for AI Agents

### Key Design Decisions

1. **Multiple Videos**: Script uploads ALL videos in folder, not just one
   - Rationale: User may have multiple recordings from same meeting
   - Title format distinguishes them automatically

2. **Title Logic**: Complex conditional logic based on video count and explicit title
   - Single video: Simple folder name
   - Multiple videos: Folder name + filename
   - Explicit title: Respects user input but appends filename for multiple videos

3. **Absolute Paths in Log**: Logs use absolute paths for consistency
   - Ensures log entries are unambiguous
   - Works regardless of script execution directory

4. **Token Refresh**: Automatic refresh without user interaction
   - Improves user experience
   - Handles token expiration gracefully

5. **Sequential Uploads**: Videos uploaded one at a time (not parallel)
   - Simpler error handling
   - Easier to track progress
   - Avoids rate limiting issues

### Code Structure Recommendations

1. **Separate Functions**:
   - `get_videos()`: File discovery and sorting
   - `upload_video()`: Single video upload logic
   - `ensure_credentials()`: OAuth and token management
   - `save_upload_result()`: Logging

2. **Error Handling**: Catch specific exceptions:
   - `HttpError`: API errors
   - `FileNotFoundError`: Missing files/folders
   - `RuntimeError`: Configuration errors

3. **Logging**: Use Python `logging` module, not `print()`
   - Allows log level control
   - Better for debugging
   - Professional output format

### Testing Considerations

1. **Test with single video folder**
2. **Test with multiple videos folder**
3. **Test with missing folder**
4. **Test with empty folder**
5. **Test with expired token**
6. **Test with invalid credentials**
7. **Test with unverified account (should fail gracefully)**

### Security Considerations

1. **Never commit `.env` file** (add to `.gitignore`)
2. **Never commit `youtube_token.json`** (add to `.gitignore`)
3. **Token file contains sensitive data** (refresh tokens)
4. **Client secret is sensitive** (store in `.env`, not code)

---

## Summary Checklist for Implementation

When recreating this script, ensure:

- [ ] Google Cloud project created
- [ ] YouTube Data API v3 enabled
- [ ] OAuth consent screen configured with `youtube.upload` scope
- [ ] OAuth client created as "Desktop app" type
- [ ] `.env` file with `YOUTUBE_CLIENT_ID` and `YOUTUBE_CLIENT_SECRET`
- [ ] YouTube channel created for Google account
- [ ] Account verified for long videos (if needed)
- [ ] Dependencies installed (`google-api-python-client`, `google-auth-oauthlib`, `python-dotenv`)
- [ ] OAuth flow implemented with `InstalledAppFlow`
- [ ] Token storage and refresh logic implemented
- [ ] Video discovery supports `.mp4`, `.mov`, `.mkv`, `.webm`
- [ ] Videos sorted by modification time (newest first)
- [ ] All videos uploaded when multiple exist
- [ ] Title logic handles single vs multiple videos
- [ ] Upload uses resumable chunks (4 MB)
- [ ] Progress logging implemented
- [ ] Log file uses tab-separated format with absolute paths
- [ ] Error handling for common failure cases
- [ ] Privacy status set to "unlisted"

---

## Additional Resources

- YouTube Data API v3 Documentation: https://developers.google.com/youtube/v3
- Google OAuth 2.0 Documentation: https://developers.google.com/identity/protocols/oauth2
- Google Auth Library Python: https://google-auth.readthedocs.io/
- YouTube API Python Client: https://github.com/googleapis/google-api-python-client

---

*Document created: December 2024*
*Last updated: Based on working implementation*

