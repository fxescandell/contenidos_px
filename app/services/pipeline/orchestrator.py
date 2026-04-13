import time
from typing import Dict, Any, List
from sqlalchemy.orm import Session
from app.db.session import SessionLocal
from app.db.repositories.all_repos import (
    source_batch_repo, source_file_repo, content_candidate_repo, canonical_content_repo, processing_event_repo
)
from app.db.models import (
    SourceBatch, SourceFile, ContentCandidate, CanonicalContent
)
from app.core.states import BatchStatus, CandidateStatus
from app.core.enums import EventLevel

from app.services.ingestion.service import IngestionService
from app.services.grouping.orchestrator import GroupingOrchestrator
from app.services.extraction.orchestrator import ExtractionOrchestrator
from app.services.classification.orchestrator import ClassificationOrchestrator
from app.services.editorial.builder import EditorialBuilderService
from app.services.images.processor import ImageProcessingService
from app.adapters.factory import AdapterFactory
from app.services.export.builder import WordPressJsonExportBuilder
from app.services.pipeline.events import event_logger
from app.services.settings.service import SettingsResolver
from app.services.working_directory_cleanup import working_directory_cleanup_service

class PipelineOrchestrator:
    def __init__(self, config):
        self.config = config
        working_dir = SettingsResolver.get("working_folder_path") or config.WORKING_DIRECTORY
        export_dir = SettingsResolver.get("export_output_path") or config.EXPORT_DIRECTORY
        self.ingestion_service = IngestionService(working_dir)
        self.grouping_orchestrator = GroupingOrchestrator()
        self.extraction_orchestrator = ExtractionOrchestrator()
        self.classification_orchestrator = ClassificationOrchestrator()
        self.editorial_builder = EditorialBuilderService()
        self.image_processor = ImageProcessingService(export_dir)
        self.export_builder = WordPressJsonExportBuilder()
        self.working_cleanup_service = working_directory_cleanup_service

    def process_new_batch(self, source_path: str):
        db = SessionLocal()
        batch_id = None
        try:
            # 1. Ingestion
            ingestion_data = self.ingestion_service.ingest_batch(source_path)
            
            # Check if duplicate
            existing = source_batch_repo.get_by_sha256(db, ingestion_data["batch_sha256"])
            if existing:
                event_logger.log(db, EventLevel.WARNING, "BATCH_DUPLICATE", "INGESTION", "Batch already processed", batch_id=existing.id)
                return
            
            # Save batch to DB
            batch = source_batch_repo.create(db, obj_in={
                "external_name": ingestion_data["external_name"],
                "original_path": ingestion_data["original_path"],
                "working_path": ingestion_data["working_path"],
                "batch_sha256": ingestion_data["batch_sha256"],
                "status": BatchStatus.DETECTED
            })
            batch_id = batch.id
            
            # Save files to DB
            files = []
            for file_data in ingestion_data["files"]:
                file_data["batch_id"] = batch.id
                files.append(source_file_repo.create(db, obj_in=file_data))
                
            event_logger.log(db, EventLevel.INFO, "BATCH_INGESTED", "INGESTION", "Batch ingested successfully", batch_id=batch.id)
            
            # Update status
            source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.PROCESSING})

            # 2. Grouping
            groups = self.grouping_orchestrator.group_batch(batch, files)
            for group in groups:
                # 3. Create Candidate
                candidate = content_candidate_repo.create(db, obj_in={
                    "batch_id": batch.id,
                    "candidate_key": group.candidate_key,
                    "grouping_strategy": group.strategy,
                    "grouping_confidence": group.confidence,
                    "status": CandidateStatus.CREATED
                })
                
                # Assign files
                assigned_files = [f for f in files if f.id in [a["id"] for a in group.assigned_files]]
                docs = [f for f in assigned_files if f.extension in [".pdf", ".docx"]]
                imgs = [f for f in assigned_files if f.extension in [".jpg", ".jpeg", ".png"]]
                
                # 4. Extraction
                extractions = self.extraction_orchestrator.process_files(
                    [{"id": f.id, "path": f.working_path} for f in docs + imgs]
                )
                
                # 5. Classification
                hints = {
                    "municipality_hint": batch.municipality_hint or "",
                    "category_hint": batch.category_hint or ""
                }
                classification = self.classification_orchestrator.classify_candidate(group, extractions, hints)
                
                # 6. Images
                processed_images = self.image_processor.process_images(candidate, imgs)
                
                # 7. Editorial
                combined_text = "\n".join([e.cleaned_text for e in extractions if str(e.cleaned_text or "").strip()])
                editorial = self.editorial_builder.build_editorial_content(
                    classification,
                    combined_text,
                    processed_images,
                    {"featured_selection_images": processed_images},
                )
                
                # Update candidate with featured image
                if editorial.featured_image_ref:
                    try:
                        content_candidate_repo.update(db, db_obj=candidate, obj_in={"featured_source_file_id": editorial.featured_image_ref})
                    except Exception:
                        db.rollback()
                
                # 8. Create Canonical
                canonical = canonical_content_repo.create(db, obj_in={
                    "candidate_id": candidate.id,
                    "municipality": classification.municipality,
                    "category": classification.category,
                    "subtype": classification.subtype,
                    "final_title": editorial.final_title,
                    "final_summary": editorial.final_summary,
                    "final_body_html": editorial.final_body_html,
                    "structured_fields_json": editorial.structured_fields,
                    "requires_review": classification.requires_review,
                    "review_reasons_json": classification.review_reasons
                })
                
                # 9. Adapter & Validation
                adapter = AdapterFactory.get_adapter(classification.category)
                adapter_result = adapter.build_payload(canonical)
                
                if not adapter_result.is_ready_for_export:
                    canonical_content_repo.update(db, db_obj=canonical, obj_in={"requires_review": True})
                    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": CandidateStatus.REVIEW_REQUIRED})
                    event_logger.log(db, EventLevel.WARNING, "CANDIDATE_REVIEW_REQUIRED", "VALIDATION", "Validation failed", candidate_id=candidate.id)
                    continue

                # 10. Export
                export_result = self.export_builder.build_export(adapter_result)
                if export_result.status == "WRITTEN":
                    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": CandidateStatus.EXPORTED})
                    event_logger.log(db, EventLevel.INFO, "CANDIDATE_EXPORTED", "EXPORT", "Candidate exported successfully", candidate_id=candidate.id)
                else:
                    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": CandidateStatus.FAILED})
                    event_logger.log(db, EventLevel.ERROR, "CANDIDATE_EXPORT_FAILED", "EXPORT", "Failed to write export", candidate_id=candidate.id)

            # Update batch status
            all_candidates = batch.candidates
            if any(c.status == CandidateStatus.REVIEW_REQUIRED for c in all_candidates):
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.REVIEW_REQUIRED})
            elif any(c.status == CandidateStatus.FAILED for c in all_candidates):
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED})
            else:
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FINISHED})
                self.working_cleanup_service.cleanup_batch(batch)

        except Exception as e:
            if batch_id:
                batch = source_batch_repo.get_by_id(db, batch_id)
                if batch:
                    source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED, "error_message": str(e)})
            event_logger.log(db, EventLevel.CRITICAL, "PIPELINE_ERROR", "PIPELINE", str(e), batch_id=batch_id)
        finally:
            db.close()
