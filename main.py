"""Main orchestrator for Zoom to YouTube automation."""
import argparse
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import config
import discord_client
import youtube_client
import zoom_client
from video_manager import cleanup_old_videos
from video_tracker import VideoTracker

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


def _send_error_notification(zoom_uuid: str, meeting_topic: str, error_message: str) -> None:
    """Send Discord notification for repeated errors."""
    try:
        discord_client.send_error_notification(
            error_message=f"Recording failed after {config.ERROR_NOTIFICATION_THRESHOLD} attempts: {meeting_topic}",
            error_details=f"UUID: {zoom_uuid[:8]}...\nError: {error_message}"
        )
        logger.info(f"Sent Discord notification for repeated error: {zoom_uuid[:8]}...")
    except Exception as e:
        logger.warning(f"Failed to send Discord error notification: {e}")


def _send_success_notification(zoom_uuid: str, meeting_topic: str, operation: str) -> None:
    """Send Discord notification when an error is resolved."""
    try:
        discord_client.send_error_notification(
            error_message=f"✅ Error resolved: {meeting_topic}",
            error_details=f"UUID: {zoom_uuid[:8]}...\nOperation: {operation}\nThe previous error has been resolved successfully."
        )
        logger.info(f"Sent Discord notification for resolved error: {zoom_uuid[:8]}...")
    except Exception as e:
        logger.warning(f"Failed to send Discord success notification: {e}")


