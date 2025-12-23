"""File management and cleanup for downloaded videos."""
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

import config
from video_tracker import VideoTracker

logger = logging.getLogger(__name__)


def cleanup_old_videos(retention_days: int = None) -> int:
    """
    Delete videos older than retention period.
    
    Args:
        retention_days: Number of days to retain videos (defaults to config value)
    
    Returns:
        Number of videos deleted
    """
    if retention_days is None:
        retention_days = config.VIDEO_RETENTION_DAYS
    
    logger.info(f"Cleaning up videos older than {retention_days} days...")
    
    tracker = VideoTracker()
    records = tracker.get_all_records()
    
    cutoff_date = datetime.now() - timedelta(days=retention_days)
    deleted_count = 0
    
    for record in records:
        downloaded_at_str = record.get('zoom_downloaded_at', '')
        if not downloaded_at_str:
            continue
        
        try:
            downloaded_at = datetime.fromisoformat(downloaded_at_str)
            if downloaded_at < cutoff_date:
                # Check if file exists
                file_path_str = record.get('file_path', '')
                if file_path_str:
                    file_path = Path(file_path_str)
                    if file_path.exists():
                        try:
                            file_path.unlink()
                            logger.info(f"Deleted old video: {file_path}")
                            deleted_count += 1
                            
                            # Try to remove parent directory if empty
                            parent_dir = file_path.parent
                            try:
                                if parent_dir.exists() and not any(parent_dir.iterdir()):
                                    parent_dir.rmdir()
                                    logger.debug(f"Removed empty directory: {parent_dir}")
                            except OSError:
                                pass  # Directory not empty or other error
                        except Exception as e:
                            logger.error(f"Failed to delete {file_path}: {e}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid date format in record {record.get('zoom_uuid')}: {e}")
            continue
    
    logger.info(f"Cleanup complete: deleted {deleted_count} video(s)")
    return deleted_count

