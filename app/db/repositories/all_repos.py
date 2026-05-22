from typing import List, Optional
from uuid import UUID
from sqlalchemy.orm import Session
from sqlalchemy import select, delete

from app.db.models import (
    SourceBatch, SourceFile, ContentCandidate, ExtractedDocument, 
    CanonicalContent, ValidationReport, WordPressExport, ProcessingEvent, ReprocessingRequest
)
from app.db.repositories.base import BaseRepository
from app.core.states import BatchStatus

class SourceBatchRepository(BaseRepository[SourceBatch]):
    def __init__(self):
        super().__init__(SourceBatch)

    def get_by_sha256(self, db: Session, sha256: str) -> Optional[SourceBatch]:
        return db.execute(select(self.model).where(self.model.batch_sha256 == sha256)).scalar_one_or_none()

    def list_by_status(self, db: Session, status: BatchStatus) -> List[SourceBatch]:
        return db.execute(select(self.model).where(self.model.status == status)).scalars().all()

    def get_by_municipality_and_category(self, db: Session, municipality: str, category: str) -> List[SourceBatch]:
        return db.execute(
            select(self.model).where(
                self.model.municipality_hint == municipality,
                self.model.category_hint == category,
            )
        ).scalars().all()

class SourceFileRepository(BaseRepository[SourceFile]):
    def __init__(self):
        super().__init__(SourceFile)

    def get_by_sha256(self, db: Session, sha256: str) -> Optional[SourceFile]:
        return db.execute(select(self.model).where(self.model.sha256 == sha256)).scalar_one_or_none()

    def get_by_batch_id(self, db: Session, batch_id: UUID) -> List[SourceFile]:
        return db.execute(select(self.model).where(self.model.batch_id == batch_id)).scalars().all()

    def delete_by_batch_id(self, db: Session, batch_id: UUID) -> int:
        result = db.execute(delete(self.model).where(self.model.batch_id == batch_id))
        db.commit()
        return result.rowcount

class ContentCandidateRepository(BaseRepository[ContentCandidate]):
    def __init__(self):
        super().__init__(ContentCandidate)

    def list_pending_review(self, db: Session) -> List[ContentCandidate]:
        return db.execute(select(self.model).where(self.model.requires_review == True)).scalars().all()

    def get_by_batch_id(self, db: Session, batch_id: UUID) -> List[ContentCandidate]:
        return db.execute(select(self.model).where(self.model.batch_id == batch_id)).scalars().all()

class ExtractedDocumentRepository(BaseRepository[ExtractedDocument]):
    def __init__(self):
        super().__init__(ExtractedDocument)

    def get_by_candidate_id(self, db: Session, candidate_id: UUID) -> List[ExtractedDocument]:
        return db.execute(select(self.model).where(self.model.candidate_id == candidate_id)).scalars().all()

class CanonicalContentRepository(BaseRepository[CanonicalContent]):
    def __init__(self):
        super().__init__(CanonicalContent)

    def get_by_candidate_id(self, db: Session, candidate_id: UUID) -> Optional[CanonicalContent]:
        return db.execute(select(self.model).where(self.model.candidate_id == candidate_id)).scalar_one_or_none()

    def delete_by_candidate_ids(self, db: Session, candidate_ids: List[UUID]) -> int:
        if not candidate_ids:
            return 0
        result = db.execute(delete(self.model).where(self.model.candidate_id.in_(candidate_ids)))
        db.commit()
        return result.rowcount

class ValidationReportRepository(BaseRepository[ValidationReport]):
    def __init__(self):
        super().__init__(ValidationReport)

class WordPressExportRepository(BaseRepository[WordPressExport]):
    def __init__(self):
        super().__init__(WordPressExport)

    def find_latest_export_for_candidate(self, db: Session, candidate_id: UUID) -> Optional[WordPressExport]:
        return db.execute(
            select(self.model)
            .where(self.model.candidate_id == candidate_id)
            .order_by(self.model.created_at.desc())
        ).scalars().first()

class ProcessingEventRepository(BaseRepository[ProcessingEvent]):
    def __init__(self):
        super().__init__(ProcessingEvent)

    def get_by_batch_id(self, db: Session, batch_id: UUID) -> List[ProcessingEvent]:
        return db.execute(
            select(self.model).where(self.model.batch_id == batch_id).order_by(self.model.created_at.desc())
        ).scalars().all()

class ReprocessingRequestRepository(BaseRepository[ReprocessingRequest]):
    def __init__(self):
        super().__init__(ReprocessingRequest)

source_batch_repo = SourceBatchRepository()
source_file_repo = SourceFileRepository()
content_candidate_repo = ContentCandidateRepository()
extracted_document_repo = ExtractedDocumentRepository()
canonical_content_repo = CanonicalContentRepository()
validation_report_repo = ValidationReportRepository()
wordpress_export_repo = WordPressExportRepository()
processing_event_repo = ProcessingEventRepository()
reprocessing_request_repo = ReprocessingRequestRepository()
