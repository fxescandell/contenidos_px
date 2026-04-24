from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID, uuid4
from sqlalchemy import String, Integer, Float, Boolean, JSON, ForeignKey, DateTime, Text, Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.sql import func

from app.db.base import Base
from app.core.enums import (
    Municipality, ContentCategory, ContentSubtype, ReviewReason, 
    ExtractionMethod, ExportFormat, ImageRole, ValidationSeverity, 
    SourceFileRole, CandidateGroupingStrategy, EventLevel, ReprocessingScope
)
from app.core.states import BatchStatus, CandidateStatus, ExportStatus, ReprocessingStatus

class SourceBatch(Base):
    __tablename__ = "source_batches"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    external_name: Mapped[str] = mapped_column(String(255), index=True)
    original_path: Mapped[str] = mapped_column(String(1024))
    working_path: Mapped[str] = mapped_column(String(1024))
    batch_sha256: Mapped[str] = mapped_column(String(64), index=True)
    
    municipality_hint: Mapped[Optional[str]] = mapped_column(String(100))
    category_hint: Mapped[Optional[str]] = mapped_column(String(100))
    
    status: Mapped[BatchStatus] = mapped_column(SQLEnum(BatchStatus), default=BatchStatus.DETECTED)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String(255))
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    files: Mapped[List["SourceFile"]] = relationship(back_populates="batch", cascade="all, delete-orphan")
    candidates: Mapped[List["ContentCandidate"]] = relationship(back_populates="batch", cascade="all, delete-orphan")

class SourceFile(Base):
    __tablename__ = "source_files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("source_batches.id", ondelete="CASCADE"))
    
    original_path: Mapped[str] = mapped_column(String(1024))
    working_path: Mapped[str] = mapped_column(String(1024))
    relative_path: Mapped[str] = mapped_column(String(1024))
    file_name: Mapped[str] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(20))
    mime_type: Mapped[str] = mapped_column(String(100))
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    
    file_role: Mapped[SourceFileRole] = mapped_column(SQLEnum(SourceFileRole), default=SourceFileRole.UNKNOWN)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    batch: Mapped["SourceBatch"] = relationship(back_populates="files")

class ContentCandidate(Base):
    __tablename__ = "content_candidates"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[UUID] = mapped_column(ForeignKey("source_batches.id", ondelete="CASCADE"))
    
    candidate_key: Mapped[str] = mapped_column(String(255), index=True)
    grouping_strategy: Mapped[CandidateGroupingStrategy] = mapped_column(SQLEnum(CandidateGroupingStrategy))
    grouping_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    
    municipality: Mapped[Optional[Municipality]] = mapped_column(SQLEnum(Municipality))
    category: Mapped[Optional[ContentCategory]] = mapped_column(SQLEnum(ContentCategory))
    subtype: Mapped[Optional[ContentSubtype]] = mapped_column(SQLEnum(ContentSubtype))
    
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float)
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)
    editorial_confidence: Mapped[Optional[float]] = mapped_column(Float)
    
    status: Mapped[CandidateStatus] = mapped_column(SQLEnum(CandidateStatus), default=CandidateStatus.CREATED)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reason: Mapped[Optional[str]] = mapped_column(String(255))
    title_hint: Mapped[Optional[str]] = mapped_column(String(255))
    featured_source_file_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("source_files.id", ondelete="SET NULL"))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    batch: Mapped["SourceBatch"] = relationship(back_populates="candidates")
    canonical_content: Mapped[Optional["CanonicalContent"]] = relationship(back_populates="candidate", uselist=False, cascade="all, delete-orphan")

