"""Logic to identify Gallery View recordings from Zoom API responses."""
import logging

logger = logging.getLogger(__name__)


def is_gallery_view(recording_file):
    """
    Determine if a recording file is a Gallery View recording.
    
    Args:
        recording_file: A recording file object from Zoom API
    
    Returns:
        Boolean indicating if this is a Gallery View recording
    """
    recording_type = recording_file.get("recording_type", "").lower()
    
    # Check for gallery view types
    return recording_type in ["gallery_view", "shared_screen_with_gallery_view"]


def find_best_gallery_view_file(recording_files):
    """
    Find the best Gallery View file from a list of recording files.
    Prioritizes shared_screen_with_gallery_view over gallery_view.
    Falls back to active_speaker if no Gallery View is available.
    
    Args:
        recording_files: List of recording file objects from Zoom API
    
    Returns:
        Best video file (Gallery View preferred, speaker view as fallback), or None if not found
    """
    # First, try to find shared_screen_with_gallery_view (preferred)
    for file in recording_files:
        recording_type = file.get("recording_type", "").lower()
        if recording_type == "shared_screen_with_gallery_view":
            logger.debug(f"Found preferred Gallery View: shared_screen_with_gallery_view")
            return file
    
    # Fall back to gallery_view
    for file in recording_files:
        recording_type = file.get("recording_type", "").lower()
        if recording_type == "gallery_view":
            logger.debug(f"Found Gallery View: gallery_view")
            return file
    
    # Fall back to active_speaker if no Gallery View found
    for file in recording_files:
        recording_type = file.get("recording_type", "").lower()
        if recording_type == "active_speaker":
            logger.debug(f"Found fallback: active_speaker")
            return file
    
    # Also check for shared_screen_with_speaker_view as fallback
    for file in recording_files:
        recording_type = file.get("recording_type", "").lower()
        if recording_type == "shared_screen_with_speaker_view":
            logger.debug(f"Found fallback: shared_screen_with_speaker_view")
            return file
    
    # No suitable video file found
    logger.debug("No Gallery View or Speaker View file found")
    return None


def find_all_gallery_view_files(recording_files):
    """
    Find all Gallery View files from a list of recording files.
    
    Args:
        recording_files: List of recording file objects from Zoom API
    
    Returns:
        List of Gallery View recording file objects
    """
    gallery_files = []
    for file in recording_files:
        if is_gallery_view(file):
            gallery_files.append(file)
    
    return gallery_files

