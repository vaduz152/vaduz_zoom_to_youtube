"""YouTube API client for uploading videos."""
import logging
import os
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, parse_qs, urlencode
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
import time
import secrets

import requests
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

import config

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


class GoogleOAuthRedirectHandler(BaseHTTPRequestHandler):
    """HTTP request handler to capture Google OAuth redirect."""
    
    def do_GET(self):
        """Handle GET request from OAuth redirect."""
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        
        if 'code' in query_params:
            code = query_params['code'][0]
            state = query_params.get('state', [None])[0]
            self.server.authorization_code = code
            self.server.authorization_state = state
            
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
            self.server.authorization_state = None
    
    def log_message(self, format, *args):
        """Suppress default logging."""
        pass


def start_google_oauth_server(port: int = 8081, timeout: int = 300) -> Tuple[Optional[str], Optional[str]]:
    """
    Start a local HTTP server to capture Google OAuth redirect.
    Returns a tuple of (authorization_code, state) if captured, (None, None) otherwise.
    """
    server_address = ('', port)
    httpd = HTTPServer(server_address, GoogleOAuthRedirectHandler)
    httpd.authorization_code = None
    httpd.authorization_state = None
    httpd.socket.settimeout(1.0)  # Set socket timeout for non-blocking behavior
    
    logger.info(f"Starting Google OAuth redirect server on port {port}...")
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
    state = httpd.authorization_state
    httpd.server_close()
    
    if code:
        logger.info("Authorization code captured successfully!")
    else:
        logger.warning("Server timed out waiting for authorization code.")
    
    return (code, state)


