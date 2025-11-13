"""Simple prototype to test downloading videos from Zoom cloud using OAuth authorization code flow."""
import requests
import base64
import os
import urllib.parse
from datetime import datetime
from dotenv import load_dotenv
from gallery_identifier import find_best_gallery_view_file

# Load environment variables
load_dotenv()

# Zoom credentials
ZOOM_CLIENT_ID = os.getenv("ZOOM_CLIENT_ID")
ZOOM_CLIENT_SECRET = os.getenv("ZOOM_CLIENT_SECRET")
ZOOM_REDIRECT_URI = os.getenv("ZOOM_REDIRECT_URI", "http://localhost:8080/redirect")
ZOOM_USER_ID = os.getenv("ZOOM_USER_ID")
REFRESH_TOKEN_FILE = ".zoom_refresh_token"


def get_authorization_url():
    """Generate the authorization URL for user to visit."""
    params = {
        "response_type": "code",
        "client_id": ZOOM_CLIENT_ID,
        "redirect_uri": ZOOM_REDIRECT_URI
    }
    url = "https://zoom.us/oauth/authorize?" + urllib.parse.urlencode(params)
    return url


def exchange_code_for_tokens(authorization_code):
    """Exchange authorization code for access token and refresh token."""
    print("Exchanging authorization code for tokens...")
    
    credentials = f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": ZOOM_REDIRECT_URI
    }
    
    response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    
    # Save refresh token for future use
    if refresh_token:
        with open(REFRESH_TOKEN_FILE, 'w') as f:
            f.write(refresh_token)
        print("✓ Refresh token saved for future use")
    
    return access_token, refresh_token


def get_access_token_from_refresh(refresh_token):
    """Get a new access token using refresh token."""
    credentials = f"{ZOOM_CLIENT_ID}:{ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "refresh_token",
        "refresh_token": refresh_token
    }
    
    response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    
    # Update refresh token if a new one is provided
    if new_refresh_token and new_refresh_token != refresh_token:
        with open(REFRESH_TOKEN_FILE, 'w') as f:
            f.write(new_refresh_token)
    
    return access_token


def get_zoom_access_token():
    """Get OAuth access token using refresh token or guide user through authorization."""
    print("Getting Zoom access token...")
    
    # Check if we have a saved refresh token
    if os.path.exists(REFRESH_TOKEN_FILE):
        print("  Found saved refresh token, using it to get access token...")
        with open(REFRESH_TOKEN_FILE, 'r') as f:
            refresh_token = f.read().strip()
        
        try:
            access_token = get_access_token_from_refresh(refresh_token)
            print("✓ Access token obtained from refresh token")
            return access_token
        except Exception as e:
            print(f"  Refresh token expired or invalid: {e}")
            print("  Need to re-authorize...")
            os.remove(REFRESH_TOKEN_FILE)
    
    # No valid refresh token, need to get authorization code
    print("\n" + "="*60)
    print("First-time authorization required!")
    print("="*60)
    print("\n1. Visit this URL in your browser to authorize the app:")
    print(f"\n   {get_authorization_url()}\n")
    print("2. After authorizing, you'll be redirected to your redirect URI.")
    print("3. Copy the 'code' parameter from the redirect URL.")
    print("   Example: http://localhost:8080/redirect?code=ABC123")
    print("   The code is: ABC123")
    print("\n" + "="*60)
    
    authorization_code = input("\nPaste the authorization code here: ").strip()
    
    if not authorization_code:
        raise Exception("No authorization code provided")
    
    access_token, refresh_token = exchange_code_for_tokens(authorization_code)
    print("✓ Access token obtained")
    return access_token


def list_recordings(access_token):
    """List recordings for the user."""
    print("\nFetching recordings...")
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://zoom.us/v2/users/{ZOOM_USER_ID}/recordings"
    params = {"page_size": 30}
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        print(f"  Error: {response.status_code}")
        print(f"  Response: {response.text}")
        print("\n  The token might not have the required scopes.")
        response.raise_for_status()
    
    data = response.json()
    recordings = data.get("meetings", [])
    
    print(f"✓ Found {len(recordings)} recordings")
    return recordings


