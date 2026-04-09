from abc import ABC, abstractmethod
from typing import List, Tuple, Optional
from datetime import datetime
import mimetypes

from app.schemas.inbox import (
    InboxConnectionSettings, InboxConnectionTestResult, InboxPathValidationResult,
    InboxListResult, InboxFetchResult, InboxEntry
)
from app.core.inbox_enums import ProcessedEntryAction

class BaseRemoteInboxClient(ABC):
    def __init__(self, settings: InboxConnectionSettings):
        self.settings = settings
        
    @abstractmethod
    def test_connection(self) -> InboxConnectionTestResult:
        pass
        
    @abstractmethod
    def validate_base_path(self) -> InboxPathValidationResult:
        pass
        
    @abstractmethod
    def list_entries(self, sub_path: Optional[str] = None) -> InboxListResult:
        pass
        
    @abstractmethod
    def fetch_entry(self, remote_path: str, local_destination_dir: str) -> InboxFetchResult:
        pass
        
    @abstractmethod
    def fetch_batch(self, batch_path: str, local_destination_dir: str) -> InboxFetchResult:
        pass
        
    @abstractmethod
    def move_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        pass
        
    @abstractmethod
    def delete_processed_entry(self, remote_path: str) -> Tuple[bool, str]:
        pass
        
    def _get_mime_type(self, file_path: str) -> str:
        mime, _ = mimetypes.guess_type(file_path)
        return mime or "application/octet-stream"
        
    def _is_allowed_extension(self, file_path: str) -> bool:
        if not self.settings.extensions_allowlist:
            return True
        ext = "." + file_path.split('.')[-1].lower() if "." in file_path else ""
        return ext in self.settings.extensions_allowlist
