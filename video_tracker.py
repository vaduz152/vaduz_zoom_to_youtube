"""CSV-based tracking database for processed recordings."""
import csv
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

CSV_HEADERS = [
    "zoom_uuid",
    "meeting_topic",
    "start_time",
    "file_path",
    "zoom_downloaded_at",
    "youtube_uploaded_at",
    "youtube_url",
    "discord_notified_at",
    "status",
    "error_message",
    "failure_count",
    "error_notified_at",
    "last_notified_error",
    "transcribed_at",
    "transcript_url",
    "generated_title"
]


class VideoTracker:
    """Manages CSV tracking database for processed recordings."""

    def __init__(self, csv_path: Path = None):
        self.csv_path = csv_path or config.CSV_TRACKER_PATH
        self._ensure_csv_exists()

    def _ensure_csv_exists(self) -> None:
        """Create CSV file with headers if it doesn't exist."""
        if not self.csv_path.exists():
            with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
                writer.writeheader()
            logger.debug(f"Created CSV tracker: {self.csv_path}")

    def _read_all_records(self) -> list[dict]:
        """Read all records from CSV."""
        if not self.csv_path.exists():
            return []

        records = []
        with open(self.csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Ensure backward compatibility: add missing fields if they don't exist
                for field in ('failure_count',):
                    if field not in row:
                        row[field] = '0'
                for field in ('error_notified_at', 'last_notified_error',
                              'transcribed_at', 'transcript_url', 'generated_title'):
                    if field not in row:
                        row[field] = ''
                records.append(row)
        return records

    def _write_all_records(self, records: list[dict]) -> None:
        """Write all records to CSV."""
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            writer.writerows(records)

    def _find_or_create(self, records: list[dict], zoom_uuid: str) -> dict:
        """Find existing record by UUID, or create and append a new one."""
        for r in records:
            if r['zoom_uuid'] == zoom_uuid:
                return r
        record = {header: '' for header in CSV_HEADERS}
        record['zoom_uuid'] = zoom_uuid
        record['failure_count'] = '0'
        records.append(record)
        return record

    def _had_notified_failures(self, record: dict) -> bool:
        """Check if record had failures that crossed the notification threshold."""
        try:
            return int(record.get('failure_count', '0') or '0') >= config.ERROR_NOTIFICATION_THRESHOLD
        except (ValueError, TypeError):
            return False

    def _clear_errors(self, record: dict) -> None:
        """Clear error state after a successful step."""
        record['error_message'] = ''
        record['failure_count'] = '0'
        record['error_notified_at'] = ''
        record['last_notified_error'] = ''

    def _record_success(
        self,
        zoom_uuid: str,
        status: str,
        fields: dict,
        create_if_missing: bool = False,
    ) -> bool:
        """
        Generic success recording: find record, check had_failures, update fields,
        clear errors, save.

        Returns True if there were previous failures that were resolved.
        """
        records = self._read_all_records()

        if create_if_missing:
            record = self._find_or_create(records, zoom_uuid)
        else:
            record = None
            for r in records:
                if r['zoom_uuid'] == zoom_uuid:
                    record = r
                    break
            if record is None:
                logger.warning(f"Attempted to record {status} for unknown UUID: {zoom_uuid}")
                return False

        had_failures = self._had_notified_failures(record)
        record['status'] = status
        for k, v in fields.items():
            record[k] = v
        self._clear_errors(record)
        self._write_all_records(records)
        logger.debug(f"Recorded {status}: {zoom_uuid}")
        return had_failures

    def is_processed(self, zoom_uuid: str) -> bool:
        """Check if a recording has been fully processed or intentionally skipped."""
        records = self._read_all_records()
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                if record.get('status') == 'skipped':
                    return True
                return bool(
                    record.get('zoom_downloaded_at') and
                    record.get('youtube_uploaded_at') and
                    record.get('discord_notified_at')
                )
        return False

    def get_record(self, zoom_uuid: str) -> Optional[dict]:
        """Get a record by UUID."""
        records = self._read_all_records()
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                return record
        return None

    def update_meeting_metadata(
        self,
        zoom_uuid: str,
        meeting_topic: str = '',
        start_time: str = ''
    ) -> bool:
        """
        Update meeting_topic and start_time for an existing record if they are missing.

        Returns:
            True if any field was updated, False otherwise.
        """
        if not meeting_topic and not start_time:
            return False

        records = self._read_all_records()

        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                updated = False
                if meeting_topic and not record.get('meeting_topic'):
                    record['meeting_topic'] = meeting_topic
                    updated = True
                if start_time and not record.get('start_time'):
                    record['start_time'] = start_time
                    updated = True

                if updated:
                    self._write_all_records(records)
                    logger.debug(f"Updated metadata for: {zoom_uuid}")
                return updated

        return False

    def record_download(
        self,
        zoom_uuid: str,
        meeting_topic: str,
        start_time: str,
        file_path: Path
    ) -> bool:
        """Record a successful download. Returns True if previous failures were resolved."""
        fields = {
            'file_path': str(file_path),
            'zoom_downloaded_at': datetime.now().isoformat(),
        }
        if meeting_topic:
            fields['meeting_topic'] = meeting_topic
        if start_time:
            fields['start_time'] = start_time
        return self._record_success(zoom_uuid, 'downloaded', fields, create_if_missing=True)

    def record_upload(self, zoom_uuid: str, youtube_url: str) -> bool:
        """Record a successful upload. Returns True if previous failures were resolved."""
        return self._record_success(zoom_uuid, 'uploaded', {
            'youtube_uploaded_at': datetime.now().isoformat(),
            'youtube_url': youtube_url,
        })

    def record_notification(self, zoom_uuid: str) -> bool:
        """Record a successful Discord notification. Returns True if previous failures were resolved."""
        return self._record_success(zoom_uuid, 'notified', {
            'discord_notified_at': datetime.now().isoformat(),
        })

    def record_transcription(
        self,
        zoom_uuid: str,
        transcript_url: str,
        generated_title: str = ''
    ) -> bool:
        """Record a successful transcription. Returns True if previous failures were resolved."""
        return self._record_success(zoom_uuid, 'transcribed', {
            'transcribed_at': datetime.now().isoformat(),
            'transcript_url': transcript_url,
            'generated_title': generated_title,
        })

    def record_skipped(
        self,
        zoom_uuid: str,
        reason: str,
        meeting_topic: str = '',
        start_time: str = ''
    ) -> None:
        """
        Record that a recording was intentionally skipped (e.g., video too short).

        This is not an error — it marks the recording as permanently skipped
        without incrementing failure count or triggering Discord notifications.
        """
        records = self._read_all_records()
        record = self._find_or_create(records, zoom_uuid)

        if meeting_topic and not record.get('meeting_topic'):
            record['meeting_topic'] = meeting_topic
        if start_time and not record.get('start_time'):
            record['start_time'] = start_time

        record['status'] = 'skipped'
        record['error_message'] = str(reason)

        self._write_all_records(records)
        logger.info(f"Recorded skip: {zoom_uuid} - {reason}")

    def record_error(
        self,
        zoom_uuid: str,
        error_message: str,
        status: str = 'failed',
        meeting_topic: str = '',
        start_time: str = ''
    ) -> bool:
        """
        Record an error and increment failure count.

        Returns:
            True if notification should be sent (threshold reached), False otherwise
        """
        records = self._read_all_records()
        record = self._find_or_create(records, zoom_uuid)

        if meeting_topic and not record.get('meeting_topic'):
            record['meeting_topic'] = meeting_topic
        if start_time and not record.get('start_time'):
            record['start_time'] = start_time

        try:
            failure_count = int(record.get('failure_count', '0') or '0')
        except (ValueError, TypeError):
            failure_count = 0

        failure_count += 1

        record['status'] = status
        record['error_message'] = str(error_message)
        record['failure_count'] = str(failure_count)

        # Only notify if error is different from last notified error
        should_notify = False
        if failure_count >= config.ERROR_NOTIFICATION_THRESHOLD:
            if str(error_message) != record.get('last_notified_error', ''):
                should_notify = True
                record['error_notified_at'] = datetime.now().isoformat()
                record['last_notified_error'] = str(error_message)

        self._write_all_records(records)
        logger.debug(f"Recorded error: {zoom_uuid} - {error_message} (failure_count: {failure_count})")

        return should_notify

    def get_records_for_retry(self) -> list[dict]:
        """Get records that need retry (failed or incomplete)."""
        records = self._read_all_records()
        retry_records = []

        for record in records:
            status = record.get('status', '')
            file_path = record.get('file_path', '')

            needs_retry = False
            if status == 'failed':
                needs_retry = True
            elif record.get('zoom_downloaded_at') and not record.get('youtube_uploaded_at'):
                needs_retry = True
            elif record.get('youtube_uploaded_at') and not record.get('discord_notified_at'):
                needs_retry = True

            if needs_retry and file_path:
                if not Path(file_path).exists():
                    continue

            if needs_retry:
                retry_records.append(record)

        return retry_records

    def get_all_records(self) -> list[dict]:
        """Get all records (for cleanup operations)."""
        return self._read_all_records()
