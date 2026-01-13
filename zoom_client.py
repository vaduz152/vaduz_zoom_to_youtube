"""Zoom API client for downloading cloud recordings."""
import base64
import logging
import os
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
import time

import requests

import config
from gallery_identifier import find_best_gallery_view_file

logger = logging.getLogger(__name__)

# Import discord_client with error handling to avoid breaking OAuth flow if import fails
try:
    import discord_client
    DISCORD_AVAILABLE = True
except ImportError:
    DISCORD_AVAILABLE = False
    logger.warning("Discord client not available, error notifications will be skipped")


def get_authorization_url() -> str:
    """Generate the authorization URL for user to visit."""
    params = {
        "response_type": "code",
        "client_id": config.ZOOM_CLIENT_ID,
        "redirect_uri": config.ZOOM_REDIRECT_URI
    }
    url = "https://zoom.us/oauth/authorize?" + urllib.parse.urlencode(params)
    return url


def exchange_code_for_tokens(authorization_code: str) -> Tuple[str, str]:
    """Exchange authorization code for access token and refresh token."""
    logger.info("Exchanging authorization code for tokens...")
    
    credentials = f"{config.ZOOM_CLIENT_ID}:{config.ZOOM_CLIENT_SECRET}"
    encoded_credentials = base64.b64encode(credentials.encode()).decode()
    
    headers = {
        "Authorization": f"Basic {encoded_credentials}",
        "Content-Type": "application/x-www-form-urlencoded"
    }
    
    data = {
        "grant_type": "authorization_code",
        "code": authorization_code,
        "redirect_uri": config.ZOOM_REDIRECT_URI
    }
    
    response = requests.post("https://zoom.us/oauth/token", headers=headers, data=data)
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    
    # Save refresh token for future use
    if refresh_token:
        config.ZOOM_REFRESH_TOKEN_FILE.write_text(refresh_token)
        logger.info("Refresh token saved")
    
    return access_token, refresh_token


def get_access_token_from_refresh(refresh_token: str) -> str:
    """Get a new access token using refresh token."""
    credentials = f"{config.ZOOM_CLIENT_ID}:{config.ZOOM_CLIENT_SECRET}"
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
    
    # Check for token expiration/revocation errors before raising
    if response.status_code != 200:
        try:
            error_data = response.json()
            error_code = error_data.get("error", "")
            error_description = error_data.get("error_description", "")
            
            # Check for token expiration/revocation errors
            if error_code in ["invalid_grant", "invalid_token"] or "expired" in error_description.lower() or "revoked" in error_description.lower():
                error_msg = f"{error_code}: {error_description}" if error_description else error_code
                raise ValueError(f"Refresh token expired or revoked: {error_msg}")
        except (ValueError, KeyError):
            # If we can't parse the error or it's not a token expiration error, 
            # let raise_for_status() handle it
            # Note: ValueError here means we raised it ourselves for token expiration
            # If response.json() fails, it will raise on the next call, which is fine
            pass
    
    response.raise_for_status()
    
    token_data = response.json()
    access_token = token_data.get("access_token")
    new_refresh_token = token_data.get("refresh_token")
    
    # Update refresh token if a new one is provided
    if new_refresh_token and new_refresh_token != refresh_token:
        config.ZOOM_REFRESH_TOKEN_FILE.write_text(new_refresh_token)
    
    return access_token


