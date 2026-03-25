"""Main orchestrator for Zoom to YouTube automation."""
import argparse
import fcntl
import logging
import sys
from datetime import datetime, timedelta
from pathlib import Path

import config
import discord_client
import transcription_client
import transcript_storage
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

# Suppress noisy HTTP request logging from httpx and google libs
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient.discovery_cache").setLevel(logging.WARNING)
logging.getLogger("google_genai.models").setLevel(logging.WARNING)


def _format_meeting_datetime(start_time: str) -> str:
    """Format ISO start_time as 'YYYY-MM-DD HH:MM'."""
    if not start_time:
        return ''
    try:
        dt = datetime.fromisoformat(start_time.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return ''


def _handle_error(
    tracker: VideoTracker,
    zoom_uuid: str, meeting_topic: str, start_time: str,
    error_msg: str,
) -> None:
    """Record error in tracker and send Discord notification if threshold reached."""
    should_notify = tracker.record_error(
        zoom_uuid, error_msg,
        meeting_topic=meeting_topic, start_time=start_time
    )
    if should_notify:
        try:
            discord_client.send_error_notification(
                error_message=f"Recording failed after {config.ERROR_NOTIFICATION_THRESHOLD} attempts: {meeting_topic}",
                error_details=f"UUID: {zoom_uuid[:8]}...\nError: {error_msg}"
            )
        except Exception as e:
            logger.warning(f"Failed to send Discord error notification: {e}")


def _notify_if_resolved(
    had_failures: bool,
    zoom_uuid: str, meeting_topic: str, operation: str,
) -> None:
    """If previous failures were resolved, send a success notification."""
    if not had_failures:
        return
    try:
        discord_client.send_error_notification(
            error_message=f"✅ Error resolved: {meeting_topic}",
            error_details=f"UUID: {zoom_uuid[:8]}...\nOperation: {operation}\nThe previous error has been resolved successfully."
        )
    except Exception as e:
        logger.warning(f"Failed to send Discord success notification: {e}")


def process_recording(recording: dict, tracker: VideoTracker, dry_run: bool = False) -> None:
    """Process a single recording: wait for video+VTT, download, upload, transcribe, notify."""
    zoom_uuid = recording.get('uuid', '')
    meeting_topic = recording.get('topic') or 'Untitled Meeting'
    start_time = recording.get('start_time') or ''

    if not zoom_uuid:
        logger.warning("Recording missing UUID, skipping")
        return

    logger.info(f"Processing recording: {meeting_topic} ({zoom_uuid[:8]}...)")

    # Check if already fully processed
    if tracker.is_processed(zoom_uuid):
        tracker.update_meeting_metadata(zoom_uuid, meeting_topic, start_time)
        logger.info(f"Already fully processed, skipping: {zoom_uuid[:8]}...")
        return

    existing_record = tracker.get_record(zoom_uuid)

    # Validate recording files
    recording_files = recording.get('recording_files', [])
    if not recording_files:
        logger.warning(f"No recording files found for {meeting_topic}")
        _handle_error(tracker, zoom_uuid, meeting_topic, start_time, "No recording files found")
        return

    available_types = [f.get('recording_type', 'unknown') for f in recording_files]
    logger.debug(f"Available recording types for {zoom_uuid[:8]}: {available_types}")

    # --- Check video readiness ---
    best_video = zoom_client.find_best_video(recording_files)
    if not best_video:
        processing_files = [
            f for f in recording_files
            if f.get('status', '').lower() not in ('', 'completed')
        ]
        if processing_files:
            statuses = [f.get('status', 'unknown') for f in processing_files]
            error_msg = f"Video files still processing (status: {', '.join(statuses)})"
        else:
            error_msg = "No suitable video file found"
        logger.warning(f"{error_msg} for {meeting_topic}")
        logger.warning(f"  Recording types present: {available_types}")
        _handle_error(tracker, zoom_uuid, meeting_topic, start_time, error_msg)
        return

    # Check minimum length
    duration_seconds = zoom_client.get_recording_duration_seconds(recording, best_video)
    if config.MIN_VIDEO_LENGTH_SECONDS > 0 and duration_seconds < config.MIN_VIDEO_LENGTH_SECONDS:
        logger.info(f"Video too short ({duration_seconds}s < {config.MIN_VIDEO_LENGTH_SECONDS}s), skipping")
        tracker.record_skipped(
            zoom_uuid, f"Video too short: {duration_seconds}s",
            meeting_topic=meeting_topic, start_time=start_time
        )
        return

    # Record video readiness timestamp
    tracker.record_video_ready(zoom_uuid, meeting_topic, start_time)

    # --- Check VTT readiness ---
    transcript_file = zoom_client.find_transcript_file(recording_files)
    if transcript_file:
        tracker.record_vtt_ready(zoom_uuid)
    else:
        logger.info(f"VTT not yet available for {meeting_topic}, waiting for next run")
        return

    # --- From here: both video and VTT are ready ---

    folder_name = zoom_client.generate_folder_name(recording)
    video_type = best_video.get('recording_type', 'video')
    file_path = config.DOWNLOAD_DIR / folder_name / f"{video_type}.mp4"
    vtt_path = config.DOWNLOAD_DIR / folder_name / "zoom_transcript.vtt"

    # Step 1: Download video + VTT
    if not existing_record or not existing_record.get('zoom_downloaded_at'):
        if dry_run:
            logger.info(f"[DRY RUN] Would download to: {file_path}")
        else:
            try:
                download_url = best_video.get('download_url')
                if not download_url:
                    raise ValueError("No download URL in video file")
                access_token = zoom_client.get_access_token()

                # Download video
                zoom_client.download_file(download_url, access_token, file_path)
                logger.info(f"Downloaded video: {file_path}")

                # Download VTT
                vtt_download_url = transcript_file.get('download_url')
                if vtt_download_url:
                    zoom_client.download_file(vtt_download_url, access_token, vtt_path)
                    logger.info(f"Downloaded VTT: {vtt_path}")

                had_failures = tracker.record_download(zoom_uuid, meeting_topic, start_time, file_path)
                _notify_if_resolved(had_failures, zoom_uuid, meeting_topic, "Download")
            except Exception as e:
                logger.error(f"Download failed: {e}")
                _handle_error(tracker, zoom_uuid, meeting_topic, start_time, f"Download failed: {e}")
                return
    else:
        logger.info(f"Already downloaded: {file_path}")
        if not file_path.exists():
            logger.warning(f"File missing, will retry download: {file_path}")
            try:
                download_url = best_video.get('download_url')
                if download_url:
                    access_token = zoom_client.get_access_token()
                    zoom_client.download_file(download_url, access_token, file_path)
                    # Also re-download VTT if missing
                    if not vtt_path.exists():
                        vtt_download_url = transcript_file.get('download_url')
                        if vtt_download_url:
                            zoom_client.download_file(vtt_download_url, access_token, vtt_path)
                    had_failures = tracker.record_download(zoom_uuid, meeting_topic, start_time, file_path)
                    _notify_if_resolved(had_failures, zoom_uuid, meeting_topic, "Download (retry)")
            except Exception as e:
                logger.error(f"Retry download failed: {e}")
                _handle_error(tracker, zoom_uuid, meeting_topic, start_time, f"Download failed: {e}")
                return

    # Step 2: Upload to YouTube
    if not existing_record or not existing_record.get('youtube_uploaded_at'):
        if dry_run:
            logger.info(f"[DRY RUN] Would upload to YouTube: {file_path}")
        else:
            try:
                if not file_path.exists():
                    raise FileNotFoundError(f"Video file not found: {file_path}")
                youtube_url = youtube_client.upload_video(
                    video_path=file_path,
                    title=folder_name,
                    description=config.YOUTUBE_DEFAULT_DESCRIPTION,
                    tags=[t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()],
                    category_id=config.YOUTUBE_CATEGORY_ID
                )
                had_failures = tracker.record_upload(zoom_uuid, youtube_url)
                logger.info(f"Uploaded to YouTube: {youtube_url}")
                _notify_if_resolved(had_failures, zoom_uuid, meeting_topic, "Upload")
            except Exception as e:
                logger.error(f"Upload failed: {e}")
                _handle_error(tracker, zoom_uuid, meeting_topic, start_time, f"Upload failed: {e}")
                return
    else:
        logger.info(f"Already uploaded: {existing_record.get('youtube_url')}")

    # Step 3: Transcribe with VTT hints + generate title + save transcript
    existing_record = tracker.get_record(zoom_uuid)  # Refresh
    transcript_url = existing_record.get('transcript_url', '') if existing_record else ''
    generated_title = existing_record.get('generated_title', '') if existing_record else ''
    transcription_cost = ''

    if not existing_record or not existing_record.get('transcribed_at'):
        if dry_run:
            logger.info(f"[DRY RUN] Would transcribe: {file_path}")
        else:
            try:
                # Pass VTT path for speaker hints
                vtt_for_transcription = str(vtt_path) if vtt_path.exists() else None
                transcript, usage = transcription_client.transcribe_video(
                    str(file_path), duration_seconds,
                    vtt_path=vtt_for_transcription,
                )
                if transcript:
                    generated_title = transcription_client.generate_title(transcript, usage) or ''

                    # Build full title with date/time prefix from start_time
                    if generated_title:
                        dt_prefix = _format_meeting_datetime(start_time).replace(':', '-')
                        full_title = f"{dt_prefix} - {generated_title}" if dt_prefix else generated_title
                    else:
                        full_title = folder_name

                    # Add markdown header with title and date
                    header_title = generated_title or meeting_topic or folder_name
                    header_date = _format_meeting_datetime(start_time)
                    header = f"# {header_title}\n\n**{header_date}**\n\n"
                    transcript = header + transcript

                    transcript_url = transcript_storage.save_transcript(
                        transcript, folder_name, generated_title or None
                    ) or ''

                    # Update YouTube title
                    youtube_url = existing_record.get('youtube_url', '') if existing_record else ''
                    if generated_title and youtube_url:
                        description = f"{config.YOUTUBE_DEFAULT_DESCRIPTION}\n\nFolder: {folder_name}"
                        youtube_client.update_video_title(youtube_url, full_title, description)

                    # Rename folder to match generated title
                    if generated_title and full_title != folder_name:
                        new_folder_path = config.DOWNLOAD_DIR / full_title
                        try:
                            file_path.parent.rename(new_folder_path)
                            file_path = new_folder_path / file_path.name
                            folder_name = full_title
                            logger.info(f"Renamed folder to: {full_title}")
                        except OSError as e:
                            logger.warning(f"Could not rename folder: {e}")

                    had_failures = tracker.record_transcription(
                        zoom_uuid, transcript_url, generated_title
                    )
                    transcription_cost = usage.cost_string()
                    logger.info(f"Transcription complete: {full_title} ({transcription_cost})")
                    _notify_if_resolved(had_failures, zoom_uuid, meeting_topic, "Transcription")
                else:
                    logger.info("Transcription skipped or returned no result")
            except Exception as e:
                logger.warning(f"Transcription step failed: {e}")
                _handle_error(tracker, zoom_uuid, meeting_topic, start_time, f"Transcription failed: {e}")
                # Continue to Discord notification without transcript
    else:
        logger.info(f"Already transcribed: {transcript_url}")

    # Step 4: Send Discord notification
    existing_record = tracker.get_record(zoom_uuid)  # Refresh
    youtube_url = existing_record.get('youtube_url', '') if existing_record else ''
    transcript_url = existing_record.get('transcript_url', '') if existing_record else ''
    generated_title = existing_record.get('generated_title', '') if existing_record else ''

    if not existing_record or not existing_record.get('discord_notified_at'):
        if not youtube_url:
            logger.warning("Cannot send Discord notification: no YouTube URL")
            return

        if dry_run:
            logger.info(f"[DRY RUN] Would send Discord notification: {youtube_url}")
        else:
            try:
                success = discord_client.send_notification(
                    youtube_url,
                    transcript_url=transcript_url or None,
                    generated_title=generated_title or None,
                    meeting_topic=meeting_topic,
                    meeting_datetime=_format_meeting_datetime(start_time),
                    transcription_cost=transcription_cost or None,
                )
                if success:
                    had_failures = tracker.record_notification(zoom_uuid)
                    logger.info(f"Discord notification sent: {youtube_url}")
                    _notify_if_resolved(had_failures, zoom_uuid, meeting_topic, "Discord notification")
                else:
                    _handle_error(tracker, zoom_uuid, meeting_topic, start_time, "Discord notification failed")
            except Exception as e:
                logger.error(f"Discord notification failed: {e}")
                _handle_error(tracker, zoom_uuid, meeting_topic, start_time, f"Discord notification failed: {e}")
    else:
        logger.info(f"Already notified Discord: {youtube_url}")


def retry_failed_recordings(tracker: VideoTracker, dry_run: bool = False) -> None:
    """Retry failed or incomplete recordings."""
    retry_records = tracker.get_records_for_retry()

    if not retry_records:
        logger.info("No recordings need retry")
        return

    logger.info(f"Found {len(retry_records)} recording(s) to retry")

    access_token = None
    if not dry_run:
        try:
            access_token = zoom_client.get_access_token()
        except Exception as e:
            logger.error(f"Failed to get Zoom access token for retries: {e}")
            return

    for record in retry_records:
        uuid = record['zoom_uuid']
        meeting_topic = record.get('meeting_topic', 'Unknown Meeting')
        start_time = record.get('start_time', '')
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
                            folder_name = file_path.parent.name
                            title = folder_name if folder_name else meeting_topic
                            youtube_url = youtube_client.upload_video(
                                video_path=file_path,
                                title=title,
                                description=config.YOUTUBE_DEFAULT_DESCRIPTION,
                                tags=[t.strip() for t in config.YOUTUBE_DEFAULT_TAGS.split(",") if t.strip()],
                                category_id=config.YOUTUBE_CATEGORY_ID
                            )
                            had_failures = tracker.record_upload(uuid, youtube_url)
                            logger.info(f"Retry upload successful: {youtube_url}")
                            _notify_if_resolved(had_failures, uuid, meeting_topic, "Upload (retry)")
                        except Exception as e:
                            logger.error(f"Retry upload failed: {e}")
                            _handle_error(tracker, uuid, meeting_topic, start_time, f"Upload failed: {e}")

        # Note: Discord notification and transcription are NOT retried here.
        # After a successful retry upload, process_recording will handle
        # the remaining steps (transcription → Discord) on the next cron run.


LOCK_FILE = Path(__file__).parent / ".main.lock"


def _check_credentials(dry_run: bool) -> None:
    """Validate external service credentials. Runs even in dry-run mode."""
    logger.info("\nChecking credentials...")
    errors = []

    # Zoom
    try:
        zoom_client.get_access_token()
        logger.info("  Zoom: OK")
    except Exception as e:
        logger.error(f"  Zoom: FAILED - {e}")
        errors.append(f"Zoom: {e}")

    # YouTube - validate credentials without starting interactive OAuth
    try:
        youtube_client.check_credentials()
        logger.info("  YouTube: OK")
    except Exception as e:
        logger.error(f"  YouTube: FAILED - {e}")
        errors.append(f"YouTube: {e}")

    # Gemini - lightweight API check
    if config.GEMINI_API_KEY:
        try:
            from google import genai
            client = genai.Client(api_key=config.GEMINI_API_KEY)
            client.models.get(model=config.GEMINI_MODEL)
            logger.info("  Gemini: OK")
        except Exception as e:
            logger.error(f"  Gemini: FAILED - {e}")
            errors.append(f"Gemini: {e}")
    else:
        logger.warning("  Gemini: skipped (no API key)")

    # Discord webhook - test with a dry ping (HEAD request)
    try:
        import requests as req
        resp = req.head(config.DISCORD_WEBHOOK_URL, timeout=5)
        if resp.status_code < 400:
            logger.info("  Discord: OK")
        else:
            logger.warning(f"  Discord: HTTP {resp.status_code}")
            errors.append(f"Discord: HTTP {resp.status_code}")
    except Exception as e:
        logger.error(f"  Discord: FAILED - {e}")
        errors.append(f"Discord: {e}")

    # Transcripts repo (holds prompts, transcripts, summaries)
    if config.TRANSCRIPTS_REPO_URL:
        try:
            transcript_storage._ensure_repo(config.TRANSCRIPTS_REPO_PATH, config.TRANSCRIPTS_REPO_URL)
            logger.info("  Transcripts repo: OK")
        except Exception as e:
            logger.error(f"  Transcripts repo: FAILED - {e}")
            errors.append(f"Transcripts repo: {e}")

    # Prompt files (live in transcripts repo)
    for label, path in [
        ("Transcription prompt", config.TRANSCRIPTION_PROMPT_PATH),
        ("Title prompt", config.TITLE_PROMPT_PATH),
    ]:
        if path.exists():
            logger.info(f"  {label}: OK")
        else:
            logger.error(f"  {label}: MISSING - {path}")
            errors.append(f"{label}: {path} not found")

    if errors:
        summary = "; ".join(errors)
        if dry_run:
            logger.error(f"Credential check failed: {summary}")
            sys.exit(1)
        else:
            logger.warning(f"Credential issues detected: {summary}")
            try:
                discord_client.send_error_notification(
                    error_message="Credential/config check failed on startup",
                    error_details=summary,
                )
            except Exception as e:
                logger.warning(f"Failed to send Discord startup error: {e}")
            logger.warning("Continuing anyway — errors will be handled per-recording")


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

    # Prevent concurrent runs
    lock_fp = open(LOCK_FILE, "w")
    try:
        fcntl.flock(lock_fp, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print("Another instance is already running, exiting.", file=sys.stderr)
        sys.exit(1)

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

    _check_credentials(args.dry_run)

    tracker = VideoTracker()

    # Step 1: Retry failed recordings
    logger.info("\nStep 1: Retrying failed recordings...")
    retry_failed_recordings(tracker, dry_run=args.dry_run)

    # Step 2: Fetch and process new recordings
    logger.info("\nStep 2: Fetching new recordings from Zoom...")
    try:
        access_token = zoom_client.get_access_token()

        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=365)).strftime("%Y-%m-%d")

        recordings = zoom_client.list_recordings(
            access_token=access_token,
            limit=config.LAST_MEETINGS_TO_PROCESS,
            from_date=from_date,
            to_date=to_date
        )

        logger.info(f"Found {len(recordings)} recording(s) to process")

        # Sort by start_time so recordings are processed in chronological order
        recordings.sort(key=lambda r: r.get('start_time', ''))

        for idx, recording in enumerate(recordings, 1):
            logger.info(f"\n[{idx}/{len(recordings)}] Processing recording...")
            try:
                process_recording(recording, tracker, dry_run=args.dry_run)
            except Exception as e:
                logger.error(f"Error processing recording: {e}", exc_info=True)
                zoom_uuid = recording.get('uuid', '')
                if zoom_uuid:
                    _handle_error(
                        tracker, zoom_uuid,
                        recording.get('topic', 'Unknown Meeting'),
                        recording.get('start_time', ''),
                        f"Processing error: {e}",
                    )

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
