from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import func
from uuid import UUID
from datetime import datetime
from pathlib import Path

from app.db.session import get_db
from app.db.repositories.all_repos import source_batch_repo, content_candidate_repo, processing_event_repo
from app.core.states import BatchStatus

router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


def _compute_workspace_assets_version() -> str:
    latest_mtime_ns = 0
    asset_roots = [
        (Path("app/static/js"), "*.js"),
        (Path("app/static/css"), "*.css"),
    ]
    for root, pattern in asset_roots:
        if not root.exists():
            continue
        for asset in root.rglob(pattern):
            try:
                latest_mtime_ns = max(latest_mtime_ns, asset.stat().st_mtime_ns)
            except OSError:
                continue

    if latest_mtime_ns <= 0:
        return datetime.utcnow().strftime("%Y%m%d%H%M%S")
    return str(latest_mtime_ns)


ACTIVE_STATUSES = [BatchStatus.DETECTED, BatchStatus.COPYING, BatchStatus.COPIED,
                    BatchStatus.SCANNED, BatchStatus.GROUPED, BatchStatus.PROCESSING]

WORKSPACE_PAGES = {
    "dashboard": "Dashboard",
    "manual-article": "Articulo manual",
    "manual-batches": "Lotes manuales",
    "preprocess": "Preprocesado",
    "final-review": "Revision final",
    "activity": "Actividad",
}


def _build_workspace_context(db: Session) -> dict:
    from app.services.settings.service import SettingsResolver, SettingsService

    SettingsResolver.reload(db)
    active_mode = SettingsResolver.get("active_source_mode", "smb") or "smb"

    all_batches = source_batch_repo.get_all(db, skip=0, limit=100)
    all_batches.sort(key=lambda x: x.created_at, reverse=True)

    stats = {
        "total": len(all_batches),
        "active": sum(1 for b in all_batches if b.status in ACTIVE_STATUSES),
        "finished": sum(1 for b in all_batches if b.status == BatchStatus.FINISHED),
        "failed": sum(1 for b in all_batches if b.status == BatchStatus.FAILED),
        "review": sum(1 for b in all_batches if b.status == BatchStatus.REVIEW_REQUIRED),
    }

    SettingsService.initialize_defaults(db)

    batches_data = []
    for b in all_batches:
        n_files = len(b.files) if b.files else 0
        n_candidates = len(b.candidates) if b.candidates else 0
        batches_data.append({
            "id": str(b.id),
            "external_name": b.external_name,
            "municipality": b.municipality_hint,
            "category": b.category_hint,
            "status": b.status.value if b.status else "UNKNOWN",
            "error_message": b.error_message,
            "review_reason": b.review_reason,
            "n_files": n_files,
            "n_candidates": n_candidates,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "finished_at": b.finished_at.isoformat() if b.finished_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        })

    municipalities = sorted(set(b["municipality"] for b in batches_data if b["municipality"]))

    return {
        "stats": stats,
        "batches": batches_data,
        "active_mode": active_mode,
        "municipalities": municipalities,
        "has_active": stats["active"] > 0,
        "workspace_assets_version": _compute_workspace_assets_version(),
    }


@router.get("/", response_class=HTMLResponse)
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    return RedirectResponse(url="/workspace/dashboard", status_code=302)


@router.get("/workspace/{page}", response_class=HTMLResponse)
def workspace_page(request: Request, page: str, db: Session = Depends(get_db)):
    if page == "configuration":
        return RedirectResponse(url="/settings", status_code=302)
    if page not in WORKSPACE_PAGES:
        return RedirectResponse(url="/workspace/dashboard", status_code=302)

    context = _build_workspace_context(db)
    context.update(
        {
            "workspace_page": page,
            "workspace_title": WORKSPACE_PAGES[page],
        }
    )
    return templates.TemplateResponse(request=request, name="index.html", context=context)


@router.get("/api/batches", response_class=JSONResponse)
def api_batches(request: Request, db: Session = Depends(get_db)):
    from app.services.settings.service import SettingsResolver
    SettingsResolver.reload(db)

    all_batches = source_batch_repo.get_all(db, skip=0, limit=100)
    all_batches.sort(key=lambda x: x.created_at, reverse=True)

    stats = {
        "total": len(all_batches),
        "active": sum(1 for b in all_batches if b.status in ACTIVE_STATUSES),
        "finished": sum(1 for b in all_batches if b.status == BatchStatus.FINISHED),
        "failed": sum(1 for b in all_batches if b.status == BatchStatus.FAILED),
        "review": sum(1 for b in all_batches if b.status == BatchStatus.REVIEW_REQUIRED),
    }

    batches_data = []
    for b in all_batches:
        n_files = len(b.files) if b.files else 0
        n_candidates = len(b.candidates) if b.candidates else 0
        batches_data.append({
            "id": str(b.id),
            "external_name": b.external_name,
            "municipality": getattr(b, "municipality_hint", None),
            "category": b.category_hint,
            "status": b.status.value if b.status else "UNKNOWN",
            "error_message": b.error_message,
            "review_reason": b.review_reason,
            "n_files": n_files,
            "n_candidates": n_candidates,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "finished_at": b.finished_at.isoformat() if b.finished_at else None,
            "updated_at": b.updated_at.isoformat() if b.updated_at else None,
        })

    return {
        "stats": stats,
        "batches": batches_data,
        "has_active": stats["active"] > 0,
    }


