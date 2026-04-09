from typing import List, Optional, Any, Dict
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.db.repositories.base import BaseRepository
from app.db.settings_models import SystemSetting, SettingsAuditLog
from app.core.settings_enums import SettingType

class SystemSettingRepository(BaseRepository[SystemSetting]):
    def __init__(self):
        super().__init__(SystemSetting)

    def get_by_key(self, db: Session, key: str) -> Optional[SystemSetting]:
        return db.execute(select(self.model).where(self.model.key == key)).scalar_one_or_none()

    def get_by_category(self, db: Session, category: str) -> List[SystemSetting]:
        return db.execute(select(self.model).where(self.model.category == category)).scalars().all()

class SettingsAuditLogRepository(BaseRepository[SettingsAuditLog]):
    def __init__(self):
        super().__init__(SettingsAuditLog)

system_setting_repo = SystemSettingRepository()
settings_audit_repo = SettingsAuditLogRepository()