def get_credentials() -> Credentials:
    """Get or refresh YouTube OAuth credentials."""
    # Set environment variable to allow HTTP for localhost (required for OAuth redirect)
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
    
    token_file = config.YOUTUBE_TOKEN_FILE
    
    creds: Optional[Credentials] = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file.resolve()), scopes=SCOPES)
    
    if creds and creds.valid:
        return creds
    
    if creds and creds.expired and creds.refresh_token:
        logger.info("Refreshing YouTube credentials...")
        creds.refresh(Request())
        token_file.write_text(creds.to_json())
        return creds
    
    # Need to authorize
    logger.info("YouTube authorization required. Starting OAuth flow...")
    
    # Use 127.0.0.1 instead of localhost for better compatibility
    port = 8081
    redirect_uri = f"http://127.0.0.1:{port}/"
    
    # Generate state parameter for security
    state = secrets.token_urlsafe(32)
    
    # Manually construct authorization URL with all required parameters
    auth_params = {
        'response_type': 'code',
        'client_id': config.YOUTUBE_CLIENT_ID,
        'redirect_uri': redirect_uri,
        'scope': ' '.join(SCOPES),
        'state': state,
        'access_type': 'offline',
        'include_granted_scopes': 'true',
    }
    
    # Add login_hint if provided
    if config.YOUTUBE_LOGIN_HINT:
        auth_params['login_hint'] = config.YOUTUBE_LOGIN_HINT
        auth_params['prompt'] = 'consent'
    else:
        auth_params['prompt'] = 'select_account consent'
    
    authorization_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
    
    logger.error("\n" + "="*60)
    logger.error("YouTube authorization required!")
    logger.error("="*60)
    logger.error("\nOPTION 1: Automatic (Recommended if using SSH port forwarding)")
    logger.error("="*60)
    logger.error("1. If connecting via SSH, set up port forwarding FIRST:")
    logger.error(f"   ssh -L {port}:localhost:{port} user@remote-host")
    logger.error("   (Run this in a separate terminal before running the script)")
    logger.error("\n2. Visit this URL in your browser:")
    logger.error(f"\n   {authorization_url}\n")
    logger.error("3. Click 'Continue' on the Google authorization page.")
    logger.error("4. The code will be captured automatically - you'll see a success page.")
    logger.error("\n" + "="*60)
    logger.error("OPTION 2: Manual (If port forwarding is not available)")
    logger.error("="*60)
    logger.error("1. Visit this URL in your browser:")
    logger.error(f"\n   {authorization_url}\n")
    logger.error("2. Click 'Continue' on the Google authorization page.")
    logger.error("3. IMPORTANT: After clicking 'Continue', Google will redirect you.")
    logger.error("   Even if you see an error page (like 'Connection refused'),")
    logger.error("   LOOK AT YOUR BROWSER'S ADDRESS BAR - it will contain the code!")
    logger.error("\n4. The URL will look like:")
    logger.error(f"   http://127.0.0.1:{port}/?code=ABC123XYZ...&state=...")
    logger.error("\n5. Copy everything after 'code=' until the next '&' (if any).")
    logger.error("   Example: If URL is '...?code=ABC123&state=...', copy 'ABC123'")
    logger.error("   Or paste the full URL - the script will extract the code automatically.")
    logger.error("\n" + "="*60)
    
    # Try to start server and capture code automatically
    logger.info("\nAttempting to capture authorization code automatically...")
    logger.info("(If this doesn't work, you can manually paste the code when prompted)")
    
    authorization_code, captured_state = start_google_oauth_server(port=port, timeout=300)
    
    # Verify state parameter matches for security
    if captured_state and captured_state != state:
        logger.warning(f"State parameter mismatch! Expected: {state}, Got: {captured_state}")
        logger.warning("This could indicate a security issue. Proceeding with caution...")
    
    # Use captured state if available, otherwise use the one we generated
    final_state = captured_state if captured_state else state
    
    # If automatic capture failed, fall back to manual input
    if not authorization_code:
        logger.warning("\nAutomatic capture timed out or failed.")
        logger.info("Please manually extract the code from your browser's address bar.")
        logger.info(f"The URL will look like: http://127.0.0.1:{port}/?code=YOUR_CODE_HERE&state=...")
        logger.info("You can paste either:")
        logger.info("  - Just the code: ABC123XYZ...")
        logger.info(f"  - Or the full URL: http://127.0.0.1:{port}/?code=ABC123XYZ...&state=...")
        
        user_input = input("\nPaste the authorization code or full URL here: ").strip()
        
        # Extract code and state from URL if user pasted full URL
        if user_input.startswith('http'):
            parsed = urlparse(user_input)
            query_params = parse_qs(parsed.query)
            if 'code' in query_params:
                authorization_code = query_params['code'][0]
                # Verify state parameter if present
                if 'state' in query_params:
                    url_state = query_params['state'][0]
                    if url_state != state:
                        logger.warning(f"State parameter mismatch! Expected: {state}, Got: {url_state}")
                        logger.warning("This could indicate a security issue. Proceeding with caution...")
                    final_state = url_state
            else:
                authorization_code = user_input
        else:
            authorization_code = user_input
    
    if not authorization_code:
        raise Exception("No authorization code provided")
    
    # Manual token exchange using requests (as recommended in debugging doc)
    logger.info("Exchanging authorization code for tokens...")
    token_data = {
        'code': authorization_code,
        'client_id': config.YOUTUBE_CLIENT_ID,
        'client_secret': config.YOUTUBE_CLIENT_SECRET,
        'redirect_uri': redirect_uri,
        'grant_type': 'authorization_code'
    }
    
    response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
    response.raise_for_status()
    token_response = response.json()
    
    # Create Credentials object from token response
    creds = Credentials(
        token=token_response.get('access_token'),
        refresh_token=token_response.get('refresh_token'),
        token_uri='https://oauth2.googleapis.com/token',
        client_id=config.YOUTUBE_CLIENT_ID,
        client_secret=config.YOUTUBE_CLIENT_SECRET,
        scopes=SCOPES
    )
    
    token_file.write_text(creds.to_json())
    logger.info("YouTube credentials saved")
    return creds


def upload_video(
    video_path: Path,
    title: str,
    description: Optional[str] = None,
    tags: Optional[List[str]] = None,
    category_id: Optional[str] = None,
    privacy_status: str = "unlisted",
) -> str:
    """
    Upload a video to YouTube.
    
    Args:
        video_path: Path to video file
        title: Video title
        description: Video description (defaults to config value)
        tags: List of tags (defaults to config value)
        category_id: YouTube category ID (defaults to config value)
        privacy_status: Privacy status (defaults to "unlisted")
    
    Returns:
        YouTube video URL
    """
    if description is None:
        description = config.YOUTUBE_DEFAULT_DESCRIPTION
    if tags is None:
        tags = [t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()]
    if category_id is None:
        category_id = config.YOUTUBE_CATEGORY_ID
    
    logger.info(f"Uploading video: {video_path.name}")
    logger.info(f"Title: {title}")
    
    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds)
    
    media = MediaFileUpload(str(video_path), chunksize=4 * 1024 * 1024, resumable=True)
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "categoryId": category_id,
        },
        "status": {"privacyStatus": privacy_status},
    }
    if tags:
        body["snippet"]["tags"] = tags
    
    request = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Upload progress: %.2f%%", status.progress() * 100)
    
    video_id = response["id"]
    youtube_url = f"https://youtu.be/{video_id}"
    logger.info(f"Upload complete: {youtube_url}")
    return youtube_url

