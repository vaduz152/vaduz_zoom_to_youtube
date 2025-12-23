# YouTube Upload Experiment

Independent prototype to upload a video as **Unlisted** to YouTube using Python and OAuth credentials stored in `.env`.

## Prerequisites

- Python 3.10+ and `pip`
- A Google account with access to YouTube
- **A YouTube channel** - You must have created a YouTube channel for your Google account (visit https://www.youtube.com and create one if needed)
- **Account verification for long videos** - YouTube requires account verification to upload videos longer than 15 minutes. Verify your account at https://www.youtube.com/verify if you plan to upload longer videos.
- Ability to run a local browser to complete OAuth once

## 1) Google Cloud + OAuth setup

1. **Create/select a project**
   - Go to https://console.cloud.google.com/
   - Create a new project or select an existing one

2. **Enable YouTube Data API v3**
   - In the left sidebar, click **APIs & Services** → **Library**
   - Search for "YouTube Data API v3"
   - Click on it and press **Enable**

3. **Configure OAuth consent screen**
   - In the left sidebar, click **APIs & Services** → **OAuth consent screen**
   - OR if you see "Google Auth Platform" in the sidebar, click that, then look for "OAuth consent screen" or "Audience" in the submenu
   - Select **External** as the user type (for personal/testing)
   - Fill in the required fields (App name, User support email, Developer contact)
   - Click **Save and Continue**
   - On the **Scopes** page, click **Add or Remove Scopes**
   - Search for and add: `https://www.googleapis.com/auth/youtube.upload`
   - Click **Update** then **Save and Continue**
   - On the **Test users** page (if in Testing mode), click **Add Users** and add your Google account email
   - Click **Save and Continue** through the remaining screens

4. **Create OAuth client credentials**
   - In the left sidebar, click **APIs & Services** → **Credentials**
   - OR if you're in "Google Auth Platform", click **Clients** in the sidebar
   - Click **Create Credentials** → **OAuth client ID**
   - Select **Desktop app** as the application type
   - Give it a name (e.g., "YouTube Uploader")
   - Click **Create**
   - Copy the **Client ID** and **Client Secret** (or download the JSON file)

## 2) .env configuration

Create `.env` in the script folder by copying the example file:

```bash
cp .env.example .env
```

Then edit `.env` and add your actual credentials:

```
YOUTUBE_CLIENT_ID=your_client_id
YOUTUBE_CLIENT_SECRET=your_client_secret
YOUTUBE_UPLOAD_DIR=./test_downloads   # folder to pick a video from
YOUTUBE_DEFAULT_DESCRIPTION=Uploaded via script
YOUTUBE_DEFAULT_TAGS=zoom,upload,automation
YOUTUBE_CATEGORY_ID=22                # People & Blogs
YOUTUBE_LOG_FILE=youtube_uploads_log.txt  # optional: log file for upload results
```

**Important:** Never commit the `.env` file to git! It contains sensitive credentials.

Notes:
- `YOUTUBE_UPLOAD_DIR` is where the script will look for videos (files with extensions: mp4, mov, mkv, webm).
- **When multiple videos are in a folder**: The script uploads **all videos** in the folder, sorted by modification time (newest first).
- The video title defaults based on folder contents:
  - **Single video in folder**: Uses folder name (e.g., `2025-11-27_1000`)
  - **Multiple videos in folder**: Uses `[folder name] - [file name]` format for each video (e.g., `2025-11-27_1000 - shared_screen`)
  - Override with `--title` if needed (when multiple videos, filename will still be appended).
- Tags are comma-separated.
- Privacy is forced to **unlisted** by the script.
- The OAuth token is automatically saved to `youtube_token.json` in the script folder after first authorization.
- Upload results are automatically saved to `youtube_uploads.txt` (or `YOUTUBE_LOG_FILE` if set). Each line contains: timestamp, folder path, YouTube URL.

## 3) Dependencies

Create and activate a virtualenv in the script folder, then install:

**On macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**On Windows:**
```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

## 4) First-time authorization

The first run launches a local server on port `8081` to complete the OAuth flow in your browser. After you grant access, the script saves `youtube_token.json` in the script folder for reuse.

## 5) Run the uploader

Examples:

```bash
# Use defaults from .env (uploads all videos in YOUTUBE_UPLOAD_DIR)
python upload_to_youtube.py

# Specify a folder (uploads all videos in that folder)
python upload_to_youtube.py --folder ./test_downloads/2025-11-27_1000

# Override title if needed (when multiple videos, filename will be appended)
python upload_to_youtube.py --folder ./test_downloads/2025-11-27_1000 --title "My meeting upload"
```

If successful, the script prints the video URL and saves the result to the log file (`youtube_uploads.txt` by default). Each log entry contains:
- Timestamp (ISO format)
- Folder path where the video was located
- YouTube video URL

## 6) Troubleshooting

- **"youtubeSignupRequired" error**: Your Google account must have a YouTube channel created. Visit https://www.youtube.com and create a channel if you haven't already.
- **"Video unavailable - This video was removed because it was too long"**: YouTube requires account verification to upload videos longer than 15 minutes. Verify your account at https://www.youtube.com/verify before uploading long videos.
- Ensure the OAuth client is of type **Desktop app**; Web app clients will fail.
- If you rotate client secrets, delete `youtube_token.json` and re-run to re-authorize.
- Check that the YouTube Data API is enabled in the project tied to your OAuth client.
- HTTP 403 with `quotaExceeded` means your project has exhausted daily quota; retry later or request more quota.