class OAuthRedirectHandler(BaseHTTPRequestHandler):
    """HTTP request handler to capture OAuth redirect."""
    
    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        
        if 'code' in query_params:
            code = query_params['code'][0]
            self.server.authorization_code = code
            
            # Send success response
            self.send_response(200)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"""
                <html>
                <head><title>Authorization Successful</title></head>
                <body>
                    <h1>Authorization Successful!</h1>
                    <p>You can close this window and return to the terminal.</p>
                    <p>The authorization code has been captured automatically.</p>
                </body>
                </html>
            """)
        else:
            # Error case
            error = query_params.get('error', ['Unknown error'])[0]
            self.send_response(400)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(f"""
                <html>
                <head><title>Authorization Failed</title></head>
                <body>
                    <h1>Authorization Failed</h1>
                    <p>Error: {error}</p>
                    <p>Please check the terminal for instructions.</p>
                </body>
                </html>
            """.encode())
            self.server.authorization_code = None
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def start_oauth_server(port: int = 8080, timeout: int = 300) -> Optional[str]:
    """
    Start a local HTTP server to capture OAuth redirect.
    Returns the authorization code if captured, None otherwise.
    """
    import socket
    
    server_address = ('', port)
    httpd = HTTPServer(server_address, OAuthRedirectHandler)
    httpd.authorization_code = None
    httpd.socket.settimeout(1.0)  # Set socket timeout for non-blocking behavior
    
    logger.info(f"Starting OAuth redirect server on port {port}...")
    logger.info("Waiting for authorization (timeout: {} seconds)...".format(timeout))
    
    # Set a timeout for the server
    start_time = time.time()
    while httpd.authorization_code is None and (time.time() - start_time) < timeout:
        try:
            httpd.handle_request()
            if httpd.authorization_code is not None:
                break
        except socket.timeout:
            # Timeout is expected, continue waiting
            continue
    
    code = httpd.authorization_code
    httpd.server_close()
    
    if code:
        logger.info("Authorization code captured successfully!")
    else:
        logger.warning("Server timed out waiting for authorization code.")
    
    return code


