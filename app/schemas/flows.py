from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel


class FlowCreate(BaseModel):
    name: str
    municipality: str
    category: str
    source_mode: str = "smb"
    source_folder: str
    output_filename: str
    enabled: bool = True
    auto_process: bool = False


class FlowUpdate(BaseModel):
    name: Optional[str] = None
    municipality: Optional[str] = None
    category: Optional[str] = None
    source_mode: Optional[str] = None
    source_folder: Optional[str] = None
    output_filename: Optional[str] = None
    enabled: Optional[bool] = None
    auto_process: Optional[bool] = None


class FlowResponse(BaseModel):
    id: UUID
    name: str
    municipality: str
    category: str
    source_mode: str
    source_folder: str
    output_filename: str
    enabled: bool
    auto_process: bool
    last_run_at: Optional[datetime] = None
    last_run_status: Optional[str] = None
    last_run_summary: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class FlowRunRequest(BaseModel):
    flow_id: Optional[UUID] = None
    municipality: Optional[str] = None
    category: Optional[str] = None
