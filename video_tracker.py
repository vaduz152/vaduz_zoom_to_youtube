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
    "error_message"
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
    ) -> None:
        """Record a successful download."""
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
            records.append(record)
        
        record['file_path'] = str(file_path)
        record['zoom_downloaded_at'] = datetime.now().isoformat()
        record['status'] = 'downloaded'
        record['error_message'] = ''  # Clear any previous errors
        
        self._write_all_records(records)
        logger.debug(f"Recorded download: {zoom_uuid}")
    
    def record_upload(self, zoom_uuid: str, youtube_url: str) -> None:
        """Record a successful upload."""
        records = self._read_all_records()
        
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                record['youtube_uploaded_at'] = datetime.now().isoformat()
                record['youtube_url'] = youtube_url
                record['status'] = 'uploaded'
                record['error_message'] = ''  # Clear any previous errors
                self._write_all_records(records)
                logger.debug(f"Recorded upload: {zoom_uuid}")
                return
        
        logger.warning(f"Attempted to record upload for unknown UUID: {zoom_uuid}")
    
    def record_notification(self, zoom_uuid: str) -> None:
        """Record a successful Discord notification."""
        records = self._read_all_records()
        
        for record in records:
            if record['zoom_uuid'] == zoom_uuid:
                record['discord_notified_at'] = datetime.now().isoformat()
                record['status'] = 'notified'
                record['error_message'] = ''  # Clear any previous errors
                self._write_all_records(records)
                logger.debug(f"Recorded notification: {zoom_uuid}")
                return
        
        logger.warning(f"Attempted to record notification for unknown UUID: {zoom_uuid}")
    
    def record_error(self, zoom_uuid: str, error_message: str, status: str = 'failed') -> None:
        """Record an error."""
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
            records.append(record)
        
        record['status'] = status
        record['error_message'] = str(error_message)
        
        self._write_all_records(records)
        logger.debug(f"Recorded error: {zoom_uuid} - {error_message}")
    
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