def get_access_token() -> str:
    """Get OAuth access token using refresh token or guide user through authorization."""
    logger.info("Getting Zoom access token...")
    
    token_file = config.ZOOM_REFRESH_TOKEN_FILE
    
    # Check if we have a saved refresh token
    if token_file.exists():
        logger.debug("Found saved refresh token")
        refresh_token = token_file.read_text().strip()
        
        try:
            access_token = get_access_token_from_refresh(refresh_token)
            logger.info("Access token obtained from refresh token")
            return access_token
        except ValueError as e:
            # Token expired or revoked (specific error from get_access_token_from_refresh)
            error_str = str(e)
            logger.error("="*60)
            logger.error("Zoom refresh token has expired or been revoked!")
            logger.error("="*60)
            logger.error(f"Error details: {error_str}")
            logger.error("\nThe stored credentials are no longer valid.")
            logger.error("You will need to re-authorize. The OAuth flow will start now...")
            logger.error("="*60 + "\n")
            
            # Send Discord notification about the token error
            if DISCORD_AVAILABLE:
                try:
                    discord_client.send_error_notification(
                        error_message="Zoom refresh token has expired or been revoked",
                        error_details=error_str
                    )
                except Exception as discord_error:
                    # Don't let Discord notification failure break the OAuth flow
                    logger.warning(f"Failed to send Discord notification: {discord_error}")
            
            # Delete the invalid token file to force re-authorization
            if token_file.exists():
                token_file.unlink()
                logger.info("Removed invalid token file")
        except Exception as e:
            # Other errors (network issues, etc.)
            error_str = str(e)
            logger.warning(f"Refresh token failed: {error_str}")
            logger.info("Need to re-authorize...")
            
            # Send Discord notification for other token errors too
            if DISCORD_AVAILABLE:
                try:
                    discord_client.send_error_notification(
                        error_message="Zoom token refresh failed",
                        error_details=error_str
                    )
                except Exception as discord_error:
                    logger.warning(f"Failed to send Discord notification: {discord_error}")
            
            if token_file.exists():
                token_file.unlink()
    
    # No valid refresh token, need to get authorization code
    auth_url = get_authorization_url()
    
    # Parse redirect URI to get port
    redirect_uri = config.ZOOM_REDIRECT_URI
    parsed_uri = urlparse(redirect_uri)
    port = parsed_uri.port if parsed_uri.port else 8080
    
    logger.error("\n" + "="*60)
    logger.error("First-time authorization required!")
    logger.error("="*60)
    logger.error("\nOPTION 1: Automatic (Recommended if using SSH port forwarding)")
    logger.error("="*60)
    logger.error("1. If connecting via SSH, set up port forwarding FIRST:")
    logger.error(f"   ssh -L {port}:localhost:{port} user@remote-host")
    logger.error("   (Run this in a separate terminal before running the script)")
    logger.error("\n2. Visit this URL in your browser:")
    logger.error(f"\n   {auth_url}\n")
    logger.error("3. Click 'Allow' on the Zoom authorization page.")
    logger.error("4. The code will be captured automatically - you'll see a success page.")
    logger.error("\n" + "="*60)
    logger.error("OPTION 2: Manual (If port forwarding is not available)")
    logger.error("="*60)
    logger.error("1. Visit this URL in your browser:")
    logger.error(f"\n   {auth_url}\n")
    logger.error("2. Click 'Allow' on the Zoom authorization page.")
    logger.error("3. IMPORTANT: After clicking 'Allow', Zoom will redirect you.")
    logger.error("   Even if you see an error page (like 'Connection refused'),")
    logger.error("   LOOK AT YOUR BROWSER'S ADDRESS BAR - it will contain the code!")
    logger.error("\n4. The URL will look like:")
    logger.error("   http://localhost:8080/redirect?code=ABC123XYZ...")
    logger.error("\n5. Copy everything after 'code=' until the next '&' (if any).")
    logger.error("   Example: If URL is '...?code=ABC123&state=...', copy 'ABC123'")
    logger.error("\n" + "="*60)
    
    # Try to start server and capture code automatically
    logger.info("\nAttempting to capture authorization code automatically...")
    logger.info("(If this doesn't work, you can manually paste the code when prompted)")
    
    authorization_code = start_oauth_server(port=port, timeout=300)
    
    # If automatic capture failed, fall back to manual input
    if not authorization_code:
        logger.warning("\nAutomatic capture timed out or failed.")
        logger.info("Please manually extract the code from your browser's address bar.")
        logger.info("The URL will look like: http://localhost:8080/redirect?code=YOUR_CODE_HERE")
        logger.info("You can paste either:")
        logger.info("  - Just the code: ABC123XYZ...")
        logger.info("  - Or the full URL: http://localhost:8080/redirect?code=ABC123XYZ...")
        
        user_input = input("\nPaste the authorization code or full URL here: ").strip()
        
        # Extract code from URL if user pasted full URL
        if user_input.startswith('http'):
            parsed = urlparse(user_input)
            query_params = parse_qs(parsed.query)
            if 'code' in query_params:
                authorization_code = query_params['code'][0]
            else:
                authorization_code = user_input
        else:
            authorization_code = user_input
    
    if not authorization_code:
        raise Exception("No authorization code provided")
    
    access_token, refresh_token = exchange_code_for_tokens(authorization_code)
    logger.info("Access token obtained")
    return access_token


def list_recordings(
    access_token: str,
    limit: Optional[int] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    page_size: int = 30
) -> List[dict]:
    """List recordings for the user."""
    logger.info("Fetching recordings from Zoom...")
    
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    
    url = f"https://zoom.us/v2/users/{config.ZOOM_USER_ID}/recordings"
    params = {"page_size": page_size}
    
    # Add date filters if provided
    if from_date:
        params["from"] = from_date
    if to_date:
        params["to"] = to_date
    
    response = requests.get(url, headers=headers, params=params)
    
    if response.status_code != 200:
        logger.error(f"Error: {response.status_code}")
        logger.error(f"Response: {response.text}")
        response.raise_for_status()
    
    data = response.json()
    recordings = data.get("meetings", [])
    
    logger.info(f"Found {len(recordings)} recordings in this page")
    
    # Handle pagination if next_page_token exists
    all_recordings = recordings.copy()
    next_page_token = data.get("next_page_token")
    page_number = 1
    
    while next_page_token:
        logger.debug(f"Fetching page {page_number + 1}...")
        next_params = {"page_size": page_size, "next_page_token": next_page_token}
        if from_date:
            next_params["from"] = from_date
        if to_date:
            next_params["to"] = to_date
            
        response = requests.get(url, headers=headers, params=next_params)
        response.raise_for_status()
        
        page_data = response.json()
        page_recordings = page_data.get("meetings", [])
        all_recordings.extend(page_recordings)
        next_page_token = page_data.get("next_page_token")
        page_number += 1
        
        logger.debug(f"Found {len(page_recordings)} recordings in page {page_number}")
    
    if page_number > 1:
        logger.info(f"Total recordings across all pages: {len(all_recordings)}")
    
    # Apply limit if specified
    if limit:
        all_recordings = all_recordings[:limit]
    
    return all_recordings


