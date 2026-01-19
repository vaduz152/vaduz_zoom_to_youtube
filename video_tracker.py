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
    "last_notified_error"
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
                if 'failure_count' not in row:
                    row['failure_count'] = '0'
                if 'error_notified_at' not in row:
                    row['error_notified_at'] = ''
                if 'last_notified_error' not in row:
                    row['last_notified_error'] = ''
                records.append(row)
        return records
    
    def _write_all_records(self, records: list[dict]) -> None:
        """Write all records to CSV."""
        with open(self.csv_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
            writer.writerows(records)
    
    def is_processed(self, zoom_uuid: str) -> bool:
        """Check if a recording has been fully processed (downloaded + uploaded + notified)."""
        records = self._read_all_records()
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                # Check if fully processed
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
    
    def record_download(
        self,
        zoom_uuid: str,
        meeting_topic: str,
        start_time: str,
        file_path: Path
    ) -> bool:
        """
        Record a successful download.
        
        Returns:
            True if there were previous failures that were resolved, False otherwise
        """
        records = self._read_all_records()
        
        # Find existing record or create new one
        record = None
        for r in records:
            if r['zoom_uuid'] == zoom_uuid:
                record = r
                break
        
        if record is None:
            record = {header: '' for header in CSV_HEADERS}
            record['zoom_uuid'] = zoom_uuid
            record['meeting_topic'] = meeting_topic
            record['start_time'] = start_time
            record['failure_count'] = '0'
            record['error_notified_at'] = ''
            records.append(record)
        
        # Check if there were previous failures before clearing
        had_failures = False
        try:
            failure_count = int(record.get('failure_count', '0') or '0')
            had_failures = failure_count >= config.ERROR_NOTIFICATION_THRESHOLD
        except (ValueError, TypeError):
            pass
        
        record['file_path'] = str(file_path)
        record['zoom_downloaded_at'] = datetime.now().isoformat()
        record['status'] = 'downloaded'
        record['error_message'] = ''  # Clear any previous errors
        record['failure_count'] = '0'  # Reset failure count on success
        record['error_notified_at'] = ''  # Clear notification timestamp
        record['last_notified_error'] = ''  # Clear last notified error
        
        self._write_all_records(records)
        logger.debug(f"Recorded download: {zoom_uuid}")
        
        return had_failures
    
    def record_upload(self, zoom_uuid: str, youtube_url: str) -> bool:
        """
        Record a successful upload.
        
        Returns:
            True if there were previous failures that were resolved, False otherwise
        """
        records = self._read_all_records()
        
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                # Check if there were previous failures before clearing
                had_failures = False
                try:
                    failure_count = int(record.get('failure_count', '0') or '0')
                    had_failures = failure_count >= config.ERROR_NOTIFICATION_THRESHOLD
                except (ValueError, TypeError):
                    pass
                
                record['youtube_uploaded_at'] = datetime.now().isoformat()
                record['youtube_url'] = youtube_url
                record['status'] = 'uploaded'
                record['error_message'] = ''  # Clear any previous errors
                record['failure_count'] = '0'  # Reset failure count on success
                record['error_notified_at'] = ''  # Clear notification timestamp
                record['last_notified_error'] = ''  # Clear last notified error
                self._write_all_records(records)
                logger.debug(f"Recorded upload: {zoom_uuid}")
                return had_failures
        
        logger.warning(f"Attempted to record upload for unknown UUID: {zoom_uuid}")
        return False
    
    def record_notification(self, zoom_uuid: str) -> bool:
        """
        Record a successful Discord notification.
        
        Returns:
            True if there were previous failures that were resolved, False otherwise
        """
        records = self._read_all_records()
        
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                # Check if there were previous failures before clearing
                had_failures = False
                try:
                    failure_count = int(record.get('failure_count', '0') or '0')
                    had_failures = failure_count >= config.ERROR_NOTIFICATION_THRESHOLD
                except (ValueError, TypeError):
                    pass
                
                record['discord_notified_at'] = datetime.now().isoformat()
                record['status'] = 'notified'
                record['error_message'] = ''  # Clear any previous errors
                record['failure_count'] = '0'  # Reset failure count on success
                record['error_notified_at'] = ''  # Clear notification timestamp
                record['last_notified_error'] = ''  # Clear last notified error
                self._write_all_records(records)
                logger.debug(f"Recorded notification: {zoom_uuid}")
                return had_failures
        
        logger.warning(f"Attempted to record notification for unknown UUID: {zoom_uuid}")
        return False
    
    def record_error(self, zoom_uuid: str, error_message: str, status: str = 'failed') -> bool:
        """
        Record an error and increment failure count.
        
        Returns:
            True if notification should be sent (threshold reached), False otherwise
        """
        records = self._read_all_records()
        
        # Find existing record or create new one
        record = None
        for r in records:
            if r['zoom_uuid'] == zoom_uuid:
                record = r
                break
        
        if record is None:
            record = {header: '' for header in CSV_HEADERS}
            record['zoom_uuid'] = zoom_uuid
            record['failure_count'] = '0'
            record['error_notified_at'] = ''
            record['last_notified_error'] = ''
            records.append(record)
        
        # Increment failure count
        try:
            failure_count = int(record.get('failure_count', '0') or '0')
        except (ValueError, TypeError):
            failure_count = 0
        
        failure_count += 1
        
        # Check previous error message before updating
        previous_error = record.get('error_message', '')
        error_notified_at = record.get('error_notified_at', '')
        
        record['status'] = status
        record['error_message'] = str(error_message)
        record['failure_count'] = str(failure_count)
        
        # Check if we should send notification
        should_notify = False
        last_notified_error = record.get('last_notified_error', '')
        
        if failure_count >= config.ERROR_NOTIFICATION_THRESHOLD:
            # Only notify if error message is different from the last notified error
            # This prevents duplicate notifications for the same persistent error
            if str(error_message) != last_notified_error:
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
            uuid = record['zoom_uuid']
            status = record.get('status', '')
            file_path = record.get('file_path', '')
            
            # Check if needs retry
            needs_retry = False
            
            # If status is failed, needs retry
            if status == 'failed':
                needs_retry = True
            # If downloaded but not uploaded, needs retry
            elif record.get('zoom_downloaded_at') and not record.get('youtube_uploaded_at'):
                needs_retry = True
            # If uploaded but not notified, needs retry
            elif record.get('youtube_uploaded_at') and not record.get('discord_notified_at'):
                needs_retry = True
            
            # Only retry if file still exists (for downloads/uploads)
            if needs_retry and file_path:
                file_path_obj = Path(file_path)
                if not file_path_obj.exists():
                    # File doesn't exist, skip retry
                    continue
            
            if needs_retry:
                retry_records.append(record)
        
        return retry_records
    
    def get_all_records(self) -> list[dict]:
        """Get all records (for cleanup operations)."""
        return self._read_all_records()

