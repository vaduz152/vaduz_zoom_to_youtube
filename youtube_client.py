"""YouTube API client for uploading videos."""
import logging
from pathlib import Path
from typing import List, Optional, Tuple
from urllib.parse import urlparse, parse_qs
from http.server import HTTPServer, BaseHTTPRequestHandler
import socket
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
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
    flow = InstalledAppFlow.from_client_config(
        {
            "installed": {
                "client_id": config.YOUTUBE_CLIENT_ID,
                "client_secret": config.YOUTUBE_CLIENT_SECRET,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": ["http://localhost:8081/"]
            }
        },
        scopes=SCOPES,
    )
    
    # Build authorization URL manually
    port = 8081
    redirect_uri = f"http://localhost:{port}/"
    
    # Use login_hint if provided to pre-select account
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        redirect_uri=redirect_uri,
        login_hint=config.YOUTUBE_LOGIN_HINT if config.YOUTUBE_LOGIN_HINT else None,
        prompt='consent' if config.YOUTUBE_LOGIN_HINT else 'select_account consent'
    )
    
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
    logger.error(f"   http://localhost:{port}/?code=ABC123XYZ...")
    logger.error("\n5. Copy everything after 'code=' until the next '&' (if any).")
    logger.error("   Example: If URL is '...?code=ABC123&state=...', copy 'ABC123'")
    logger.error("\n" + "="*60)
    
    # Try to start server and capture code automatically
    logger.info("\nAttempting to capture authorization code automatically...")
    logger.info("(If this doesn't work, you can manually paste the code when prompted)")
    
    authorization_code, captured_state = start_google_oauth_server(port=port, timeout=300)
    
    # Use captured state if available, otherwise use the one we generated
    final_state = captured_state if captured_state else state
    
    # If automatic capture failed, fall back to manual input
    if not authorization_code:
        logger.warning("\nAutomatic capture timed out or failed.")
        logger.info("Please manually extract the code from your browser's address bar.")
        logger.info(f"The URL will look like: http://localhost:{port}/?code=YOUR_CODE_HERE")
        logger.info("You can paste either:")
        logger.info("  - Just the code: ABC123XYZ...")
        logger.info(f"  - Or the full URL: http://localhost:{port}/?code=ABC123XYZ...")
        
        user_input = input("\nPaste the authorization code or full URL here: ").strip()
        
        # Extract code and state from URL if user pasted full URL
        if user_input.startswith('http'):
            parsed = urlparse(user_input)
            query_params = parse_qs(parsed.query)
            if 'code' in query_params:
                authorization_code = query_params['code'][0]
                # Use state from URL if available, otherwise use generated state
                if 'state' in query_params:
                    final_state = query_params['state'][0]
            else:
                authorization_code = user_input
        else:
            authorization_code = user_input
    
    if not authorization_code:
        raise Exception("No authorization code provided")
    
    # Exchange authorization code for credentials
    # Build the authorization response URL that Google would have redirected to
    authorization_response = f"{redirect_uri}?code={authorization_code}"
    if final_state:
        authorization_response += f"&state={final_state}"
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
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

