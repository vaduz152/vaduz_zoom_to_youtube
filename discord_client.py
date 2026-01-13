"""Discord webhook client for posting notifications."""
import logging
from typing import Optional

import requests

import config

logger = logging.getLogger(__name__)


def send_notification(youtube_url: str) -> bool:
    """
    Send a Discord notification with YouTube link.
    
    Args:
        youtube_url: YouTube video URL to post
    
    Returns:
        True if successful, False otherwise
    """
    # Format Discord message - modify this line to change message format
    message = f"{youtube_url}"
    
    try:
        response = requests.post(
            config.DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Discord notification sent: {youtube_url}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord notification: {e}")
        return False


def send_error_notification(error_message: str, error_details: Optional[str] = None) -> bool:
    """
    Send a Discord notification for errors (e.g., token expiration).
    
    Args:
        error_message: Main error message to display
        error_details: Optional additional error details
    
    Returns:
        True if successful, False otherwise
    """
    # Format Discord message with error information
    message = f"⚠️ **Error**: {error_message}"
    if error_details:
        message += f"\n```\n{error_details}\n```"
    
    try:
        response = requests.post(
            config.DISCORD_WEBHOOK_URL,
            json={"content": message},
            timeout=10
        )
        response.raise_for_status()
        logger.info(f"Discord error notification sent: {error_message}")
        return True
    except Exception as e:
        logger.error(f"Failed to send Discord error notification: {e}")
        return False

