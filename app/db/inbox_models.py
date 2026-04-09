from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, DateTime, Text, Enum as SQLEnum, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from sqlalchemy.sql import func
from app.db.base import Base
from app.core.inbox_enums import InboxMode

class InboxFetchHistory(Base):
    __tablename__ = "inbox_fetch_history"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    inbox_mode: Mapped[InboxMode] = mapped_column(SQLEnum(InboxMode))
    source_identifier: Mapped[str] = mapped_column(String(255), index=True) # Hash or unique ID
    source_path: Mapped[str] = mapped_column(String(1024))
    source_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    source_modified_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    
    local_working_path: Mapped[Optional[str]] = mapped_column(String(1024))
    batch_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("source_batches.id", ondelete="SET NULL"))
    
    fetch_status: Mapped[str] = mapped_column(String(50)) # SUCCESS, FAILED
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
