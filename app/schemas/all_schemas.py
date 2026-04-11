from typing import Optional, List, Dict, Any
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.enums import (
    Municipality, ContentCategory, ContentSubtype, ReviewReason,
    ValidationSeverity, CandidateGroupingStrategy, ExtractionMethod, ExportFormat
)
from app.core.states import BatchStatus, CandidateStatus, ExportStatus, ReprocessingStatus

# -----------------------
# Common & Base Schemas
# -----------------------

class CanonicalImageItem(BaseModel):
    id: UUID
    source_file_id: UUID
    role: str
    original_path: str
    optimized_path: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None

class CanonicalActivityItem(BaseModel):
    title: Optional[str] = None
    datetime_label: Optional[str] = None
    location: Optional[str] = None
    description: Optional[str] = None
    extra_info: Optional[str] = None
    image_ref: Optional[str] = None

class CanonicalBookData(BaseModel):
    book_title: Optional[str] = None
    book_author: Optional[str] = None
    edition_year: Optional[str] = None
    publisher: Optional[str] = None
    sponsor_name: Optional[str] = None
    sponsor_page: Optional[str] = None
    sample_pdf_available: bool = False
    sample_pdf_path: Optional[str] = None

class CanonicalRecipeData(BaseModel):
    gastronomy_type: str = "recipe"

class CanonicalContentItem(BaseModel):
    source_batch_id: UUID
    source_candidate_id: UUID
    
    municipality: Municipality
    category: ContentCategory
    subtype: ContentSubtype
    
    source_title: Optional[str] = None
    detected_title: Optional[str] = None
    final_title: Optional[str] = None
    
    source_summary: Optional[str] = None
    final_summary: Optional[str] = None
    
    source_body_text: Optional[str] = None
    final_body_html: Optional[str] = None
    
    language: Optional[str] = None
    featured_image_candidate_id: Optional[UUID] = None
    image_items: List[CanonicalImageItem] = Field(default_factory=list)
    structured_fields: Dict[str, Any] = Field(default_factory=dict)
    keyword_signals: List[str] = Field(default_factory=list)
    
    extraction_confidence: Optional[float] = None
    grouping_confidence: Optional[float] = None
    classification_confidence: Optional[float] = None
    editorial_confidence: Optional[float] = None
    
    requires_review: bool = False
    review_reasons: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    
    timestamps: Dict[str, datetime] = Field(default_factory=dict)

class ClassificationDecision(BaseModel):
    municipality: Municipality
    category: ContentCategory
    subtype: ContentSubtype
    confidence: float
    reasons: List[str] = Field(default_factory=list)

class ValidationIssue(BaseModel):
    severity: ValidationSeverity
    code: str
    message: str
    details: Dict[str, Any] = Field(default_factory=dict)

class ValidationResult(BaseModel):
    is_valid: bool
    requires_review: bool
    blocking_errors_count: int
    issues: List[ValidationIssue] = Field(default_factory=list)

class WordPressExportPayload(BaseModel):
    post_title: str
    post_content: str
    post_excerpt: Optional[str] = None
    post_status: str = "draft"
    post_date: Optional[str] = None
    featured_image_path: Optional[str] = None
    taxonomies: Dict[str, List[str]] = Field(default_factory=dict)
    meta_input: Dict[str, Any] = Field(default_factory=dict)

# -----------------------
# Operational Schemas
# -----------------------

class GroupingResult(BaseModel):
    candidate_key: str
    strategy: CandidateGroupingStrategy
    confidence: float
    assigned_files: List[Dict[str, Any]] # id, role, sort_order, confidence

class ExtractionResult(BaseModel):
    source_file_id: UUID
    method: ExtractionMethod
    confidence: float
    raw_text: str
    cleaned_text: str

class ImageProcessingResult(BaseModel):
    source_file_id: UUID
    optimized_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    width: int = 0
    height: int = 0
    original_format: Optional[str] = None
    optimized_format: Optional[str] = None
    optimized_file_size_bytes: Optional[int] = None
    role: str = "INLINE"

class EditorialBuildResult(BaseModel):
    source_title: Optional[str] = None
    detected_title: Optional[str] = None
    final_title: Optional[str] = None
    source_summary: Optional[str] = None
    final_summary: Optional[str] = None
    source_body_text: Optional[str] = None
    final_body_html: Optional[str] = None
    structured_fields: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    editorial_confidence: Optional[float] = None
    inserted_images: List[str] = Field(default_factory=list)
    featured_image_ref: Optional[UUID] = None

class AdapterBuildResult(BaseModel):
    canonical_id: UUID
    adapter_name: str
    payload: WordPressExportPayload
    raw_payload: Optional[Any] = None
    is_ready_for_export: bool
    validation_issues: List[ValidationIssue] = Field(default_factory=list)

class ExportBuildResult(BaseModel):
    export_id: UUID
    path: Optional[str] = None
    checksum: str
    status: ExportStatus