def process_recording(recording: dict, tracker: VideoTracker, dry_run: bool = False) -> None:
    """
    Process a single recording: download, upload, notify.
    
    Args:
        recording: Recording object from Zoom API
        tracker: VideoTracker instance
        dry_run: If True, skip actual operations
    """
    zoom_uuid = recording.get('uuid', '')
    meeting_topic = recording.get('topic', 'Untitled Meeting')
    start_time = recording.get('start_time', '')
    
    if not zoom_uuid:
        logger.warning("Recording missing UUID, skipping")
        return
    
    logger.info(f"Processing recording: {meeting_topic} ({zoom_uuid[:8]}...)")
    
    # Check if already fully processed
    if tracker.is_processed(zoom_uuid):
        logger.info(f"Already fully processed, skipping: {zoom_uuid[:8]}...")
        return
    
    # Get existing record if any
    existing_record = tracker.get_record(zoom_uuid)
    
    # Get recording files
    recording_files = recording.get('recording_files', [])
    if not recording_files:
        logger.warning(f"No recording files found for {meeting_topic}")
        should_notify = tracker.record_error(zoom_uuid, "No recording files found")
        if should_notify:
            _send_error_notification(zoom_uuid, meeting_topic, "No recording files found")
        return
    
    # Find best video file
    best_video = zoom_client.find_best_video(recording_files)
    if not best_video:
        logger.warning(f"No suitable video file found for {meeting_topic}")
        should_notify = tracker.record_error(zoom_uuid, "No suitable video file found")
        if should_notify:
            _send_error_notification(zoom_uuid, meeting_topic, "No suitable video file found")
        return
    
    # Check minimum length requirement
    duration_seconds = zoom_client.get_recording_duration_seconds(recording, best_video)
    if config.MIN_VIDEO_LENGTH_SECONDS > 0 and duration_seconds < config.MIN_VIDEO_LENGTH_SECONDS:
        logger.info(f"Video too short ({duration_seconds}s < {config.MIN_VIDEO_LENGTH_SECONDS}s), skipping")
        should_notify = tracker.record_error(zoom_uuid, f"Video too short: {duration_seconds}s")
        if should_notify:
            _send_error_notification(zoom_uuid, meeting_topic, f"Video too short: {duration_seconds}s")
        return
    
    # Generate folder name and file path
    folder_name = zoom_client.generate_folder_name(recording)
    video_type = best_video.get('recording_type', 'video')
    filename = f"{video_type}.mp4"
    file_path = config.DOWNLOAD_DIR / folder_name / filename
    
    # Step 1: Download (if not already downloaded)
    if not existing_record or not existing_record.get('zoom_downloaded_at'):
        if dry_run:
            logger.info(f"[DRY RUN] Would download to: {file_path}")
        else:
            try:
                download_url = best_video.get('download_url')
                if not download_url:
                    raise ValueError("No download URL in video file")
                
                access_token = zoom_client.get_access_token()
                zoom_client.download_video(download_url, access_token, file_path)
                had_failures = tracker.record_download(zoom_uuid, meeting_topic, start_time, file_path)
                logger.info(f"Downloaded: {file_path}")
                if had_failures:
                    _send_success_notification(zoom_uuid, meeting_topic, "Download")
            except Exception as e:
                logger.error(f"Download failed: {e}")
                should_notify = tracker.record_error(zoom_uuid, f"Download failed: {e}")
                if should_notify:
                    _send_error_notification(zoom_uuid, meeting_topic, f"Download failed: {e}")
                return
    else:
        logger.info(f"Already downloaded: {file_path}")
        # Verify file still exists
        if not file_path.exists():
            logger.warning(f"File missing, will retry download: {file_path}")
            try:
                download_url = best_video.get('download_url')
                if download_url:
                    access_token = zoom_client.get_access_token()
                    zoom_client.download_video(download_url, access_token, file_path)
                    had_failures = tracker.record_download(zoom_uuid, meeting_topic, start_time, file_path)
                    if had_failures:
                        _send_success_notification(zoom_uuid, meeting_topic, "Download (retry)")
            except Exception as e:
                logger.error(f"Retry download failed: {e}")
                should_notify = tracker.record_error(zoom_uuid, f"Retry download failed: {e}")
                if should_notify:
                    _send_error_notification(zoom_uuid, meeting_topic, f"Retry download failed: {e}")
                return
    
    # Step 2: Upload to YouTube (if not already uploaded)
    if not existing_record or not existing_record.get('youtube_uploaded_at'):
        if dry_run:
            logger.info(f"[DRY RUN] Would upload to YouTube: {file_path}")
        else:
            try:
                if not file_path.exists():
                    raise FileNotFoundError(f"Video file not found: {file_path}")
                
                # Use folder name as title (includes date/time/topic format)
                title = folder_name
                youtube_url = youtube_client.upload_video(
                    video_path=file_path,
                    title=title,
                    description=config.YOUTUBE_DEFAULT_DESCRIPTION,
                    tags=[t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()],
                    category_id=config.YOUTUBE_CATEGORY_ID
                )
                had_failures = tracker.record_upload(zoom_uuid, youtube_url)
                logger.info(f"Uploaded to YouTube: {youtube_url}")
                if had_failures:
                    _send_success_notification(zoom_uuid, meeting_topic, "Upload")
            except Exception as e:
                logger.error(f"Upload failed: {e}")
                should_notify = tracker.record_error(zoom_uuid, f"Upload failed: {e}")
                if should_notify:
                    _send_error_notification(zoom_uuid, meeting_topic, f"Upload failed: {e}")
                return
    else:
        logger.info(f"Already uploaded: {existing_record.get('youtube_url')}")
    
    # Step 3: Send Discord notification (if not already notified)
    existing_record = tracker.get_record(zoom_uuid)  # Refresh record
    youtube_url = existing_record.get('youtube_url', '') if existing_record else ''
    
    if not existing_record or not existing_record.get('discord_notified_at'):
        if not youtube_url:
            logger.warning("Cannot send Discord notification: no YouTube URL")
            return
        
        if dry_run:
            logger.info(f"[DRY RUN] Would send Discord notification: {youtube_url}")
        else:
            try:
                success = discord_client.send_notification(youtube_url)
                if success:
                    had_failures = tracker.record_notification(zoom_uuid)
                    logger.info(f"Discord notification sent: {youtube_url}")
                    if had_failures:
                        _send_success_notification(zoom_uuid, meeting_topic, "Discord notification")
                else:
                    should_notify = tracker.record_error(zoom_uuid, "Discord notification failed")
                    if should_notify:
                        _send_error_notification(zoom_uuid, meeting_topic, "Discord notification failed")
            except Exception as e:
                logger.error(f"Discord notification failed: {e}")
                should_notify = tracker.record_error(zoom_uuid, f"Discord notification failed: {e}")
                if should_notify:
                    _send_error_notification(zoom_uuid, meeting_topic, f"Discord notification failed: {e}")
    else:
        logger.info(f"Already notified Discord: {youtube_url}")


