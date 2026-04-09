from typing import Optional, Dict, Any
from uuid import UUID
from sqlalchemy.orm import Session
from app.db.repositories.all_repos import source_batch_repo, content_candidate_repo, reprocessing_request_repo
from app.db.models import ReprocessingRequest
from app.core.states import ReprocessingStatus, BatchStatus, CandidateStatus
from app.core.enums import ReprocessingScope
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.config.settings import settings

class ReprocessingService:
    def __init__(self):
        self.pipeline = PipelineOrchestrator(settings)

    def request_reprocessing(self, db: Session, user: str, reason: str, 
                             batch_id: Optional[UUID] = None, 
                             candidate_id: Optional[UUID] = None,
                             scope: ReprocessingScope = ReprocessingScope.FULL_REBUILD) -> ReprocessingRequest:
        
        req = reprocessing_request_repo.create(db, obj_in={
            "requested_by": user,
            "reason": reason,
            "batch_id": batch_id,
            "candidate_id": candidate_id,
            "force_full_rebuild": scope == ReprocessingScope.FULL_REBUILD,
            "status": ReprocessingStatus.PENDING
        })
        
        return req

    def process_pending_requests(self, db: Session):
        # En una app real esto correría en un worker en background (Celery, RQ, o BackgroundTasks)
        # Para esta demo, ejecutamos sincrónicamente para el panel
        pass
        
    def reprocess_candidate_sync(self, db: Session, candidate_id: UUID) -> bool:
        """
        Para el panel: reprocesamiento simplificado sincrónico.
        En V1 borramos el candidato y lo volvemos a pasar por el pipeline desde el batch.
        """
        candidate = content_candidate_repo.get_by_id(db, candidate_id)
        if not candidate:
            return False
            
        batch = candidate.batch
        
        # Eliminar el candidato actual (las cascadas borrarán el resto)
        content_candidate_repo.delete(db, id=candidate_id)
        
        # Reprocesar todo el batch
        self.pipeline.process_new_batch(batch.original_path)
        
        return True
