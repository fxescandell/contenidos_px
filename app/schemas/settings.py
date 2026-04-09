from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from app.core.settings_enums import SettingType

class SettingItemRead(BaseModel):
    key: str
    value: Any
    value_type: SettingType
    category: str
    is_secret: bool
    description: Optional[str]

class SettingItemUpdate(BaseModel):
    key: str
    value: Any
    value_type: SettingType
    is_secret: bool = False
    description: Optional[str] = None

class SettingsSectionUpdate(BaseModel):
    settings: List[SettingItemUpdate]

class SettingsSectionRead(BaseModel):
    category: str
    settings: List[SettingItemRead]

class SettingsValidationResult(BaseModel):
    is_valid: bool
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

class SettingsTestResult(BaseModel):
    success: bool
    message: str
    details: Optional[str] = None
    timestamp: str

class SettingsStatusSummary(BaseModel):
    is_loaded: bool
    last_modified: Optional[str]
    missing_sections: List[str] = Field(default_factory=list)
    validation_errors: List[str] = Field(default_factory=list)
    
    telegram_status: str
    inbox_status: str
    ocr_status: str
    llm_status: str
    paths_status: str