@router.delete("/api/batches/{batch_id}", response_class=JSONResponse)
def delete_batch(request: Request, batch_id: UUID, db: Session = Depends(get_db)):
    batch = source_batch_repo.get_by_id(db, batch_id)
    if not batch:
        return JSONResponse(status_code=404, content={"success": False, "message": "Lote no encontrado"})
    name = batch.external_name
    source_batch_repo.delete(db, id=batch_id)
    return {"success": True, "message": f"Lote '{name}' eliminado correctamente"}


@router.get("/batch/{batch_id}", response_class=HTMLResponse)
def batch_detail(request: Request, batch_id: UUID, db: Session = Depends(get_db)):
    batch = source_batch_repo.get_by_id(db, batch_id)
    if not batch:
        return RedirectResponse(url="/workspace/dashboard", status_code=302)

    events = processing_event_repo.get_all(db)
    batch_events = [e for e in events if e.batch_id == batch.id]
    batch_events.sort(key=lambda x: x.created_at, reverse=True)

    files_data = []
    for f in (batch.files or []):
        files_data.append({
            "id": str(f.id),
            "file_name": f.file_name,
            "extension": f.extension,
            "file_size_bytes": f.file_size_bytes,
            "file_role": f.file_role.value if f.file_role else "UNKNOWN",
            "relative_path": f.relative_path,
            "created_at": f.created_at.isoformat() if f.created_at else None,
        })

    candidates_data = []
    for c in (batch.candidates or []):
        has_canonical = c.canonical_content is not None
        canonical_data = None
        if has_canonical:
            cc = c.canonical_content
            canonical_data = {
                "municipality": cc.municipality.value if cc.municipality else None,
                "category": cc.category.value if cc.category else None,
                "subtype": cc.subtype.value if cc.subtype else None,
                "final_title": cc.final_title,
                "final_summary": cc.final_summary,
                "classification_confidence": cc.classification_confidence or 0,
                "editorial_confidence": cc.editorial_confidence or 0,
                "requires_review": cc.requires_review,
                "review_reasons": cc.review_reasons_json or [],
                "errors": cc.errors_json or [],
                "warnings": cc.warnings_json or [],
            }

        candidates_data.append({
            "id": str(c.id),
            "candidate_key": c.candidate_key,
            "grouping_strategy": c.grouping_strategy.value if c.grouping_strategy else None,
            "grouping_confidence": c.grouping_confidence,
            "status": c.status.value if c.status else "UNKNOWN",
            "requires_review": c.requires_review,
            "review_reason": c.review_reason,
            "municipality": c.municipality.value if c.municipality else None,
            "category": c.category.value if c.category else None,
            "title_hint": c.title_hint,
            "canonical": canonical_data,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "updated_at": c.updated_at.isoformat() if c.updated_at else None,
        })

    events_data = []
    for e in batch_events[:50]:
        events_data.append({
            "level": e.level.value if e.level else "INFO",
            "event_type": e.event_type,
            "stage": e.stage,
            "message": e.message,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })

    return templates.TemplateResponse(
        request=request,
        name="batch_detail.html",
        context={
            "batch": {
                "id": str(batch.id),
                "external_name": batch.external_name,
                "original_path": batch.original_path,
                "working_path": batch.working_path,
                "batch_sha256": batch.batch_sha256,
                "municipality": batch.municipality_hint,
                "category": batch.category_hint,
                "status": batch.status.value if batch.status else "UNKNOWN",
                "requires_review": batch.requires_review,
                "review_reason": batch.review_reason,
                "error_message": batch.error_message,
                "created_at": batch.created_at.isoformat() if batch.created_at else None,
                "detected_at": batch.detected_at.isoformat() if batch.detected_at else None,
                "started_at": batch.started_at.isoformat() if batch.started_at else None,
                "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
                "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
            },
            "files": files_data,
            "candidates": candidates_data,
            "events": events_data,
            "workspace_assets_version": _compute_workspace_assets_version(),
        }
    )


@router.get("/candidate/{candidate_id}", response_class=HTMLResponse)
def candidate_detail(request: Request, candidate_id: UUID, db: Session = Depends(get_db)):
    candidate = content_candidate_repo.get_by_id(db, candidate_id)
    canonical = candidate.canonical_content

    extracted_texts = []
    if candidate.batch:
        from app.db.repositories.all_repos import extracted_document_repo
        all_extractions = extracted_document_repo.get_all(db)
        extracted_texts = [e for e in all_extractions if e.candidate_id == candidate.id]

    return templates.TemplateResponse(
        request=request,
        name="candidate_detail.html",
        context={
            "candidate": candidate,
            "canonical": canonical,
            "extractions": extracted_texts,
            "workspace_assets_version": _compute_workspace_assets_version(),
        }
    )