class CandidateSourceFile(Base):
    __tablename__ = "candidate_source_files"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    
    assigned_role: Mapped[SourceFileRole] = mapped_column(SQLEnum(SourceFileRole))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ExtractedDocument(Base):
    __tablename__ = "extracted_documents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    
    extraction_method: Mapped[ExtractionMethod] = mapped_column(SQLEnum(ExtractionMethod))
    extraction_confidence: Mapped[float] = mapped_column(Float, default=0.0)
    detected_language: Mapped[Optional[str]] = mapped_column(String(10))
    
    raw_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CandidateImage(Base):
    __tablename__ = "candidate_images"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    source_file_id: Mapped[UUID] = mapped_column(ForeignKey("source_files.id", ondelete="CASCADE"))
    
    original_path: Mapped[str] = mapped_column(String(1024))
    optimized_path: Mapped[Optional[str]] = mapped_column(String(1024))
    
    width: Mapped[Optional[int]] = mapped_column(Integer)
    height: Mapped[Optional[int]] = mapped_column(Integer)
    
    original_format: Mapped[Optional[str]] = mapped_column(String(20))
    optimized_format: Mapped[Optional[str]] = mapped_column(String(20))
    optimized_file_size_bytes: Mapped[Optional[int]] = mapped_column(Integer)
    sha256: Mapped[Optional[str]] = mapped_column(String(64))
    
    image_role: Mapped[ImageRole] = mapped_column(SQLEnum(ImageRole), default=ImageRole.UNKNOWN)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    processing_status: Mapped[str] = mapped_column(String(50), default="PENDING")
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class CanonicalContent(Base):
    __tablename__ = "canonical_contents"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"), unique=True)
    
    municipality: Mapped[Municipality] = mapped_column(SQLEnum(Municipality))
    category: Mapped[ContentCategory] = mapped_column(SQLEnum(ContentCategory))
    subtype: Mapped[ContentSubtype] = mapped_column(SQLEnum(ContentSubtype))
    
    source_title: Mapped[Optional[str]] = mapped_column(String(500))
    detected_title: Mapped[Optional[str]] = mapped_column(String(500))
    final_title: Mapped[Optional[str]] = mapped_column(String(500))
    
    source_summary: Mapped[Optional[str]] = mapped_column(Text)
    final_summary: Mapped[Optional[str]] = mapped_column(Text)
    
    source_body_text: Mapped[Optional[str]] = mapped_column(Text)
    final_body_html: Mapped[Optional[str]] = mapped_column(Text)
    
    structured_fields_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    metadata_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    extraction_confidence: Mapped[Optional[float]] = mapped_column(Float)
    grouping_confidence: Mapped[Optional[float]] = mapped_column(Float)
    classification_confidence: Mapped[Optional[float]] = mapped_column(Float)
    editorial_confidence: Mapped[Optional[float]] = mapped_column(Float)
    
    requires_review: Mapped[bool] = mapped_column(Boolean, default=False)
    review_reasons_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    errors_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    warnings_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    candidate: Mapped["ContentCandidate"] = relationship(back_populates="canonical_content")

class ValidationReport(Base):
    __tablename__ = "validation_reports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    
    validator_name: Mapped[str] = mapped_column(String(100))
    severity: Mapped[ValidationSeverity] = mapped_column(SQLEnum(ValidationSeverity))
    code: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    details_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class WordPressExport(Base):
    __tablename__ = "wordpress_exports"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    candidate_id: Mapped[UUID] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    
    export_format: Mapped[ExportFormat] = mapped_column(SQLEnum(ExportFormat))
    adapter_name: Mapped[str] = mapped_column(String(100))
    export_status: Mapped[ExportStatus] = mapped_column(SQLEnum(ExportStatus), default=ExportStatus.PENDING)
    
    export_path: Mapped[Optional[str]] = mapped_column(String(1024))
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    checksum: Mapped[str] = mapped_column(String(64))
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    exported_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

class ProcessingEvent(Base):
    __tablename__ = "processing_events"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("source_batches.id", ondelete="CASCADE"))
    candidate_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    
    level: Mapped[EventLevel] = mapped_column(SQLEnum(EventLevel), default=EventLevel.INFO)
    event_type: Mapped[str] = mapped_column(String(100))
    stage: Mapped[str] = mapped_column(String(100))
    message: Mapped[str] = mapped_column(Text)
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

