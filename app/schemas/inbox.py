from typing import Optional, List, Dict, Any
from datetime import datetime
from pydantic import BaseModel, Field, field_validator

from app.core.inbox_enums import InboxMode, ProcessedEntryAction

class InboxConnectionSettings(BaseModel):
    mode: InboxMode
    local_path: Optional[str] = None
    
    host: Optional[str] = None
    port: Optional[int] = None
    username: Optional[str] = None
    password: Optional[str] = None
    base_path: str = "/"
    use_passive_mode: bool = True
    timeout_seconds: int = 30
    
    delete_after_import: bool = False
    move_after_import: bool = False
    processed_path: Optional[str] = None
    
    recursive_scan: bool = False
    max_depth: int = 1
    ignore_hidden_files: bool = True
    extensions_allowlist: List[str] = Field(default_factory=lambda: [".pdf", ".docx", ".jpg", ".jpeg", ".png"])
    
    use_key_auth: bool = False
    private_key_path: Optional[str] = None
    private_key_passphrase: Optional[str] = None

class InboxEntry(BaseModel):
    name: str
    full_path: str
    relative_path: str
    is_dir: bool
    size_bytes: Optional[int] = None
    modified_at: Optional[datetime] = None
    extension: Optional[str] = None
    mime_type: Optional[str] = None

class InboxBatch(BaseModel):
    batch_name: str
    source_path: str
    entries: List[InboxEntry] = Field(default_factory=list)
    entry_count: int = 0
    total_size_bytes: int = 0

class InboxConnectionTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[str] = None
    tested_at: str

class InboxPathValidationResult(BaseModel):
    success: bool
    exists: bool
    is_dir: bool
    readable: bool
    writable: Optional[bool] = None
    message: str
    tested_at: str

class InboxFetchResult(BaseModel):
    success: bool
    source_path: str
    local_destination_path: str
    downloaded_files_count: int
    skipped_files_count: int
    total_bytes: int
    message: str
    fetched_at: str

class InboxListResult(BaseModel):
    success: bool
    entries: List[InboxEntry] = Field(default_factory=list)
    message: str
    listed_at: str
