from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from uuid import UUID

from app.db.session import get_db
from app.db.repositories.all_repos import source_batch_repo, content_candidate_repo, processing_event_repo

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")

@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    """
    Vista principal: Lotes recientes
    """
    batches = source_batch_repo.get_all(db, skip=0, limit=20)
    # Sort them descending manually for the view since the base get_all doesn't have order_by
    batches.sort(key=lambda x: x.created_at, reverse=True)
    
    return templates.TemplateResponse(
        request=request,
        name="index.html", 
        context={"batches": batches}
    )

@router.get("/batch/{batch_id}", response_class=HTMLResponse)
def batch_detail(request: Request, batch_id: UUID, db: Session = Depends(get_db)):
    """
    Vista de detalle de un lote con sus candidatos
    """
    batch = source_batch_repo.get_by_id(db, batch_id)
    return templates.TemplateResponse(
        request=request,
        name="batch_detail.html", 
        context={"batch": batch, "candidates": batch.candidates}
    )

@router.get("/candidate/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, candidate_id: UUID, db: Session = Depends(get_db)):
    """
    Vista de revisión de un candidato
    """
    candidate = content_candidate_repo.get_by_id(db, candidate_id)
    canonical = candidate.canonical_content
    
    # Textos extraídos para revisión
    extracted_texts = []
    if candidate.batch:
        # Recuperamos todas las extracciones asociadas
        from app.db.repositories.all_repos import extracted_document_repo
        # A workaround for the lack of relations set up in models for simplicity
        # Real code would have the relation: candidate.extracted_documents
        all_extractions = extracted_document_repo.get_all(db)
        extracted_texts = [e for e in all_extractions if e.candidate_id == candidate.id]
        
    return templates.TemplateResponse(
        request=request,
        name="candidate_detail.html", 
        context={
            "candidate": candidate, 
            "canonical": canonical,
            "extractions": extracted_texts
        }
    )
