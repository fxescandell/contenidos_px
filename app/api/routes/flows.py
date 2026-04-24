import os
import shutil
from typing import List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Body
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.repositories.flow_repos import flow_repo
from app.db.models import ProcessingEvent, SourceBatch
from app.db.repositories.all_repos import source_batch_repo
from app.schemas.flows import FlowCreate, FlowUpdate, FlowResponse, FlowRunRequest
from app.config.settings import settings
from app.services.pipeline.flow_service import FlowService
from app.services.pipeline.events import event_logger
from app.services.path_filters import is_ignored_source_folder
from app.services.export.flow_export import FlowExporter
from app.services.settings.service import SettingsResolver
from app.services.manual_flow import ManualFlowService
from app.services.manual_tree import ManualTreeService
from app.services.workspace.preprocess_service import preprocess_workspace_service
from app.services.workspace.final_review_service import final_review_workspace_service
from app.core.settings_enums import SettingType
from app.core.enums import EventLevel
from app.core.states import BatchStatus

router = APIRouter(prefix="/api/v1/flows", tags=["flows"])
manual_flow_service = ManualFlowService()
manual_tree_service = ManualTreeService()

MUNICIPALITIES = ["BERGUEDA", "CERDANYA", "MARESME"]
CATEGORIES = ["AGENDA", "NOTICIES", "ESPORTS", "TURISME_ACTIU", "NENS_I_JOVES", "CULTURA", "GASTRONOMIA", "CONSELLS", "ENTREVISTES"]
FLOW_PREVIEW_EXTENSIONS = ('.pdf', '.docx', '.md', '.markdown', '.txt', '.jpg', '.jpeg', '.png')


def _serialize_processing_event(event: ProcessingEvent) -> dict:
    return {
        "id": str(event.id),
        "level": event.level.value if event.level else "INFO",
        "event_type": event.event_type,
        "stage": event.stage,
        "message": event.message,
        "payload": event.payload_json or {},
        "batch_id": str(event.batch_id) if event.batch_id else None,
        "candidate_id": str(event.candidate_id) if event.candidate_id else None,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


def _serialize_batch_activity(batch) -> dict:
    return {
        "id": str(batch.id),
        "external_name": batch.external_name,
        "status": batch.status.value if batch.status else "UNKNOWN",
        "requires_review": batch.requires_review,
        "review_reason": batch.review_reason,
        "error_message": batch.error_message,
        "created_at": batch.created_at.isoformat() if batch.created_at else None,
        "started_at": batch.started_at.isoformat() if batch.started_at else None,
        "finished_at": batch.finished_at.isoformat() if batch.finished_at else None,
        "updated_at": batch.updated_at.isoformat() if batch.updated_at else None,
    }


def _datetime_to_timestamp(value: Optional[datetime]) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo).timestamp()
    return value.timestamp()


def _safe_cleanup_children(
    root_path: str,
    protected_paths: List[str],
    dry_run: bool = False,
    include_children: Optional[List[str]] = None,
    target_full_paths: Optional[List[str]] = None,
) -> dict:
    root = os.path.abspath(root_path or "")
    if not root or not os.path.isdir(root):
        return {"root": root_path, "planned": 0, "removed": 0, "skipped": 0, "errors": [], "items": []}

    protected = [os.path.abspath(path) for path in protected_paths if path]
    target_paths = {os.path.abspath(path) for path in (target_full_paths or []) if path}
    has_target_filter = bool(target_paths)
    allowed_names = {item for item in (include_children or []) if item}
    only_allowed = bool(allowed_names)
    planned = 0
    removed = 0
    skipped = 0
    errors: List[str] = []
    items: List[str] = []

    for entry in os.listdir(root):
        if only_allowed and entry not in allowed_names:
            skipped += 1
            continue

        full = os.path.abspath(os.path.join(root, entry))
        if not full.startswith(root + os.sep):
            skipped += 1
            continue

        if has_target_filter and full not in target_paths:
            skipped += 1
            continue

        if any(p == full or p.startswith(full + os.sep) for p in protected):
            skipped += 1
            continue

        planned += 1
        if len(items) < 80:
            items.append(full)

        if dry_run:
            continue

        try:
            if os.path.isdir(full):
                shutil.rmtree(full, ignore_errors=False)
            else:
                os.remove(full)
            removed += 1
        except Exception as exc:
            errors.append(f"{full}: {exc}")

    return {
        "root": root,
        "planned": planned,
        "removed": removed,
        "skipped": skipped,
        "errors": errors,
        "items": items,
    }