def sanitize_filename(name):
    """Sanitize a string to be safe for use as a filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = name.strip(' .')
    if len(name) > 200:
        name = name[:200]
    return name


def is_video_file(recording_file):
    """
    Check if a recording file is a video file (not audio, transcript, etc.).
    
    Args:
        recording_file: A recording file object from Zoom API
    
    Returns:
        Boolean indicating if this is a video file
    """
    recording_type = recording_file.get("recording_type", "").lower()
    
    # Skip non-video files
    skip_types = [
        'audio_only',
        'timeline',
        'audio_transcript',
        'chat_file',
        'closed_caption'
    ]
    
    return recording_type not in skip_types


def get_all_video_files(recording_files):
    """
    Get all video files from a list of recording files.
    
    Args:
        recording_files: List of recording file objects from Zoom API
    
    Returns:
        List of video recording file objects
    """
    video_files = []
    for file in recording_files:
        if is_video_file(file):
            video_files.append(file)
    return video_files


def download_video(download_url, access_token, output_path):
    """Download a video file."""
    print(f"\nDownloading to {output_path}...")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(download_url, headers=headers, stream=True, timeout=300)
    response.raise_for_status()
    
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    file_size = os.path.getsize(output_path)
    print(f"✓ Downloaded {file_size / (1024*1024):.2f} MB")


def main():
    """Test downloading videos from Zoom."""
    print("=== Zoom Video Download Test ===\n")
    
    # Get access token
    access_token = get_zoom_access_token()
    
    # List recordings
    recordings = list_recordings(access_token)
    
    if not recordings:
        print("\nNo recordings found.")
        return
    
    # Get last 3 recordings (most recent first)
    last_3_recordings = recordings[:3]
    
    print(f"\n{'='*60}")
    print(f"Downloading ALL videos from last 3 meetings...")
    print(f"{'='*60}\n")
    
    total_downloaded = 0
    
    for idx, recording in enumerate(last_3_recordings, 1):
        meeting_topic = recording.get('topic', 'Untitled Meeting')
        start_time = recording.get('start_time', '')
        recording_id = recording.get('uuid', '')
        
        print(f"\n[{idx}/3] Processing: {meeting_topic}")
        print(f"  Start time: {start_time}")
        
        recording_files = recording.get("recording_files", [])
        
        # Get all video files (excluding audio_only, timeline, transcripts, etc.)
        video_files = get_all_video_files(recording_files)
        
        if not video_files:
            print(f"  ✗ No video files found (skipping)")
            continue
        
        # Identify the best file for YouTube upload (for reference)
        best_file = find_best_gallery_view_file(recording_files)
        best_type = best_file.get('recording_type', 'unknown') if best_file else None
        
        print(f"  Found {len(video_files)} video file(s)")
        if best_file:
            is_gallery = best_type in ['shared_screen_with_gallery_view', 'gallery_view']
            view_type = "Gallery View" if is_gallery else "Speaker View"
            print(f"  → Best for YouTube: {best_type} ({view_type})")
        
        # Create date/time strings for directory/filename
        try:
            dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
            date_str = dt.strftime("%Y-%m-%d")
            time_str = dt.strftime("%H%M")
        except (ValueError, AttributeError):
            date_str = datetime.now().strftime("%Y-%m-%d")
            time_str = datetime.now().strftime("%H%M")
        
        # Create directory for this recording
        recording_dir = f"test_downloads/{date_str}_{time_str}"
        os.makedirs(recording_dir, exist_ok=True)
        
        # Download all video files
        recording_downloaded = 0
        for video_file in video_files:
            file_type = video_file.get('recording_type', 'unknown')
            download_url = video_file.get('download_url')
            file_size = video_file.get('file_size', 0)
            
            if not download_url:
                print(f"    ✗ Skipping {file_type}: No download URL")
                continue
            
            filename = f"{file_type}.mp4"
            output_path = f"{recording_dir}/{filename}"
            
            # Skip if already downloaded
            if os.path.exists(output_path):
                print(f"    ⊙ Skipping {file_type}: Already exists")
                continue
            
            try:
                print(f"    ↓ Downloading {file_type} ({file_size / (1024*1024):.1f} MB)...")
                download_video(download_url, access_token, output_path)
                print(f"    ✓ Downloaded {file_type}")
                recording_downloaded += 1
                total_downloaded += 1
            except Exception as e:
                print(f"    ✗ Failed to download {file_type}: {e}")
        
        print(f"  ✓ Recording complete: {recording_downloaded}/{len(video_files)} files downloaded")
    
    print(f"\n{'='*60}")
    print(f"Download complete: {total_downloaded} total video files downloaded")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
