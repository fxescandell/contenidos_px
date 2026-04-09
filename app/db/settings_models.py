from typing import Optional, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, Boolean, JSON, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base
from app.core.settings_enums import SettingType

class SystemSetting(Base):
    __tablename__ = "system_settings"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    value_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    value_type: Mapped[SettingType] = mapped_column(SQLEnum(SettingType), default=SettingType.STRING)
    category: Mapped[str] = mapped_column(String(50), index=True)
    is_secret: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    description: Mapped[Optional[str]] = mapped_column(Text)
    
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    updated_by: Mapped[Optional[str]] = mapped_column(String(100))

class SettingsAuditLog(Base):
    __tablename__ = "settings_audit_logs"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    key: Mapped[Optional[str]] = mapped_column(String(100))
    section: Mapped[str] = mapped_column(String(50))
    action: Mapped[str] = mapped_column(String(50))
    old_value_masked: Mapped[Optional[str]] = mapped_column(Text)
    new_value_masked: Mapped[Optional[str]] = mapped_column(Text)
    performed_by: Mapped[str] = mapped_column(String(100), default="system")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