def is_video_file(recording_file: dict) -> bool:
    """Check if a recording file is a video file (not audio, transcript, etc.)."""
    recording_type = recording_file.get("recording_type", "").lower()
    
    skip_types = [
        'audio_only',
        'timeline',
        'audio_transcript',
        'chat_file',
        'closed_caption'
    ]
    
    return recording_type not in skip_types


def find_best_video(recording_files: List[dict]) -> Optional[dict]:
    """
    Find the best video file from a list of recording files.
    Uses gallery_identifier logic: prefers gallery view, falls back to speaker view.
    """
    return find_best_gallery_view_file(recording_files)


def sanitize_filename(name: str) -> str:
    """Sanitize a string to be safe for use as a filename."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    name = name.strip(' .')
    if len(name) > 200:
        name = name[:200]
    return name


def generate_folder_name(recording: dict, template: str = "{date} {time} - {topic}") -> str:
    """Generate folder name for a recording based on template."""
    meeting_topic = recording.get('topic', 'Untitled Meeting')
    start_time = recording.get('start_time', '')
    
    # Parse start_time
    try:
        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H-%M")
        date_time_str = f"{date_str} {time_str}"
    except (ValueError, AttributeError):
        dt = datetime.now()
        date_str = dt.strftime("%Y-%m-%d")
        time_str = dt.strftime("%H-%M")
        date_time_str = f"{date_str} {time_str}"
    
    # Replace placeholders in template
    folder_name = template.format(
        date=date_str,
        time=time_str,
        date_time=date_time_str,
        topic=meeting_topic
    )
    
    # Sanitize folder name for filesystem
    return sanitize_filename(folder_name)


def download_video(download_url: str, access_token: str, output_path: Path) -> None:
    """Download a video file."""
    logger.info(f"Downloading to {output_path}...")
    
    headers = {
        "Authorization": f"Bearer {access_token}"
    }
    
    response = requests.get(download_url, headers=headers, stream=True, timeout=300)
    response.raise_for_status()
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'wb') as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    
    file_size = output_path.stat().st_size
    logger.info(f"Downloaded {file_size / (1024*1024):.2f} MB")


def get_recording_duration_seconds(recording: dict, video_file: Optional[dict] = None) -> int:
    """
    Get recording duration in seconds.
    Tries recording duration first, then calculates from video file timestamps.
    """
    # Try recording duration (in minutes)
    recording_duration_minutes = recording.get('duration', 0)
    if recording_duration_minutes > 0:
        return recording_duration_minutes * 60
    
    # Fallback: calculate from video file timestamps
    if video_file:
        try:
            file_start = video_file.get('recording_start')
            file_end = video_file.get('recording_end')
            
            if file_start and file_end:
                start_dt = datetime.fromisoformat(file_start.replace('Z', '+00:00'))
                end_dt = datetime.fromisoformat(file_end.replace('Z', '+00:00'))
                return int((end_dt - start_dt).total_seconds())
        except (ValueError, AttributeError, TypeError):
            pass
    
    return 0

