# Zoom to YouTube Automation

Automated system that downloads Zoom cloud recordings and uploads them to YouTube, with transcripts, summaries, and Discord notifications.

## Features

- **Automated Downloads**: Fetches new Zoom cloud recordings every 10 minutes
- **Smart Video Selection**: Automatically selects the best video (gallery view preferred)
- **YouTube Upload**: Uploads videos as unlisted to YouTube
- **Gemini Transcription**: Transcribes videos with speaker diarization (VTT speaker hints for accuracy)
- **Gemini Summaries**: Generates structured meeting summaries that adapt to what actually happened (check-ins, technical discussions, forums, meditations, etc.)
- **Cross-linked Markdown**: Transcript and summary files carry links to each other and live in a private GitHub repo
- **Discord Notifications**: Posts YouTube + transcript + summary + cost to a Discord channel via webhook
- **Error Notifications**: Discord alerts for token expiration, repeated failures, or resolved errors
- **CSV Tracking**: Tracks every step (download, upload, transcription, summary, notification) in a CSV database
- **Smart Retry**: Next run picks up from exactly where the last run stopped — never re-runs completed steps
- **Single-Record Mode**: Process one specific recording with `--zoom-uuid UUID` (useful for debugging or backfilling)
- **Local Mode**: Process pre-downloaded videos from a folder with `--local`
- **Token Management**: Automatically handles token expiration, retries transient 5xx/network errors
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
6. **Recommended:** Publish the OAuth app (OAuth consent screen → "Publish App")
   - Without publishing, refresh tokens expire after 7 days
   - Publishing extends token lifetime to ~6 months of inactivity
   - No verification required for personal use
   - See [Testing vs Published Mode](#youtube-oauth-app-testing-vs-published-mode) for details

### 4. Create Meeting Data Repository

Prompts, transcripts, and summaries are stored in a separate **private** GitHub repository. This keeps sensitive content out of the main repo and ensures nothing is lost when migrating servers.

1. Create a new **private** repository on GitHub (e.g. `meeting-transcripts`)
2. Initialize it with the required structure:

```bash
git clone git@github.com:YOUR_ORG/meeting-transcripts.git
cd meeting-transcripts
mkdir transcripts prompts summaries

# Copy prompt templates and customize them for your project
cp ../prompts_examples/*.txt.example prompts/
# Rename .example files and edit as needed:
mv prompts/transcription_prompt.txt.example prompts/transcription_prompt.txt
mv prompts/title_prompt.txt.example prompts/title_prompt.txt
mv prompts/discord_notification.txt.example prompts/discord_notification.txt

git add -A && git commit -m "Initial structure" && git push
```

3. Set the repo URL in `.env`:

```bash
TRANSCRIPTS_REPO_URL=git@github.com:YOUR_ORG/meeting-transcripts.git
TRANSCRIPTS_REPO_PATH=./meeting-transcripts
TRANSCRIPTS_GITHUB_REPO=YOUR_ORG/meeting-transcripts
```

The repo will be cloned automatically on first run. On a new server, just configure `.env` — prompts come along with the clone.

### 5. Configure Discord Webhook

1. Open your Discord server
2. Go to Server Settings → Integrations → Webhooks
3. Create a new webhook
4. Copy the webhook URL

### 6. Create `.env` File

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
ERROR_NOTIFICATION_THRESHOLD=3
DOWNLOAD_DIR=./downloaded_videos
CSV_TRACKER_PATH=./processed_recordings.csv
LOG_FILE=./zoom_to_youtube.log
```

**Note:** The `.env` file is gitignored and should never be committed. Use `.env.example` as a template.

### 7. First-Time Authorization

**Important: If running on a remote host via SSH**, you need to set up port forwarding **before** running the script. This allows OAuth redirects to work automatically.

#### Setting Up Port Forwarding (Remote Host Only)

If you're connecting to a remote server via SSH, open a **separate terminal** and run:

```bash
ssh -L 8080:localhost:8080 -L 8082:localhost:8082 user@remote-host
```

Replace `user@remote-host` with your actual SSH connection details. Keep this terminal open - closing it will close the port forwarding tunnel.

**What this does:**
- Creates tunnels from your local machine's ports 8080 and 8082 to the remote host
- When OAuth redirects to `localhost:8080` or `localhost:8082`, SSH forwards them to the remote server
- The script can automatically capture authorization codes without manual copying

#### Running Authorization

Run the script once to authorize:

```bash
python main.py
```

**Zoom Authorization:**
- Script will display an authorization URL
- Visit the URL in your browser (on your local machine)
- Authorize the app
- **With port forwarding:** The code will be captured automatically - you'll see a success page
- **Without port forwarding:** Copy the authorization code from the redirect URL (even if you see an error page, the code is in the browser's address bar)
- Paste it into the script when prompted (if automatic capture failed)
- Refresh token will be saved to `.zoom_refresh_token`

**YouTube Authorization:**
- Script will display an authorization URL
- Visit the URL in your browser (on your local machine)
- Sign in and authorize the app
- **With port forwarding:** The code will be captured automatically - you'll see a success page
- **Without port forwarding:** Copy the authorization code from the redirect URL (even if you see an error page, the code is in the browser's address bar)
- Paste it into the script when prompted (if automatic capture failed)
- Token will be saved to `youtube_token.json`

**Note:** After first-time authorization, tokens are saved and you won't need to authorize again unless tokens expire. Port forwarding is only needed during the initial authorization process or when re-authorizing after token expiration.

**Token Expiration:** If tokens expire or are revoked, you'll receive a Discord notification with error details. The script will automatically prompt for re-authorization on the next run. Make sure port forwarding is set up again if you're on a remote host.

**Important:** On the first launch, the script will process and send the last 3 videos from Zoom Cloud to Discord (as configured by `LAST_MEETINGS_TO_PROCESS`). Subsequent runs will only process new recordings that haven't been processed yet.

## Usage

### Manual Run

```bash
# Normal run (fetch + process new recordings)
python main.py

# Dry run (test without making changes)
python main.py --dry-run

# Verbose logging
python main.py --verbose

# Process a single recording by Zoom UUID (respects CSV state, runs only missing steps)
python main.py --zoom-uuid 'abc123=='

# Process pre-downloaded videos from LOCAL_VIDEOS_DIR instead of Zoom cloud
python main.py --local
```

### Cron Setup

Add to crontab to run every 10 minutes:

```bash
crontab -e
```

Add this line (adjust paths as needed):

```bash
*/10 * * * * cd /path/to/vaduz_zoom_to_youtube && /path/to/venv/bin/python main.py >> /path/to/zoom_to_youtube.log 2>&1
```

Frequent runs are needed because the Zoom VTT transcript appears with a delay after the video is ready. The script detects video readiness first, then waits for the VTT to appear before processing.

## Configuration

All configuration is done via environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `LAST_MEETINGS_TO_PROCESS` | Number of recent meetings to process | `3` |
| `MIN_VIDEO_LENGTH_SECONDS` | Minimum video length (0 = no limit) | `60` |
| `VIDEO_RETENTION_DAYS` | Days to keep videos before cleanup | `10` |
| `ERROR_NOTIFICATION_THRESHOLD` | Number of consecutive failures before sending Discord notification | `3` |
| `DOWNLOAD_DIR` | Directory for downloaded videos | `./downloaded_videos` |
| `CSV_TRACKER_PATH` | Path to CSV tracking file | `./processed_recordings.csv` |
| `LOG_FILE` | Path to log file | `./zoom_to_youtube.log` |

## How It Works

1. **Fetch Recordings**: Gets last N meetings from Zoom (configurable)
2. **Check CSV**: Skips recordings that are already fully processed (all steps done)
3. **Select Best Video**: Chooses gallery view if available, falls back to speaker view
4. **Detect Video Ready**: Records `video_ready_at` timestamp in CSV
5. **Wait for VTT**: Checks if Zoom's audio transcript (VTT) is ready; if not, waits until next run
6. **Detect VTT Ready**: Records `vtt_ready_at` timestamp in CSV (logs delay from video readiness)
7. **Download**: Downloads video + VTT to `downloaded_videos/{meeting_folder}/`
8. **Upload**: Uploads to YouTube as unlisted video
9. **Transcribe + Summarize**:
    - Transcribes via Gemini with VTT speaker hints (chunked, 10-min segments)
    - Generates a descriptive title from the transcript
    - Generates a structured summary from the transcript (single universal prompt)
    - Writes transcript and summary to the private `meeting-transcripts` GitHub repo in a single commit, with cross-references in each file header
    - Updates YouTube video title to the generated one
10. **Notify**: Posts YouTube + transcript + summary + total Gemini cost to Discord
11. **Track**: Records all operations in CSV (including `transcribed_at`, `summarized_at`, `discord_notified_at`)
12. **Retry**: On next run, picks up from exactly where the last run stopped — never re-runs completed steps. Missing summaries are generated from the existing transcript in the local clone (no re-transcription cost).
13. **Cleanup**: Deletes videos older than retention period

## CSV Tracking

All processed recordings are tracked in `processed_recordings.csv`:

- `zoom_uuid`: Unique recording identifier
- `meeting_topic`: Meeting name
- `start_time`: Meeting start time
- `file_path`: Local file path
- `zoom_downloaded_at`: Download timestamp
- `youtube_uploaded_at`: Upload timestamp
- `youtube_url`: YouTube video URL
- `transcribed_at`: Transcription timestamp
- `transcript_url`: GitHub URL to transcript
- `generated_title`: Title generated from the transcript by Gemini
- `summarized_at`: Summary generation timestamp
- `summary_url`: GitHub URL to summary
- `discord_notified_at`: Notification timestamp
- `status`: Current status (`downloaded`, `uploaded`, `transcribed`, `summarized`, `notified`, `failed`, `skipped`)
- `error_message`: Error details if any step failed
- `failure_count`: Number of consecutive failures (resets on success)
- `error_notified_at`: Timestamp when error notification was last sent
- `last_notified_error`: Last error message that triggered a notification
- `video_ready_at`: Timestamp when video first appeared in Zoom cloud
- `vtt_ready_at`: Timestamp when VTT transcript first appeared in Zoom cloud

## Error Handling

The pipeline is step-by-step: each step checks the CSV, and if the step is already done it is skipped. If any step fails, the record is marked as `failed`, the rest of the pipeline for that recording is aborted, and the next run resumes from the failed step — without re-running any earlier completed step. No duplicate YouTube uploads, no duplicate Discord notifications, no re-transcription.

- **Transient HTTP errors (5xx, 429, network)**: API clients retry with exponential backoff (`retry_with_backoff` helper in `utils.py`). This covers Cloudflare errors on the Zoom OAuth token refresh endpoint, transient failures from YouTube / Gemini / Discord / GitHub, etc.
- **Download failures**: Recorded in CSV, retried on next run.
- **Upload failures**: Retried on next run if the video file still exists.
- **Transcription / summary failures**: Transcription and summary are both mandatory. If either one fails, the pipeline stops at that record and the next run retries. On retry, if the transcript already exists in the private repo clone it is loaded from disk and only the summary is generated (no re-transcription cost).
- **Discord failures**: Retried on next run; Discord is the final step, so retrying it does not trigger any re-work of earlier steps.
- **Token expiration/revocation**:
  - Automatically detected for both Zoom and YouTube tokens (distinguishes `invalid_grant` from transient 5xx).
  - Discord notification sent with error details.
  - Invalid token files are removed automatically.
  - Script prompts for re-authorization on next run; OAuth flow starts automatically.
- **Repeated-failure notifications**:
  - After `ERROR_NOTIFICATION_THRESHOLD` consecutive failures (default: 3), a Discord notification is sent.
  - Subsequent failures with the same error message do not trigger additional notifications (prevents spam).
  - If the error message changes, a new notification is sent.
  - When an error is resolved after multiple failures, a success notification is sent.
  - Failure count resets on successful operations.

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

### Token Expired or Revoked Error
If you see errors like `invalid_grant: Token has been expired or revoked`:

**What happens automatically:**
- Discord notification is sent with error details
- Invalid token file is removed
- Script will prompt for re-authorization on next run

**To fix:**
- **Zoom**: Delete `.zoom_refresh_token` and run the script again to re-authorize
- **YouTube**: Delete `youtube_token.json` and run the script again to re-authorize
- Make sure port forwarding is set up if running on a remote host (see "First-Time Authorization" section)

**Common causes:**
- Refresh token not used for extended period (6+ months for YouTube, varies for Zoom)
- User changed their account password (revokes all tokens)
- User manually revoked app access
- App in "Testing" mode (YouTube refresh tokens expire after 7 days)

### YouTube OAuth App: Testing vs Published Mode

Google OAuth apps have two modes that significantly affect refresh token lifetime:

| Mode | Refresh Token Lifetime | Who Can Authorize |
|------|------------------------|-------------------|
| **Testing** | 7 days (expires regardless of use) | Only test users listed in console |
| **Published** | ~6 months of inactivity | Anyone (but shows warning if unverified) |

**If your YouTube tokens expire every 7 days**, your OAuth app is likely in "Testing" mode.

**To publish your app (no verification required for personal use):**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to: **APIs & Services** → **OAuth consent screen**
3. Click **"Publish App"**
4. Confirm when warned about verification

**What happens after publishing:**
- Refresh tokens last much longer (~6 months of inactivity instead of 7 days)
- You'll see an "This app isn't verified" warning when authorizing
- Click **"Advanced"** → **"Go to [app name] (unsafe)"** to proceed
- This warning only appears during authorization, not during normal use

**Note:** Full verification is NOT required for personal use apps that only access your own data. Publishing without verification is sufficient for this automation tool.

### Repeated Failures / Error Notifications

The system tracks consecutive failures for each recording. When a recording fails `ERROR_NOTIFICATION_THRESHOLD` times (default: 3), a Discord notification is sent.

**How it works:**
- **First 3 failures**: No notification (transient errors are ignored)
- **After 3 failures**: Discord notification sent with error details
- **Subsequent failures**: If the error message is the same, no additional notification is sent (prevents spam)
- **Error changes**: If the error message changes, a new notification is sent
- **Success after failures**: When an error is resolved after multiple failures, a success notification is sent

**Example notification flow:**
1. Failure 1, 2, 3 → No notification
2. Failure 3 (threshold reached) → ⚠️ Error notification sent
3. Failure 4 (same error) → No notification (error persists)
4. Failure 5 (different error) → ⚠️ Error notification sent (new error type)
5. Success → ✅ Success notification sent (error resolved)

**Configuration:**
- Set `ERROR_NOTIFICATION_THRESHOLD` in `.env` to change when notifications are sent (default: 3)
- Lower values = more sensitive (notify sooner)
- Higher values = less sensitive (only notify for persistent issues)

**Note on Zoom processing delays:**
Zoom cloud recordings can take 2-6 hours to become available via the API after a meeting ends, especially for longer recordings. The VTT audio transcript appears with additional delay after the video is ready. The script tracks both readiness timestamps (`video_ready_at`, `vtt_ready_at`) and logs the delay. With 10-minute cron runs and `ERROR_NOTIFICATION_THRESHOLD=5`, you get ~50 minutes of retries before alerting, which accommodates most Zoom processing delays.

### Multiple Google Accounts / Wrong Account Selected
- If you have multiple Google accounts logged in and want to use a specific one:
  - Set `YOUTUBE_LOGIN_HINT=your_account@gmail.com` in `.env` to pre-select that account
  - Or use an incognito/private window when authorizing
  - Or temporarily sign out of other accounts before authorizing

## Meeting Data Repository

Prompts, transcripts, and summaries are stored in a separate **private** GitHub repository (configured via `TRANSCRIPTS_REPO_URL`). This keeps sensitive content out of the main (public) repo and ensures nothing is lost when migrating to a new server.

The repo is cloned automatically on first run. Expected structure:

```
meeting-transcripts/           # Private GitHub repo (cloned automatically)
├── transcripts/               # AI-generated meeting transcripts
│   └── 2026-03-20 12-00 - Topic.md
├── prompts/                   # Gemini & Discord templates
│   ├── transcription_prompt.txt
│   ├── title_prompt.txt
│   └── discord_notification.txt
└── summaries/                 # Meeting summaries (future)
```

On a fresh server, `git clone` + `git clone` of this repo is all that's needed — prompts come along automatically.

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
├── transcription_client.py    # Gemini transcription with VTT speaker hints
├── transcript_storage.py      # Git-based transcript storage (GitHub)
├── gallery_identifier.py      # Video selection logic
├── utils.py                   # Shared utilities (retry_with_backoff)
├── requirements.txt           # Python dependencies
├── .env.example               # Environment variables template
├── .env                       # Credentials (gitignored)
├── meeting-transcripts/       # Private data repo clone (gitignored)
├── processed_recordings.csv   # Tracking database (gitignored)
├── zoom_to_youtube.log        # Log file (gitignored)
└── downloaded_videos/         # Video storage (gitignored)
    └── {date} {time} - {title}/
        ├── {best_video}.mp4
        └── zoom_transcript.vtt  # Zoom VTT for speaker hints
```

## Prototypes

This repository also contains prototype modules in `prototype/`:
- `prototype/zoom_download/` - Original Zoom download prototype
- `prototype/youtube_upload/` - Original YouTube upload prototype
  - Contains `OAUTH_REMOTE_HOST_DEBUGGING.md` - Detailed notes on debugging OAuth flows when running on remote hosts
- `prototype/vtt_speaker_hints/` - VTT speaker hints prototype for prompt iteration

See their respective README files for prototype-specific documentation.

## License

CC0 1.0 — Public Domain Dedication
