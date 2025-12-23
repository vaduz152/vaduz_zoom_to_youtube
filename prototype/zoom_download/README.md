# Zoom to YouTube Uploader

A prototype tool that polls Zoom cloud recordings and uploads Gallery View videos to YouTube.

## Setup

### 1. Create Virtual Environment

Create and activate a Python virtual environment in the script folder:

**On macOS/Linux:**
```bash
python3 -m venv venv
source venv/bin/activate
```

**On Windows:**
```bash
python -m venv venv
venv\Scripts\activate
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Zoom API Credentials

You need to create a Zoom OAuth app with Client-to-Server authentication to access password-protected recordings.

#### Steps to get Zoom credentials:

1. **Go to Zoom Marketplace**
   - Visit: https://marketplace.zoom.us/
   - Sign in with your Zoom account

2. **Create an OAuth App (Client-to-Server)**
   - Click "Develop" → "Build App"
   - Choose **"General App"** (this uses OAuth 2.0 for Client-to-Server authentication)
   - **Do NOT choose "Server to Server OAuth App"** - that won't work with password-protected videos
   - Fill in app information:
     - App Name: (e.g., "Zoom to YouTube Uploader")
     - Company Name: (your company name)
     - Developer Contact: (your email)
   - Click "Create"

3. **Configure App Settings**
   - In the app settings, go to "Scopes" tab
   - Under the "Recording" product section, select:
     - **"View a recording"** - `cloud_recording:read:recording` (for downloading videos)
     - **"View all user recordings"** - `cloud_recording:read:list_user_recordings` (required to list recordings)
     - If you have admin access, you can also add `cloud_recording:read:list_user_recordings:admin`
   - Save changes
   - **Important:** After adding new scopes, you'll need to re-authorize the app (the script will guide you)
   
4. **Configure Redirect URI**
   - Go to the "Information" or "Basic Information" tab
   - Find "Redirect URL for OAuth" or "Whitelist URL"
   - Add: `http://localhost:8080/redirect` (or any URL you prefer)
   - This is where Zoom will redirect after authorization
   - Save changes

5. **Get Your Credentials**
   - Go to the "App Credentials" tab in your app settings
   - You'll find:
     - **Client ID** → `ZOOM_CLIENT_ID` (visible on the credentials page)
     - **Client Secret** → `ZOOM_CLIENT_SECRET` (click "Show" to reveal it)
     - **Account ID** → `ZOOM_ACCOUNT_ID` (may be optional for General OAuth apps)
       - For General OAuth apps, the Account ID might not be displayed or required
       - If you don't see it, you can try leaving it blank in your `.env` file
       - The test script will attempt authentication without it
       - If authentication fails, you may need to check Zoom's documentation or contact support

6. **Get Your User ID**
   - Your User ID is your Zoom user email address, or
   - You can find it in the Zoom API by making a test request, or
   - It's usually your email address used for Zoom

7. **Activate the App**
   - Make sure to activate the app in the Zoom Marketplace
   - You may need to publish it (or keep it in development mode for testing)

### 4. Create .env File

Create a `.env` file in the script folder with your credentials:

```
ZOOM_CLIENT_ID=your_actual_client_id_here
ZOOM_CLIENT_SECRET=your_actual_client_secret_here
ZOOM_REDIRECT_URI=http://localhost:8080/redirect
ZOOM_USER_ID=your_zoom_email@example.com
```

**Note:** `ZOOM_ACCOUNT_ID` is not needed for General OAuth apps.

**Important:** Never commit the `.env` file to git! It contains sensitive credentials.

## Configuration

### Application Settings

The script uses `config.py` in the script folder for configuration. Key settings:

- **`RECORDINGS_DATE_RANGE_DAYS`** (default: 365) - How many days back to fetch recordings from Zoom API
- **`LAST_MEETINGS_TO_PROCESS`** (default: 3) - How many most recent meetings to download. Set to `None` to process all.
- **`FOLDER_NAME_TEMPLATE`** (default: `"{date} {time} - {topic}"`) - Template for naming meeting folders
- **`DOWNLOAD_DIR`** (default: resolves to `test_downloads/` in repository root) - Directory where videos are downloaded. Can be overridden with environment variable.

You can override these by setting environment variables with the same names.

## Testing

### First-Time Authorization

Run the test script to verify you can download videos from Zoom:

```bash
python test_zoom_download.py
```

Make sure you're in the script folder and have activated the virtual environment.

**On first run**, the script will:
1. Display an authorization URL
2. Open that URL in your browser (or copy/paste it)
3. Authorize the app in Zoom
4. You'll be redirected to your redirect URI with a `code` parameter
5. Copy the code from the URL (e.g., `http://localhost:8080/redirect?code=ABC123`)
6. Paste the code into the script when prompted
7. The script will save a refresh token for future use

**On subsequent runs**, the script will automatically use the saved refresh token - no manual authorization needed!

The script will:
- Authenticate with Zoom (using refresh token)
- List your recordings
- Show details of the first recording
- Attempt to download the first file

## Notes

- The tool uses OAuth authorization code flow (required for General OAuth apps)
- The refresh token is saved in `.zoom_refresh_token` in the script folder (automatically created)
- The `.env` file should be in the script folder
- The virtual environment (`venv/`) should be created in the script folder
- Make sure your Zoom account has cloud recording enabled
- The test script downloads to `test_downloads/` directory in the repository root
- If the refresh token expires, you'll need to re-authorize (the script will guide you)

## Repository Structure

```
prototype/
├── zoom_download/          # Zoom download functionality (this folder)
│   ├── config.py
│   ├── gallery_identifier.py
│   ├── test_zoom_download.py
│   ├── requirements.txt
│   ├── .env                # Zoom credentials
│   ├── .zoom_refresh_token # OAuth refresh token
│   └── venv/               # Virtual environment
└── youtube_upload/         # YouTube upload functionality
    ├── upload_to_youtube.py
    ├── requirements.txt
    ├── README.md
    ├── .env                # YouTube credentials
    └── youtube_token.json

test_downloads/             # Downloaded Zoom videos (repository root)
```

