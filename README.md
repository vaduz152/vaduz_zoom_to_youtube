# Zoom to YouTube Automation

Automated system that downloads Zoom cloud recordings and uploads them to YouTube, with Discord notifications.

## Features

- **Automated Downloads**: Fetches new Zoom cloud recordings hourly
- **Smart Video Selection**: Automatically selects the best video (gallery view preferred)
- **YouTube Upload**: Uploads videos as unlisted to YouTube
- **Discord Notifications**: Posts YouTube links to Discord channel via webhook
- **CSV Tracking**: Tracks all processed recordings in a CSV database
- **Retry Logic**: Automatically retries failed operations on next run
- **File Cleanup**: Automatically deletes old videos after retention period
- **Dry Run Mode**: Test without making actual changes

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for detailed architecture documentation.

## Prerequisites

- Python 3.10+
- Zoom account with cloud recording enabled
- Google account with YouTube channel created
- Discord server with webhook access

## Setup

### 1. Install Dependencies

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Zoom OAuth

1. Go to [Zoom Marketplace](https://marketplace.zoom.us/)
2. Create a **General App** (OAuth) - NOT Server-to-Server
3. Add scopes:
   - `cloud_recording:read:recording`
   - `cloud_recording:read:list_user_recordings`
4. Set redirect URI: `http://localhost:8080/redirect`
5. Copy Client ID and Client Secret

### 3. Configure YouTube OAuth

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create/select a project
3. Enable **YouTube Data API v3**
4. Configure OAuth consent screen:
   - Add scope: `https://www.googleapis.com/auth/youtube.upload`
   - Add your email as test user (if in testing mode)
5. Create OAuth credentials:
   - Type: **Desktop app**
   - Copy Client ID and Client Secret

### 4. Configure Discord Webhook

1. Open your Discord server
2. Go to Server Settings → Integrations → Webhooks
3. Create a new webhook
4. Copy the webhook URL

### 5. Create `.env` File

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

Then edit `.env` and replace the placeholder values with your actual credentials:

```bash
# Zoom OAuth Credentials
ZOOM_CLIENT_ID=your_zoom_client_id_here
ZOOM_CLIENT_SECRET=your_zoom_client_secret_here
ZOOM_REDIRECT_URI=http://localhost:8080/redirect
ZOOM_USER_ID=your_zoom_email@example.com

# YouTube OAuth Credentials
YOUTUBE_CLIENT_ID=your_youtube_client_id_here
YOUTUBE_CLIENT_SECRET=your_youtube_client_secret_here
YOUTUBE_DEFAULT_DESCRIPTION=Uploaded via automation
YOUTUBE_DEFAULT_TAGS=zoom,meeting,recording
YOUTUBE_CATEGORY_ID=22
# Optional: Pre-select a specific Google account (email address)
# Set this to avoid account picker when multiple accounts are logged in
YOUTUBE_LOGIN_HINT=your_google_account@gmail.com

# Discord Webhook URL
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/your_webhook_id/your_webhook_token

# Processing Configuration
LAST_MEETINGS_TO_PROCESS=3
MIN_VIDEO_LENGTH_SECONDS=60
VIDEO_RETENTION_DAYS=10
DOWNLOAD_DIR=./downloaded_videos
CSV_TRACKER_PATH=./processed_recordings.csv
LOG_FILE=./zoom_to_youtube.log
```

**Note:** The `.env` file is gitignored and should never be committed. Use `.env.example` as a template.

### 6. First-Time Authorization

Run the script once to authorize:

```bash
python main.py
```

**Zoom Authorization:**
- Script will display an authorization URL
- Visit the URL in your browser
- Authorize the app
- Copy the authorization code from the redirect URL
- Paste it into the script when prompted
- Refresh token will be saved to `.zoom_refresh_token`

**YouTube Authorization:**
- Script will open a browser window
- Sign in and authorize the app
- Token will be saved to `youtube_token.json`

## Usage

### Manual Run

```bash
# Normal run
python main.py

# Dry run (test without making changes)
python main.py --dry-run

# Verbose logging
python main.py --verbose
```

### Cron Setup

Add to crontab to run hourly:

```bash
crontab -e
```

Add this line (adjust paths as needed):

```bash
0 * * * * cd /path/to/vaduz_zoom_to_youtube && /path/to/venv/bin/python main.py >> /path/to/zoom_to_youtube.log 2>&1
```

## Configuration

All configuration is done via environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `LAST_MEETINGS_TO_PROCESS` | Number of recent meetings to process | `3` |
| `MIN_VIDEO_LENGTH_SECONDS` | Minimum video length (0 = no limit) | `60` |
| `VIDEO_RETENTION_DAYS` | Days to keep videos before cleanup | `10` |
| `DOWNLOAD_DIR` | Directory for downloaded videos | `./downloaded_videos` |
| `CSV_TRACKER_PATH` | Path to CSV tracking file | `./processed_recordings.csv` |
| `LOG_FILE` | Path to log file | `./zoom_to_youtube.log` |

## How It Works

1. **Fetch Recordings**: Gets last N meetings from Zoom (configurable)
2. **Check CSV**: Skips already processed recordings
3. **Select Best Video**: Chooses gallery view if available, falls back to speaker view
4. **Download**: Downloads video to `downloaded_videos/{meeting_folder}/`
5. **Upload**: Uploads to YouTube as unlisted video
6. **Notify**: Posts YouTube link to Discord
7. **Track**: Records all operations in CSV
8. **Retry**: On next run, retries any failed operations
9. **Cleanup**: Deletes videos older than retention period

## CSV Tracking

All processed recordings are tracked in `processed_recordings.csv`:

- `zoom_uuid`: Unique recording identifier
- `meeting_topic`: Meeting name
- `start_time`: Meeting start time
- `file_path`: Local file path
- `zoom_downloaded_at`: Download timestamp
- `youtube_uploaded_at`: Upload timestamp
- `youtube_url`: YouTube video URL
- `discord_notified_at`: Notification timestamp
- `status`: Current status (`downloaded`, `uploaded`, `notified`, `failed`)
- `error_message`: Error details if any step failed

## Error Handling

- **Download failures**: Recorded in CSV, skipped on next run
- **Upload failures**: Retried on next run if file exists
- **Discord failures**: Retried on next run if upload succeeded
- **Token expiration**: Script will prompt for re-authorization

## Troubleshooting

### "youtubeSignupRequired" Error
- Your Google account must have a YouTube channel
- Visit https://www.youtube.com and create a channel

### "Video too long" Error
- YouTube requires phone verification for videos >15 minutes
- Verify your account at https://www.youtube.com/verify

### Zoom Authorization Fails
- Make sure you're using a **General App** (OAuth), not Server-to-Server
- Check that redirect URI matches exactly
- Delete `.zoom_refresh_token` and re-authorize

### YouTube Authorization Fails
- Make sure OAuth client is type **Desktop app**
- Check that YouTube Data API v3 is enabled
- Delete `youtube_token.json` and re-authorize

### Multiple Google Accounts / Wrong Account Selected
- If you have multiple Google accounts logged in and want to use a specific one:
  - Set `YOUTUBE_LOGIN_HINT=your_account@gmail.com` in `.env` to pre-select that account
  - Or use an incognito/private window when authorizing
  - Or temporarily sign out of other accounts before authorizing

## Repository Structure

```
vaduz_zoom_to_youtube/
├── main.py                    # Main orchestrator
├── config.py                  # Configuration loader
├── zoom_client.py             # Zoom API client
├── youtube_client.py          # YouTube API client
├── discord_client.py          # Discord webhook client
├── video_tracker.py           # CSV tracking database
├── video_manager.py           # File cleanup logic
├── gallery_identifier.py     # Video selection logic
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── .env                       # Credentials (gitignored)
├── processed_recordings.csv   # Tracking database (gitignored)
├── zoom_to_youtube.log        # Log file (gitignored)
└── downloaded_videos/        # Video storage (gitignored)
```

## Prototypes

This repository also contains prototype modules in `prototype/`:
- `prototype/zoom_download/` - Original Zoom download prototype
- `prototype/youtube_upload/` - Original YouTube upload prototype

See their respective README files for prototype-specific documentation.

## License

CC0 1.0 — Public Domain Dedication
