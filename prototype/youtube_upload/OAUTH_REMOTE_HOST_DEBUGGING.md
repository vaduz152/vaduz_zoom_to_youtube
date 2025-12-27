# OAuth Remote Host Debugging Session - Findings

**Date:** December 27, 2025  
**Session Goal:** Fix OAuth authorization flows (Zoom and YouTube) when running scripts on a remote host

## Problem Statement

When running the script on a remote host via SSH:
1. **Zoom OAuth**: Authorization URL opens in local browser, but redirect fails because `localhost:8080` points to local machine, not remote host
2. **YouTube OAuth**: Similar issue - redirect to `localhost:8081` fails, page gets stuck after clicking "Continue"

## Key Discoveries

### 1. SSH Port Forwarding Solution

**The Solution:** Use SSH local port forwarding to tunnel localhost connections from your local machine to the remote host.

**Command:**
```bash
ssh -L 8081:localhost:8081 user@remote-host
```

**What it does:**
- Creates a tunnel from your local port 8081 to remote host's port 8081
- When browser redirects to `localhost:8081`, SSH forwards it to the remote server
- OAuth server on remote host receives the request and captures the code automatically

**Important:** Keep the SSH session open - closing it closes the tunnel.

### 2. Zoom OAuth Implementation

**Current Status:** ✅ Working with port forwarding

**Implementation Details:**
- Redirect URI: `http://localhost:8080/redirect`
- Server listens on port 8080
- Captures authorization code from redirect URL
- Falls back to manual code entry if port forwarding not available

**Key Code Pattern:**
```python
# Start HTTP server to capture redirect
authorization_code = start_oauth_server(port=8080, timeout=300)

# If automatic capture fails, fall back to manual input
if not authorization_code:
    user_input = input("Paste authorization code or URL: ")
    # Extract code from URL if full URL pasted
```

### 3. YouTube OAuth Implementation Challenges

**Issues Encountered:**

#### Issue 1: Missing redirect_uri in Authorization URL
- **Problem:** `InstalledAppFlow.authorization_url()` wasn't including redirect_uri
- **Solution:** Manually construct authorization URL with all parameters including redirect_uri
- **Code:**
```python
auth_params = {
    'response_type': 'code',
    'client_id': config.YOUTUBE_CLIENT_ID,
    'redirect_uri': redirect_uri,  # Explicitly include
    'scope': ' '.join(SCOPES),
    'state': state,
    'access_type': 'offline',
    'include_granted_scopes': 'true',
}
authorization_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
```

#### Issue 2: HTTPS Requirement Error
- **Error:** `(insecure_transport) OAuth 2 MUST utilize https`
- **Solution:** Set environment variable to allow HTTP for localhost
- **Code:**
```python
os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'
```

#### Issue 3: Missing redirect_uri in Token Exchange
- **Error:** `(invalid_request) Missing parameter: redirect_uri`
- **Problem:** `flow.fetch_token()` wasn't recognizing redirect_uri when manually building authorization URL
- **Attempted Solutions:**
  1. Pass `redirect_uri` parameter to `fetch_token()` - didn't work
  2. Set `flow.redirect_uri` before calling `fetch_token()` - didn't work
  3. Manual token exchange using `requests` library - **This should work**

**Manual Token Exchange Pattern:**
```python
token_data = {
    'code': authorization_code,
    'client_id': config.YOUTUBE_CLIENT_ID,
    'client_secret': config.YOUTUBE_CLIENT_SECRET,
    'redirect_uri': redirect_uri,
    'grant_type': 'authorization_code'
}

response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
token_response = response.json()

creds = Credentials(
    token=token_response.get('access_token'),
    refresh_token=token_response.get('refresh_token'),
    token_uri='https://oauth2.googleapis.com/token',
    client_id=config.YOUTUBE_CLIENT_ID,
    client_secret=config.YOUTUBE_CLIENT_SECRET,
    scopes=SCOPES
)
```

### 4. Browser Behavior Observations

**Key Findings:**
- Even when redirect fails (connection refused), the authorization code is **always** in the browser's address bar
- Browser may show error page but URL contains: `http://127.0.0.1:8081/?code=...&state=...`
- User can manually copy URL and paste it - script extracts code automatically
- With port forwarding, redirect works seamlessly and code is captured automatically

**Network Tab Observations:**
- Document navigation to redirect URI shows as `(canceled)` when no server listening
- But XHR requests to same URI can succeed with `200` status
- This suggests browser security policies may cancel document navigations but allow other requests

### 5. Redirect URI Configuration

**Zoom:**
- Redirect URI: `http://localhost:8080/redirect`
- Must match exactly what's configured in Zoom Marketplace app settings

**YouTube:**
- Redirect URI: `http://127.0.0.1:8081/` or `http://localhost:8081/`
- For Desktop apps, Google accepts both localhost and 127.0.0.1
- Must be configured in Google Cloud Console OAuth client settings

**Important:** Use `127.0.0.1` instead of `localhost` for better compatibility across systems.

## Implementation Recommendations

### For Zoom OAuth:
1. ✅ Current implementation works well
2. ✅ Server captures code automatically with port forwarding
3. ✅ Falls back gracefully to manual entry

### For YouTube OAuth:
1. **Use manual token exchange** instead of `flow.fetch_token()`
2. **Set `OAUTHLIB_INSECURE_TRANSPORT=1`** environment variable
3. **Manually construct authorization URL** to ensure redirect_uri is included
4. **Use `127.0.0.1` instead of `localhost`** for redirect URI

## Code Patterns That Work

### HTTP Server for OAuth Redirect
```python
class OAuthRedirectHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urlparse(self.path)
        query_params = parse_qs(parsed_path.query)
        
        if 'code' in query_params:
            code = query_params['code'][0]
            self.server.authorization_code = code
            # Send success response
            self.send_response(200)
            # ... HTML response
```

### Manual Token Exchange (Google OAuth)
```python
# Exchange code for tokens manually
token_data = {
    'code': authorization_code,
    'client_id': CLIENT_ID,
    'client_secret': CLIENT_SECRET,
    'redirect_uri': redirect_uri,
    'grant_type': 'authorization_code'
}
response = requests.post('https://oauth2.googleapis.com/token', data=token_data)
```

## User Instructions

### Setup Port Forwarding:
```bash
# In a separate terminal, before running the script:
ssh -L 8080:localhost:8080 -L 8081:localhost:8081 user@remote-host
```

### Without Port Forwarding:
1. Visit authorization URL in browser
2. Click "Allow" / "Continue"
3. Even if redirect fails, check browser address bar
4. Copy the full URL (contains `?code=...`)
5. Paste into script when prompted

## Known Issues

1. **YouTube OAuth with manual token exchange:** May need to verify token response format matches Google's expected structure
2. **Browser security policies:** Some browsers may block localhost redirects - using 127.0.0.1 helps
3. **State parameter verification:** Should verify state matches for security

## Next Steps

1. Test manual token exchange implementation for YouTube
2. Verify credentials are saved correctly
3. Test token refresh functionality
4. Consider adding better error handling and logging

## Files Modified During Session

- `zoom_client.py` - Added HTTP server for OAuth redirect capture
- `youtube_client.py` - Multiple iterations trying to fix redirect_uri issues

## Rollback Point

**Commit:** `023b7f4c534368dacf27a1d8e56256bdfdc3f6cc`  
**Date:** Sat Dec 27 17:23:53 2025  
**Message:** "Updated YouTube authirosation for remote host setup"

This commit contains the initial YouTube OAuth remote host setup changes. All debugging and fixes attempted in this session were made after this commit.

