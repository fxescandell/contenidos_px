from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.db.repositories.all_repos import source_batch_repo, content_candidate_repo, canonical_content_repo
from app.services.reprocessing.service import ReprocessingService
from app.services.pipeline.orchestrator import PipelineOrchestrator
from app.config.settings import settings
from app.services.notifications.telegram import notifier

router = APIRouter()
reprocessor = ReprocessingService()
pipeline = PipelineOrchestrator(settings)

@router.post("/process-manual")
def process_manual_batch(path: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    """
    Endpoint manual para procesar una carpeta sin esperar al Watcher
    """
    background_tasks.add_task(pipeline.process_new_batch, path)
    notifier.send_notification(f"Lanzado proceso manual para: {path}", "INFO")
    return {"message": f"Processing started for {path}"}

@router.post("/reprocess/{candidate_id}")
def reprocess_candidate(candidate_id: UUID, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    candidate = content_candidate_repo.get_by_id(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    notifier.send_notification(f"Reprocesando candidato: {candidate.candidate_key}", "WARNING")
    background_tasks.add_task(reprocessor.reprocess_candidate_sync, db, candidate_id)
    return {"message": "Reprocessing scheduled"}

@router.post("/approve/{candidate_id}")
def approve_candidate(candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Aprueba un candidato pendiente de revisión de forma manual.
    (En V1 simplemente actualizamos el estado, en una implementación real
    regeneraríamos el JSON).
    """
    candidate = content_candidate_repo.get_by_id(db, candidate_id)
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")
        
    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": "READY", "requires_review": False})
    
    if candidate.canonical_content:
        canonical_content_repo.update(db, db_obj=candidate.canonical_content, obj_in={"requires_review": False})
        
    notifier.send_notification(f"Candidato APROBADO manualmente: {candidate.candidate_key}", "SUCCESS")
    return {"message": "Candidate approved"}