class ReprocessingRequest(Base):
    __tablename__ = "reprocessing_requests"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    batch_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("source_batches.id", ondelete="CASCADE"))
    candidate_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("content_candidates.id", ondelete="CASCADE"))
    
    requested_by: Mapped[str] = mapped_column(String(100))
    reason: Mapped[str] = mapped_column(Text)
    force_full_rebuild: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[ReprocessingStatus] = mapped_column(SQLEnum(ReprocessingStatus), default=ReprocessingStatus.PENDING)
    
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


class ManualExportDraft(Base):
    __tablename__ = "manual_export_drafts"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    flow_id: Mapped[UUID] = mapped_column(ForeignKey("flows.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)

    pending_batch_id: Mapped[Optional[str]] = mapped_column(String(64))
    pending_payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    pending_articles_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON)
    pending_files_json: Mapped[Optional[List[str]]] = mapped_column(JSON)
    pending_summary: Mapped[Optional[str]] = mapped_column(Text)
    pending_created_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    final_export_path: Mapped[Optional[str]] = mapped_column(String(1024))
    final_export_message: Mapped[Optional[str]] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    finalized_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    items: Mapped[List["ManualExportItem"]] = relationship(
        back_populates="draft",
        cascade="all, delete-orphan",
        order_by="ManualExportItem.sequence",
    )


class ManualExportItem(Base):
    __tablename__ = "manual_export_items"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    draft_id: Mapped[UUID] = mapped_column(ForeignKey("manual_export_drafts.id", ondelete="CASCADE"), index=True)
    sequence: Mapped[int] = mapped_column(Integer, default=1)
    source_batch_id: Mapped[Optional[str]] = mapped_column(String(64))
    payload_json: Mapped[Dict[str, Any]] = mapped_column(JSON, default=dict)
    articles_json: Mapped[List[Dict[str, Any]]] = mapped_column(JSON, default=list)
    files_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    draft: Mapped["ManualExportDraft"] = relationship(back_populates="items")


class ManualTreeSession(Base):
    __tablename__ = "manual_tree_sessions"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    status: Mapped[str] = mapped_column(String(30), default="OPEN", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    groups: Mapped[List["ManualTreeGroup"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="ManualTreeGroup.category_name, ManualTreeGroup.article_name",
    )


class ManualTreeGroup(Base):
    __tablename__ = "manual_tree_groups"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    session_id: Mapped[UUID] = mapped_column(ForeignKey("manual_tree_sessions.id", ondelete="CASCADE"), index=True)
    group_key: Mapped[str] = mapped_column(String(512), index=True)
    category_name: Mapped[str] = mapped_column(String(255), index=True)
    article_name: Mapped[str] = mapped_column(String(255), index=True)
    files_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="UNASSIGNED", index=True)
    validation_errors_json: Mapped[List[str]] = mapped_column(JSON, default=list)
    assigned_flow_id: Mapped[Optional[UUID]] = mapped_column(ForeignKey("flows.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    session: Mapped["ManualTreeSession"] = relationship(back_populates="groups")
    preview: Mapped[Optional["ManualTreeGroupPreview"]] = relationship(
        back_populates="group",
        uselist=False,
        cascade="all, delete-orphan",
    )


class ManualTreeGroupPreview(Base):
    __tablename__ = "manual_tree_group_previews"

    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    group_id: Mapped[UUID] = mapped_column(ForeignKey("manual_tree_groups.id", ondelete="CASCADE"), unique=True, index=True)
    status: Mapped[str] = mapped_column(String(30), default="READY", index=True)
    source_batch_id: Mapped[Optional[str]] = mapped_column(String(64))
    payload_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    articles_json: Mapped[Optional[List[Dict[str, Any]]]] = mapped_column(JSON)
    summary: Mapped[Optional[str]] = mapped_column(Text)
    preview_json: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    accepted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    group: Mapped["ManualTreeGroup"] = relationship(back_populates="preview")