@router.get("", response_model=List[FlowResponse])
def list_flows(db: Session = Depends(get_db)):
    return flow_repo.get_all_ordered(db)

@router.get("/municipalities")
def get_municipalities():
    return MUNICIPALITIES

@router.get("/categories")
def get_categories():
    return CATEGORIES

@router.post("/switch-mode")
def switch_mode(mode: str = Query(...), db: Session = Depends(get_db)):
    if mode not in ("smb", "local"):
        raise HTTPException(status_code=400, detail="Modo debe ser 'smb' o 'local'")
    from app.services.settings.service import SettingsService
    from app.schemas.settings import SettingItemUpdate
    SettingsService.update_section(db, "general", [SettingItemUpdate(key="active_source_mode", value=mode, value_type=SettingType.STRING)])
    SettingsResolver.reload(db)
    return {"success": True, "mode": mode}

@router.get("/active-mode")
def get_active_mode(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return {"mode": SettingsResolver.get("active_source_mode", "smb") or "smb"}

@router.get("/hotfolder-info")
def get_hotfolder_info(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    smb_host = SettingsResolver.get("remote_inbox_host", "")
    smb_share = SettingsResolver.get("smb_share_name", "")
    smb_base = SettingsResolver.get("remote_inbox_base_path", "/") or "/"
    local_base = SettingsResolver.get("hot_folder_local_path") or "/tmp/hot_folder"
    smb_path = ""
    if smb_host and smb_share:
        smb_path = f"//{smb_host}/{smb_share}{smb_base}"
    return {
        "smb_path": smb_path,
        "smb_host": smb_host,
        "smb_share": smb_share,
        "local_path": local_base,
        "smb_configured": bool(smb_host and smb_share),
        "local_configured": bool(local_base)
    }

@router.get("/browse-folders")
def browse_folders(mode: str = Query("smb"), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    folders = []

    if mode == "smb":
        try:
            from app.services.remote.clients import SmbRemoteInboxClient
            client = SmbRemoteInboxClient()
            cfg = client._get_config()
            if not cfg["host"] or not cfg["share"]:
                return {"success": False, "message": "SMB no configurado (falta host o share)", "folders": []}
            ok, msg, entries = client.list_subfolders("")
            if not ok:
                return {"success": False, "message": msg, "folders": []}
            folders = [e["name"] for e in entries if e.get("is_dir") and not e["name"].startswith(".") and not is_ignored_source_folder(e["name"])]

            municipality_folders = []
            for folder in folders:
                sub_ok, sub_msg, sub_entries = client.list_subfolders(folder)
                if sub_ok and sub_entries:
                    sub_dirs = [s["name"] for s in sub_entries if s.get("is_dir") and not s["name"].startswith(".") and not is_ignored_source_folder(s["name"])]
                    if sub_dirs:
                        municipality_folders.append({
                            "name": folder,
                            "type": "municipality",
                            "subfolders": sub_dirs
                        })
                    else:
                        municipality_folders.append({
                            "name": folder,
                            "type": "folder",
                            "subfolders": []
                        })
            return {"success": True, "folders": municipality_folders}
        except Exception as e:
            return {"success": False, "message": str(e), "folders": []}
    else:
        local_base = SettingsResolver.get("hot_folder_local_path", "/tmp/hot_folder")
        if not os.path.exists(local_base):
            return {"success": False, "message": f"Ruta local no existe: {local_base}", "folders": []}
        try:
            entries = os.listdir(local_base)
            for entry in sorted(entries):
                full = os.path.join(local_base, entry)
                if os.path.isdir(full) and not entry.startswith(".") and not is_ignored_source_folder(entry):
                    sub_dirs = []
                    try:
                        sub_entries = os.listdir(full)
                        sub_dirs = sorted([s for s in sub_entries if os.path.isdir(os.path.join(full, s)) and not s.startswith(".") and not is_ignored_source_folder(s)])
                    except Exception:
                        pass
                    if sub_dirs:
                        folders.append({"name": entry, "type": "municipality", "subfolders": sub_dirs})
                    else:
                        folders.append({"name": entry, "type": "folder", "subfolders": []})
            return {"success": True, "folders": folders}
        except Exception as e:
            return {"success": False, "message": str(e), "folders": []}

@router.post("", response_model=FlowResponse)
def create_flow(flow_in: FlowCreate, db: Session = Depends(get_db)):
    return flow_repo.create(db, obj_in=flow_in.model_dump())


@router.get("/manual/inbox/groups")
def get_manual_tree_groups(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return manual_tree_service.get_groups_state(db)


@router.get("/manual/inbox/ai-health")
def check_manual_inbox_ai_health(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return manual_tree_service.check_ai_connection()


@router.post("/workspace/preprocess/sessions")
def create_preprocess_session(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    state = preprocess_workspace_service.create_session()
    return {"success": True, "session": state}


@router.get("/workspace/preprocess/sessions/{session_id}")
def get_preprocess_session(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        state = preprocess_workspace_service.get_state(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "session": state}


@router.post("/workspace/preprocess/sessions/{session_id}/upload")
async def upload_preprocess_files(
    session_id: str,
    files: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
):
    SettingsResolver.reload(db)
    if not files:
        raise HTTPException(status_code=400, detail="No se han recibido archivos")
    try:
        result = preprocess_workspace_service.upload_files(session_id, files)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/workspace/preprocess/sessions/{session_id}/analyze")
def analyze_preprocess_session(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        return preprocess_workspace_service.analyze(session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/preprocess/sessions/{session_id}/generate-md")
def generate_preprocess_markdown(session_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    municipality = str(payload.get("municipality", "") or "")
    category = str(payload.get("category", "") or "")
    flow_id = str(payload.get("flow_id", "") or "")
    enable_web = bool(payload.get("enable_web_enrichment", False))
    web_query = str(payload.get("web_query", "") or "")
    try:
        return preprocess_workspace_service.generate_markdown(
            session_id=session_id,
            municipality=municipality,
            category=category,
            flow_id=flow_id,
            enable_web_enrichment=enable_web,
            web_query=web_query,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/preprocess/sessions/{session_id}/package")
def package_preprocess_session(session_id: str, payload: Optional[dict] = Body(None), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    payload = payload or {}
    folder_name = str(payload.get("article_folder_name", "") or "")
    try:
        return preprocess_workspace_service.package_article(session_id, article_folder_name=folder_name)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/preprocess/sessions/{session_id}/publish")
def publish_preprocess_session(session_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    flow_id_raw = payload.get("flow_id")
    if not flow_id_raw:
        raise HTTPException(status_code=400, detail="Debes indicar flow_id")

    try:
        flow_id = UUID(str(flow_id_raw))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"flow_id invalido: {exc}")

    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    try:
        return preprocess_workspace_service.publish_to_flow_input(session_id, flow)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions")
def create_final_review_session(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    state = final_review_workspace_service.create_session()
    return {"success": True, "session": state}


@router.get("/workspace/final-review/sessions/{session_id}")
def get_final_review_session(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        state = final_review_workspace_service.get_state(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return {"success": True, "session": state}


@router.post("/workspace/final-review/sessions/{session_id}/load-export")
async def load_final_review_export(session_id: str, file: UploadFile = File(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        return final_review_workspace_service.load_export_file(session_id, file)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/run-checks")
def run_final_review_checks(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        return final_review_workspace_service.run_checks(session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/workspace/final-review/sessions/{session_id}/articles")
def list_final_review_articles(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        items = final_review_workspace_service.list_articles(session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"success": True, "articles": items}


@router.put("/workspace/final-review/sessions/{session_id}/articles/{article_id}")
def update_final_review_article(session_id: str, article_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        return final_review_workspace_service.update_article(session_id, article_id, payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/articles/{article_id}/ai-adjust")
def ai_adjust_final_review_article(session_id: str, article_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    instructions = str(payload.get("instructions", "") or "")
    try:
        return final_review_workspace_service.ai_adjust_article(session_id, article_id, instructions)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/export-reviewed")
def export_final_reviewed(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        return final_review_workspace_service.export_reviewed(session_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/manual/maintenance/cleanup")
def cleanup_manual_temp_and_working(payload: Optional[dict] = Body(None), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    payload = payload or {}

    mode = str(payload.get("mode", "soft") or "soft").strip().lower()
    dry_run = bool(payload.get("dry_run", False))
    retry_targets_raw = payload.get("retry_targets") if isinstance(payload.get("retry_targets"), dict) else {}
    retry_working_targets = [str(path) for path in (retry_targets_raw.get("working") or []) if path]
    retry_temp_targets = [str(path) for path in (retry_targets_raw.get("temp") or []) if path]
    if mode not in {"soft", "full"}:
        raise HTTPException(status_code=400, detail="Modo de limpieza invalido. Usa 'soft' o 'full'.")

    active_statuses = {
        BatchStatus.DETECTED,
        BatchStatus.COPYING,
        BatchStatus.COPIED,
        BatchStatus.SCANNED,
        BatchStatus.GROUPED,
        BatchStatus.PROCESSING,
    }
    active_batches = (
        db.query(SourceBatch)
        .filter(SourceBatch.status.in_(list(active_statuses)))
        .all()
    )
    if active_batches and not dry_run:
        return {
            "success": False,
            "message": f"Hay {len(active_batches)} lote(s) activos. Espera a que terminen antes de limpiar temporales.",
        }

    working_root = SettingsResolver.get("working_folder_path") or "/tmp/editorial_working"
    temp_root = SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp"

    working_in_use = [
        str(getattr(batch, "working_path", "") or "")
        for batch in db.query(SourceBatch).all()
        if getattr(batch, "working_path", None)
    ]

    if mode == "soft":
        working_result = {
            "root": os.path.abspath(working_root),
            "planned": 0,
            "removed": 0,
            "skipped": 0,
            "errors": [],
            "items": [],
            "note": "No se limpia working en modo soft",
        }
        temp_result = _safe_cleanup_children(
            temp_root,
            protected_paths=working_in_use,
            dry_run=dry_run,
            include_children=["manual_flow_drafts", "manual_tree_uploads"],
            target_full_paths=retry_temp_targets,
        )
    else:
        working_result = _safe_cleanup_children(
            working_root,
            protected_paths=[],
            dry_run=dry_run,
            target_full_paths=retry_working_targets,
        )
        temp_result = _safe_cleanup_children(
            temp_root,
            protected_paths=working_in_use,
            dry_run=dry_run,
            target_full_paths=retry_temp_targets,
        )

    total_planned = int(working_result.get("planned", 0)) + int(temp_result.get("planned", 0))
    total_removed = int(working_result.get("removed", 0)) + int(temp_result.get("removed", 0))
    total_errors = len(working_result.get("errors", [])) + len(temp_result.get("errors", []))

    return {
        "success": total_errors == 0,
        "mode": mode,
        "dry_run": dry_run,
        "message": (
            "Previsualizacion de limpieza lista" if dry_run else ("Limpieza completada" if total_errors == 0 else "Limpieza completada con incidencias")
        ),
        "planned": total_planned,
        "removed": total_removed,
        "active_batches": len(active_batches),
        "details": {
            "working": working_result,
            "temp": temp_result,
        },
    }


@router.post("/manual/inbox/upload-tree")
async def upload_manual_tree(
    files: List[UploadFile] = File(...),
    relative_paths: List[str] = Form(...),
    db: Session = Depends(get_db),
):
    SettingsResolver.reload(db)
    result = await manual_tree_service.upload_tree(db, files, relative_paths)
    return result


@router.post("/manual/inbox/groups/assign")
def assign_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
        flow_id = UUID(payload.get("flow_id", ""))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    SettingsResolver.reload(db)
    return manual_tree_service.assign_groups(db, group_ids, flow_id)


@router.post("/manual/inbox/groups/auto-assign")
def auto_assign_manual_tree_groups(
    only_unassigned: bool = Query(True),
    db: Session = Depends(get_db),
):
    SettingsResolver.reload(db)
    return manual_tree_service.auto_assign_groups(db, only_unassigned=only_unassigned)


@router.post("/manual/inbox/groups/preview")
def preview_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para previsualizar")

    SettingsResolver.reload(db)
    return manual_tree_service.preview_groups(db, group_ids)


@router.post("/manual/inbox/groups/accept")
def accept_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para aceptar")

    SettingsResolver.reload(db)
    return manual_tree_service.accept_groups(db, group_ids)


@router.post("/manual/inbox/groups/finalize-export")
def finalize_manual_tree_groups_export(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para exportar")

    SettingsResolver.reload(db)
    return manual_tree_service.finalize_selected_exports(db, group_ids)


@router.get("/manual/inbox/groups/{group_id}/preview")
def get_manual_tree_group_preview(group_id: UUID, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return manual_tree_service.get_group_preview(db, group_id)


@router.put("/manual/inbox/groups/{group_id}/preview-json")
def update_manual_tree_group_preview_json(group_id: UUID, payload: dict = Body(...), db: Session = Depends(get_db)):
    preview_json = str(payload.get("preview_json", "") or "")
    SettingsResolver.reload(db)
    return manual_tree_service.update_group_preview_json(db, group_id, preview_json)


@router.post("/manual/inbox/groups/{group_id}/recompile")
def recompile_manual_tree_group_preview(group_id: UUID, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return manual_tree_service.recompile_group_preview(db, group_id)


@router.post("/manual/inbox/groups/{group_id}/ai-adjust")
def ai_adjust_manual_tree_group_preview(group_id: UUID, payload: dict = Body(...), db: Session = Depends(get_db)):
    instructions = str(payload.get("instructions", "") or "")
    SettingsResolver.reload(db)
    return manual_tree_service.apply_ai_changes_to_preview(db, group_id, instructions)


@router.delete("/manual/inbox/groups")
def delete_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para borrar")

    SettingsResolver.reload(db)
    return manual_tree_service.delete_groups(db, group_ids)


@router.post("/manual/inbox/groups/delete")
def delete_manual_tree_groups_post(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para borrar")

    SettingsResolver.reload(db)
    return manual_tree_service.delete_groups(db, group_ids)

@router.get("/{flow_id}", response_model=FlowResponse)
def get_flow(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    return flow

@router.put("/{flow_id}", response_model=FlowResponse)
def update_flow(flow_id: UUID, flow_in: FlowUpdate, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    update_data = flow_in.model_dump(exclude_unset=True)
    return flow_repo.update(db, db_obj=flow, obj_in=update_data)

@router.delete("/{flow_id}")
def delete_flow(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    flow_repo.delete(db, id=flow.id)
    return {"message": "Flow eliminado"}

@router.post("/{flow_id}/run")
def run_flow(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    if not flow.enabled:
        raise HTTPException(status_code=400, detail="Flow desactivado")

    SettingsResolver.reload(db)
    flow_service = FlowService(settings)
    result = flow_service.run_flow(flow)

    if result.get("success"):
        flow_repo.update(db, db_obj=flow, obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "OK",
            "last_run_summary": result.get("message", "")
        })
    else:
        flow_repo.update(db, db_obj=flow, obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "ERROR",
            "last_run_summary": result.get("message", "")[:255]
        })

    return result


@router.get("/{flow_id}/manual/state")
def get_manual_state(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    SettingsResolver.reload(db)
    state = manual_flow_service.get_draft_state(db, flow)
    return {"success": True, **state}


@router.post("/{flow_id}/manual/upload")
async def upload_manual_files(flow_id: UUID, files: List[UploadFile] = File(...), db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    if not files:
        raise HTTPException(status_code=400, detail="No se han recibido archivos")

    SettingsResolver.reload(db)
    result = await manual_flow_service.upload_files(db, flow, files)
    return {
        "success": True,
        "message": f"{len(result.get('saved', []))} archivo(s) cargado(s)",
        **result,
    }


@router.post("/{flow_id}/manual/preview")
def run_manual_preview(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    if not flow.enabled:
        raise HTTPException(status_code=400, detail="Flow desactivado")

    SettingsResolver.reload(db)
    result = manual_flow_service.run_preview(db, flow)
    return result


@router.get("/{flow_id}/manual/preview-current")
def get_manual_preview_current(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    return manual_flow_service.get_pending_preview(db, flow)


@router.post("/{flow_id}/manual/accept")
def accept_manual_preview(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    result = manual_flow_service.accept_pending_preview(db, flow)
    return result


@router.post("/{flow_id}/manual/discard")
def discard_manual_preview(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    result = manual_flow_service.discard_pending_preview(db, flow)
    return result


@router.post("/{flow_id}/manual/finalize-export")
def finalize_manual_export(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    result = manual_flow_service.finalize_export(db, flow)

    flow_repo.update(
        db,
        db_obj=flow,
        obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "EXPORTED" if result.get("success") else "ERROR",
            "last_run_summary": str(result.get("message", ""))[:255],
        },
    )
    return result


@router.post("/{flow_id}/manual/reset")
def reset_manual_draft(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    return manual_flow_service.reset_draft(db, flow)


@router.get("/batches/{batch_id}/events")
def get_batch_events(batch_id: UUID, limit: int = Query(200, ge=1, le=500), db: Session = Depends(get_db)):
    batch = source_batch_repo.get_by_id(db, batch_id)
    if not batch:
        raise HTTPException(status_code=404, detail="Lote no encontrado")

    events = (
        db.query(ProcessingEvent)
        .filter(ProcessingEvent.batch_id == batch_id)
        .order_by(ProcessingEvent.created_at.asc())
        .limit(limit)
        .all()
    )

    return {
        "success": True,
        "batch": _serialize_batch_activity(batch),
        "events": [_serialize_processing_event(event) for event in events],
    }


@router.get("/{flow_id}/activity")
def get_flow_activity(
    flow_id: UUID,
    started_after: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    parsed_started_after = None
    if started_after:
        try:
            parsed_started_after = datetime.fromisoformat(started_after.replace("Z", "+00:00"))
        except ValueError:
            parsed_started_after = None

    batches = source_batch_repo.get_all(db)
    matching_batches = [
        batch for batch in batches
        if (batch.municipality_hint or "").upper() == flow.municipality.upper()
        and (batch.category_hint or "").upper() == flow.category.upper()
    ]

    if parsed_started_after is not None:
        matching_batches = [
            batch for batch in matching_batches
            if batch.created_at and _datetime_to_timestamp(batch.created_at) >= _datetime_to_timestamp(parsed_started_after)
        ]

    if not matching_batches:
        return {"success": True, "batch": None, "events": []}

    latest_batch = sorted(
        matching_batches,
        key=lambda batch: _datetime_to_timestamp(batch.created_at),
        reverse=True,
    )[0]

    events = (
        db.query(ProcessingEvent)
        .filter(ProcessingEvent.batch_id == latest_batch.id)
        .order_by(ProcessingEvent.created_at.asc())
        .limit(limit)
        .all()
    )

    return {
        "success": True,
        "batch": _serialize_batch_activity(latest_batch),
        "events": [_serialize_processing_event(event) for event in events],
    }

@router.post("/{flow_id}/test-path")
def test_flow_path(flow_id: UUID, db: Session = Depends(get_db), keep: bool = Query(False)):
    import os
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    from app.services.pipeline.flow_service import FlowService
    flow_service = FlowService(settings)
    source_info = flow_service.resolve_source_info(flow)

    test_filename = "test_flow_connection.txt"
    test_content = f"Test de conexion - Flow: {flow.name}\nMunicipio: {flow.municipality}\nCategoria: {flow.category}\nFecha: {datetime.now().isoformat()}\nOK\n"
    suffix = "" if keep else " + borrado"

    if source_info["mode"] == "smb":
        try:
            from app.services.remote.clients import SmbRemoteInboxClient
            from smbclient import register_session, open_file, remove, reset_connection_cache, makedirs, listdir

            client = SmbRemoteInboxClient()
            cfg = source_info["smb_config"]
            unc = source_info["smb_source_unc"]
            unc_test = f"{unc}\\{test_filename}"
            unc_processed = f"{unc}\\processed\\{test_filename}"

            register_session(
                server=cfg["host"],
                username=client._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )

            results = []

            try:
                makedirs(unc, exist_ok=True)
            except Exception as e:
                reset_connection_cache()
                return {"success": False, "resolved_path": source_info["resolved_path"], "message": f"No se pudo acceder a la carpeta origen ({unc}): {e}"}

            try:
                with open_file(unc_test, mode="w") as f:
                    f.write(test_content)
                if not keep:
                    remove(unc_test)
                results.append(f"Origen ({unc}): escritura{suffix} OK")
            except Exception as e:
                reset_connection_cache()
                return {"success": False, "resolved_path": source_info["resolved_path"], "message": f"Error en carpeta origen ({unc}): {e}"}

            try:
                makedirs(f"{unc}\\processed", exist_ok=True)
                with open_file(unc_processed, mode="w") as f:
                    f.write(test_content)
                if not keep:
                    remove(unc_processed)
                results.append(f"Procesados ({unc}\\processed): escritura{suffix} OK")
            except Exception as e:
                results.append(f"Procesados: AVISO - {e}")

            files_in_folder = []
            try:
                entries = listdir(unc)
                files_in_folder = [str(e) for e in entries if not str(e).startswith(".") and str(e).lower().endswith(FLOW_PREVIEW_EXTENSIONS)]
            except Exception:
                pass

            reset_connection_cache()
            has_error = any("AVISO" in r or "FALLO" in r for r in results)
            return {
                "success": not has_error,
                "resolved_path": source_info["resolved_path"],
                "unc_path": unc,
                "message": " | ".join(results),
                "files_found": len(files_in_folder),
                "files": files_in_folder[:20],
                "kept": keep
            }
        except Exception as e:
            return {"success": False, "resolved_path": source_info["resolved_path"], "message": f"Error: {e}"}
    else:
        local_path = source_info["resolved_path"]
        results = []
        try:
            os.makedirs(local_path, exist_ok=True)
            test_file = os.path.join(local_path, test_filename)
            with open(test_file, "w") as f:
                f.write(test_content)
            if not keep:
                os.remove(test_file)
            results.append(f"Origen ({local_path}): escritura{suffix} OK")
        except Exception as e:
            return {"success": False, "resolved_path": local_path, "message": f"Error en carpeta origen ({local_path}): {e}"}

        proc_path = os.path.join(local_path, "processed")
        try:
            os.makedirs(proc_path, exist_ok=True)
            test_proc = os.path.join(proc_path, test_filename)
            with open(test_proc, "w") as f:
                f.write(test_content)
            if not keep:
                os.remove(test_proc)
            results.append(f"Procesados ({proc_path}): escritura{suffix} OK")
        except Exception as e:
            results.append(f"Procesados: AVISO - {e}")

        files_in_folder = []
        try:
            files_in_folder = [f for f in os.listdir(local_path) if not f.startswith(".") and f.lower().endswith(FLOW_PREVIEW_EXTENSIONS)]
        except Exception:
            pass

        has_error = any("AVISO" in r or "FALLO" in r for r in results)
        return {
            "success": not has_error,
            "resolved_path": local_path,
            "message": " | ".join(results),
            "files_found": len(files_in_folder),
            "files": files_in_folder[:20],
            "kept": keep
        }

@router.post("/{flow_id}/clear-last-batch")
def clear_last_batch(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    from app.db.repositories.all_repos import source_batch_repo, source_file_repo, content_candidate_repo, canonical_content_repo

    batches = source_batch_repo.get_all(db)
    matching = [b for b in batches if (b.municipality_hint or "").upper() == flow.municipality.upper() and (b.category_hint or "").upper() == flow.category.upper()]
    if not matching:
        return {"success": True, "message": "No hay lotes para este flujo"}
    deleted = 0
    for batch in matching:
        try:
            candidates = [c for c in content_candidate_repo.get_all(db) if c.batch_id == batch.id]
            for c in candidates:
                try:
                    canonical = canonical_content_repo.get_by_candidate_id(db, c.id)
                    if canonical:
                        canonical_content_repo.delete(db, id=canonical.id)
                except Exception:
                    pass
                content_candidate_repo.delete(db, id=c.id)
                deleted += 1
        except Exception:
            pass
        try:
            files = [f for f in source_file_repo.get_all(db) if f.batch_id == batch.id]
            for f in files:
                source_file_repo.delete(db, id=f.id)
                deleted += 1
        except Exception:
            pass
        try:
            source_batch_repo.delete(db, id=batch.id)
            deleted += 1
        except Exception:
            pass
    flow_repo.update(db, db_obj=flow, obj_in={"last_run_status": None, "last_run_at": None, "last_run_summary": None})
    return {"success": True, "message": f"{len(matching)} lote(s) eliminados ({deleted} registros borrados). Ya puedes volver a ejecutar el flujo."}

@router.post("/run-by-category")
def run_flow_by_category(req: FlowRunRequest, db: Session = Depends(get_db)):
    if req.municipality and req.category:
        flow = flow_repo.get_by_municipality_and_category(db, req.municipality, req.category)
    elif req.flow_id:
        flow = flow_repo.get_by_id(db, req.flow_id)
    else:
        raise HTTPException(status_code=400, detail="Especifica flow_id o municipio+categoria")

    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")
    if not flow.enabled:
        raise HTTPException(status_code=400, detail="Flow desactivado")

    SettingsResolver.reload(db)
    flow_service = FlowService(settings)
    result = flow_service.run_flow(flow)

    if result.get("success"):
        flow_repo.update(db, db_obj=flow, obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "OK",
            "last_run_summary": result.get("message", "")
        })
    else:
        flow_repo.update(db, db_obj=flow, obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "ERROR",
            "last_run_summary": result.get("message", "")[:255]
        })

    return result

@router.post("/{flow_id}/export")
def export_flow(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    try:
        SettingsResolver.reload(db)
        flow_service = FlowService(settings)
        result = flow_service.run_flow(flow)

        if not result.get("success"):
            return {"success": False, "message": f"Error en procesamiento: {result.get('message', '')}", "batch_id": result.get("batch_id")}

        batch_id = result.get("batch_id")
        batch_uuid = UUID(batch_id) if batch_id else None
        if batch_uuid:
            event_logger.log(db, EventLevel.INFO, "FLOW_EXPORT_STARTED", "EXPORT", "Iniciando exportacion del lote", batch_id=batch_uuid)

        exporter = FlowExporter()
        image_uploads = result.get("image_uploads", []) or []
        if image_uploads:
            if batch_uuid:
                event_logger.log(db, EventLevel.INFO, "IMAGE_UPLOAD_STARTED", "EXPORT", f"Subiendo {len(image_uploads)} imagen(es)", batch_id=batch_uuid)
            images_ok, images_msg, _uploaded = exporter.upload_image_assets(flow.municipality, image_uploads)
            if not images_ok:
                if batch_uuid:
                    event_logger.log(db, EventLevel.ERROR, "IMAGE_UPLOAD_FAILED", "EXPORT", images_msg, batch_id=batch_uuid)
                flow_repo.update(db, db_obj=flow, obj_in={
                    "last_run_at": datetime.now(),
                    "last_run_status": "ERROR",
                    "last_run_summary": f"{result.get('message', '')} | {images_msg}"[:255]
                })
                return {"success": False, "message": f"Error subiendo imagenes: {images_msg}", "batch_id": batch_id}
            if batch_uuid:
                event_logger.log(db, EventLevel.INFO, "IMAGE_UPLOAD_COMPLETED", "EXPORT", images_msg, batch_id=batch_uuid)

        json_content = flow_service.generate_json(flow, result.get("articles", []), result.get("export_payload"))
        csv_content = flow_service.generate_csv(flow, result.get("articles", []), result.get("export_payload"))
        if batch_uuid:
            event_logger.log(db, EventLevel.INFO, "EXPORT_FILES_BUILT", "EXPORT", "JSON y CSV generados en memoria", batch_id=batch_uuid)

        upload_ok, upload_msg = exporter.upload_to_outfolder(flow.municipality, flow.output_filename, json_content, content_label="JSON")
        if csv_content:
            csv_filename_base, _ext = os.path.splitext(flow.output_filename)
            csv_filename = f"{csv_filename_base}.csv" if csv_filename_base else f"{flow.output_filename}.csv"
            csv_ok, csv_msg = exporter.upload_to_outfolder(flow.municipality, csv_filename, csv_content, content_label="CSV")
            if not csv_ok:
                upload_ok = False
            upload_msg = f"{upload_msg} | {csv_msg}" if upload_msg else csv_msg

        flow_repo.update(db, db_obj=flow, obj_in={
            "last_run_at": datetime.now(),
            "last_run_status": "EXPORTED" if upload_ok else "ERROR",
            "last_run_summary": f"{result.get('message', '')} | {upload_msg}"
        })
        if batch_uuid:
            event_logger.log(
                db,
                EventLevel.INFO if upload_ok else EventLevel.ERROR,
                "FLOW_EXPORT_COMPLETED" if upload_ok else "FLOW_EXPORT_FAILED",
                "EXPORT",
                upload_msg,
                batch_id=batch_uuid,
            )

        return {
            "success": upload_ok,
            "message": result.get("message", ""),
            "upload": upload_msg,
            "articles_count": len(result.get("articles", [])),
            "classification": result.get("classification"),
            "batch_id": batch_id,
        }
    except Exception as e:
        try:
            flow_repo.update(db, db_obj=flow, obj_in={
                "last_run_at": datetime.now(),
                "last_run_status": "ERROR",
                "last_run_summary": str(e)[:255]
            })
        except Exception:
            pass
        return {"success": False, "message": f"Error interno exportando flujo: {e}"}