def retry_failed_recordings(tracker: VideoTracker, dry_run: bool = False) -> None:
    """Retry failed or incomplete recordings."""
    retry_records = tracker.get_records_for_retry()
    
    if not retry_records:
        logger.info("No recordings need retry")
        return
    
    logger.info(f"Found {len(retry_records)} recording(s) to retry")
    
    # We need to fetch recordings from Zoom to get full details
    # For now, we'll skip retries that require re-downloading
    # and only retry uploads/notifications
    access_token = None
    if not dry_run:
        try:
            access_token = zoom_client.get_access_token()
        except Exception as e:
            logger.error(f"Failed to get Zoom access token for retries: {e}")
            return
    
    for record in retry_records:
        uuid = record['zoom_uuid']
        file_path_str = record.get('file_path', '')
        
        # Retry upload if downloaded but not uploaded
        if record.get('zoom_downloaded_at') and not record.get('youtube_uploaded_at'):
            if file_path_str:
                file_path = Path(file_path_str)
                if file_path.exists():
                    logger.info(f"Retrying upload for: {uuid[:8]}...")
                    if dry_run:
                        logger.info(f"[DRY RUN] Would retry upload: {file_path}")
                    else:
                        try:
                            # Extract folder name from file path for title
                            # Path format: downloaded_videos/{folder_name}/{filename}
                            folder_name = file_path.parent.name
                            title = folder_name if folder_name else record.get('meeting_topic', 'Untitled Meeting')
                            youtube_url = youtube_client.upload_video(
                                video_path=file_path,
                                title=title,
                                description=config.YOUTUBE_DEFAULT_DESCRIPTION,
                                tags=[t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()],
                                category_id=config.YOUTUBE_CATEGORY_ID
                            )
                            meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
                            had_failures = tracker.record_upload(uuid, youtube_url)
                            logger.info(f"Retry upload successful: {youtube_url}")
                            if had_failures:
                                _send_success_notification(uuid, meeting_topic, "Upload (retry)")
                        except Exception as e:
                            logger.error(f"Retry upload failed: {e}")
                            meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
                            should_notify = tracker.record_error(uuid, f"Retry upload failed: {e}")
                            if should_notify:
                                _send_error_notification(uuid, meeting_topic, f"Retry upload failed: {e}")
        
        # Retry Discord notification if uploaded but not notified
        if record.get('youtube_uploaded_at') and not record.get('discord_notified_at'):
            youtube_url = record.get('youtube_url', '')
            if youtube_url:
                logger.info(f"Retrying Discord notification for: {uuid[:8]}...")
                if dry_run:
                    logger.info(f"[DRY RUN] Would retry Discord notification: {youtube_url}")
                else:
                    try:
                        success = discord_client.send_notification(youtube_url)
                        if success:
                            meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
                            had_failures = tracker.record_notification(uuid)
                            logger.info(f"Retry notification successful")
                            if had_failures:
                                _send_success_notification(uuid, meeting_topic, "Discord notification (retry)")
                        else:
                            meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
                            should_notify = tracker.record_error(uuid, "Retry Discord notification failed")
                            if should_notify:
                                _send_error_notification(uuid, meeting_topic, "Retry Discord notification failed")
                    except Exception as e:
                        logger.error(f"Retry notification failed: {e}")
                        meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
                        should_notify = tracker.record_error(uuid, f"Retry notification failed: {e}")
                        if should_notify:
                            _send_error_notification(uuid, meeting_topic, f"Retry notification failed: {e}")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Download Zoom recordings and upload to YouTube"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test mode: skip downloads/uploads, just log what would be done"
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Increase logging verbosity"
    )
    args = parser.parse_args()
    
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
    
    logger.info("="*60)
    logger.info("Zoom to YouTube Automation")
    logger.info("="*60)
    if args.dry_run:
        logger.info("DRY RUN MODE - No actual operations will be performed")
    logger.info(f"Configuration:")
    logger.info(f"  Last meetings to process: {config.LAST_MEETINGS_TO_PROCESS}")
    logger.info(f"  Minimum video length: {config.MIN_VIDEO_LENGTH_SECONDS}s")
    logger.info(f"  Video retention: {config.VIDEO_RETENTION_DAYS} days")
    logger.info(f"  Download directory: {config.DOWNLOAD_DIR}")
    logger.info("="*60)
    
    tracker = VideoTracker()
    
    # Step 1: Retry failed recordings
    logger.info("\nStep 1: Retrying failed recordings...")
    retry_failed_recordings(tracker, dry_run=args.dry_run)
    
    # Step 2: Fetch and process new recordings
    logger.info("\nStep 2: Fetching new recordings from Zoom...")
    try:
        access_token = zoom_client.get_access_token()
        
        # Calculate date range (last year to today)
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")
        
        recordings = zoom_client.list_recordings(
            access_token=access_token,
            limit=config.LAST_MEETINGS_TO_PROCESS,
            from_date=from_date,
            to_date=to_date
        )
        
        logger.info(f"Found {len(recordings)} recording(s) to process")
        
        # Process each recording
        for idx, recording in enumerate(recordings, 1):
            logger.info(f"\n[{idx}/{len(recordings)}] Processing recording...")
            try:
                process_recording(recording, tracker, dry_run=args.dry_run)
            except Exception as e:
                logger.error(f"Error processing recording: {e}", exc_info=True)
                zoom_uuid = recording.get('uuid', '')
                meeting_topic = recording.get('topic', 'Unknown Meeting')
                if zoom_uuid:
                    should_notify = tracker.record_error(zoom_uuid, f"Processing error: {e}")
                    if should_notify:
                        _send_error_notification(zoom_uuid, meeting_topic, f"Processing error: {e}")
        
    except Exception as e:
        logger.error(f"Failed to fetch recordings: {e}", exc_info=True)
        return
    
    # Step 3: Cleanup old videos
    logger.info("\nStep 3: Cleaning up old videos...")
    if args.dry_run:
        logger.info("[DRY RUN] Would clean up videos older than retention period")
    else:
        cleanup_old_videos()
    
    logger.info("\n" + "="*60)
    logger.info("Processing complete")
    logger.info("="*60)


if __name__ == "__main__":
    main()

