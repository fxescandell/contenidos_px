import os
import shutil
import json
import csv
import io
from typing import Any, Dict, List, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, Body
from fastapi.responses import FileResponse
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
        "module": _activity_module_from_stage(event.stage),
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


def _activity_module_from_stage(stage: Optional[str]) -> str:
    normalized = str(stage or "").strip().upper()
    if normalized.startswith("WORKSPACE_PREPROCESS"):
        return "preprocess"
    if normalized.startswith("WORKSPACE_FINAL_REVIEW"):
        return "final-review"
    if normalized.startswith("WORKSPACE_MANUAL"):
        return "manual"
    if normalized.startswith("WORKSPACE_SYSTEM"):
        return "system"
    return "flows"


def _log_workspace_event(
    db: Session,
    level: EventLevel,
    event_type: str,
    stage: str,
    message: str,
    payload: Optional[Dict[str, Any]] = None,
) -> None:
    event_logger.log(
        db,
        level,
        event_type,
        stage,
        message,
        payload=payload or {},
    )


def _collect_workspace_activity_rows(
    db: Session,
    module: str,
    level: str,
    q: str,
    limit: int,
) -> tuple[List[ProcessingEvent], Dict[str, int], int]:
    module_filter = (module or "all").strip().lower()
    level_filter = (level or "all").strip().upper()
    query_text = (q or "").strip().lower()

    base_fetch_limit = min(max(limit * 6, 400), 2500)
    rows = (
        db.query(ProcessingEvent)
        .order_by(ProcessingEvent.created_at.desc())
        .limit(base_fetch_limit)
        .all()
    )

    filtered: List[ProcessingEvent] = []
    module_counts: Dict[str, int] = {
        "flows": 0,
        "manual": 0,
        "preprocess": 0,
        "final-review": 0,
        "system": 0,
    }

    for row in rows:
        row_level = (row.level.value if row.level else "INFO").upper()
        if level_filter != "ALL" and row_level != level_filter:
            continue

        payload_text = ""
        if row.payload_json:
            try:
                payload_text = json.dumps(row.payload_json, ensure_ascii=False)
            except Exception:
                payload_text = str(row.payload_json)

        if query_text:
            haystack = " ".join(
                [
                    str(row.event_type or ""),
                    str(row.stage or ""),
                    str(row.message or ""),
                    payload_text,
                ]
            ).lower()
            if query_text not in haystack:
                continue

        module_name = _activity_module_from_stage(row.stage)
        module_counts[module_name] = module_counts.get(module_name, 0) + 1

        if module_filter != "all" and module_name != module_filter:
            continue
        filtered.append(row)

    return filtered[:limit], module_counts, len(filtered)


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
    _log_workspace_event(
        db,
        EventLevel.INFO,
        "WORKSPACE_MODE_SWITCHED",
        "WORKSPACE_SYSTEM",
        f"Modo activo cambiado a {mode}",
        payload={"mode": mode},
    )
    return {"success": True, "mode": mode}

@router.get("/active-mode")
def get_active_mode(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    return {"mode": SettingsResolver.get("active_source_mode", "smb") or "smb"}


@router.get("/workspace/activity-feed")
def workspace_activity_feed(
    module: str = Query("all"),
    level: str = Query("all"),
    q: str = Query(""),
    limit: int = Query(200, ge=1, le=500),
    db: Session = Depends(get_db),
):
    events_rows, module_counts, filtered_total = _collect_workspace_activity_rows(
        db,
        module=module,
        level=level,
        q=q,
        limit=limit,
    )
    events = [_serialize_processing_event(item) for item in events_rows]
    return {
        "success": True,
        "events": events,
        "module_counts": module_counts,
        "total": filtered_total,
    }


@router.post("/workspace/activity-feed/clear")
def clear_workspace_activity_feed(db: Session = Depends(get_db)):
    removed = db.query(ProcessingEvent).delete(synchronize_session=False)
    db.commit()
    return {
        "success": True,
        "removed": int(removed or 0),
        "message": f"Actividad eliminada ({int(removed or 0)} evento(s)).",
    }


@router.get("/workspace/activity-feed/export")
def export_workspace_activity_feed(
    module: str = Query("all"),
    level: str = Query("all"),
    q: str = Query(""),
    limit: int = Query(500, ge=1, le=2000),
    format: str = Query("json"),
    db: Session = Depends(get_db),
):
    export_format = str(format or "json").strip().lower()
    if export_format not in {"json", "csv"}:
        raise HTTPException(status_code=400, detail="Formato invalido. Usa json o csv.")

    SettingsResolver.reload(db)

    events_rows, module_counts, filtered_total = _collect_workspace_activity_rows(
        db,
        module=module,
        level=level,
        q=q,
        limit=limit,
    )
    events = [_serialize_processing_event(item) for item in events_rows]

    export_root = os.path.join(
        SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp",
        "workspace_activity_exports",
    )
    os.makedirs(export_root, exist_ok=True)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    suffix = "json" if export_format == "json" else "csv"
    output_path = os.path.join(export_root, f"activity_{stamp}.{suffix}")

    if export_format == "json":
        payload = {
            "exported_at": datetime.now().isoformat(),
            "filters": {"module": module, "level": level, "q": q, "limit": limit},
            "module_counts": module_counts,
            "total": filtered_total,
            "events": events,
        }
        with open(output_path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        media_type = "application/json"
    else:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["created_at", "module", "level", "event_type", "stage", "message", "batch_id", "candidate_id", "payload_json"])
        for event in events:
            writer.writerow([
                event.get("created_at") or "",
                event.get("module") or "",
                event.get("level") or "",
                event.get("event_type") or "",
                event.get("stage") or "",
                event.get("message") or "",
                event.get("batch_id") or "",
                event.get("candidate_id") or "",
                json.dumps(event.get("payload") or {}, ensure_ascii=False),
            ])
        with open(output_path, "w", encoding="utf-8", newline="") as handle:
            handle.write(buffer.getvalue())
        media_type = "text/csv"

    return FileResponse(
        output_path,
        media_type=media_type,
        filename=os.path.basename(output_path),
    )

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
    _log_workspace_event(
        db,
        EventLevel.INFO,
        "PREPROCESS_SESSION_CREATED",
        "WORKSPACE_PREPROCESS",
        "Sesion de preprocesado creada",
        payload={"session_id": state.get("id")},
    )
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
        _log_workspace_event(
            db,
            EventLevel.INFO,
            "PREPROCESS_FILES_UPLOADED",
            "WORKSPACE_PREPROCESS",
            f"Archivos subidos a preprocesado ({len(result.get('saved', []))})",
            payload={"session_id": session_id, "saved": len(result.get("saved", [])), "rejected": len(result.get("rejected", []))},
        )
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "PREPROCESS_UPLOAD_FAILED",
            "WORKSPACE_PREPROCESS",
            str(exc),
            payload={"session_id": session_id},
        )
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.post("/workspace/preprocess/sessions/{session_id}/analyze")
def analyze_preprocess_session(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        result = preprocess_workspace_service.analyze(session_id)
        _log_workspace_event(
            db,
            EventLevel.INFO if result.get("success", True) else EventLevel.WARNING,
            "PREPROCESS_ANALYZED",
            "WORKSPACE_PREPROCESS",
            result.get("message") or "Analisis de preprocesado completado",
            payload={
                "session_id": session_id,
                "files_processed": ((result.get("analysis") or {}).get("files_processed") or 0),
                "warnings": len(((result.get("analysis") or {}).get("warnings") or [])),
            },
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "PREPROCESS_ANALYZE_FAILED",
            "WORKSPACE_PREPROCESS",
            str(exc),
            payload={"session_id": session_id},
        )
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
        result = preprocess_workspace_service.generate_markdown(
            session_id=session_id,
            municipality=municipality,
            category=category,
            flow_id=flow_id,
            enable_web_enrichment=enable_web,
            web_query=web_query,
        )
        _log_workspace_event(
            db,
            EventLevel.INFO if result.get("success", True) else EventLevel.WARNING,
            "PREPROCESS_MARKDOWN_GENERATED",
            "WORKSPACE_PREPROCESS",
            result.get("message") or "Markdown generado",
            payload={"session_id": session_id, "flow_id": flow_id, "municipality": municipality, "category": category},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "PREPROCESS_MARKDOWN_FAILED",
            "WORKSPACE_PREPROCESS",
            str(exc),
            payload={"session_id": session_id, "flow_id": flow_id},
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/preprocess/sessions/{session_id}/package")
def package_preprocess_session(session_id: str, payload: Optional[dict] = Body(None), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    payload = payload or {}
    folder_name = str(payload.get("article_folder_name", "") or "")
    try:
        result = preprocess_workspace_service.package_article(session_id, article_folder_name=folder_name)
        _log_workspace_event(
            db,
            EventLevel.INFO if result.get("success", True) else EventLevel.WARNING,
            "PREPROCESS_PACKAGED",
            "WORKSPACE_PREPROCESS",
            result.get("message") or "Paquete generado",
            payload={"session_id": session_id, "package_path": result.get("package_path")},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "PREPROCESS_PACKAGE_FAILED",
            "WORKSPACE_PREPROCESS",
            str(exc),
            payload={"session_id": session_id},
        )
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
        result = preprocess_workspace_service.publish_to_flow_input(session_id, flow)
        level = EventLevel.INFO if result.get("success") else EventLevel.WARNING
        _log_workspace_event(
            db,
            level,
            "PREPROCESS_PUBLISHED",
            "WORKSPACE_PREPROCESS",
            result.get("message") or "Publicacion de preprocesado completada",
            payload={
                "session_id": session_id,
                "flow_id": str(flow.id),
                "published_input_path": result.get("published_input_path"),
            },
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "PREPROCESS_PUBLISH_FAILED",
            "WORKSPACE_PREPROCESS",
            str(exc),
            payload={"session_id": session_id, "flow_id": str(flow.id)},
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions")
def create_final_review_session(db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    state = final_review_workspace_service.create_session()
    _log_workspace_event(
        db,
        EventLevel.INFO,
        "FINAL_REVIEW_SESSION_CREATED",
        "WORKSPACE_FINAL_REVIEW",
        "Sesion de revision final creada",
        payload={"session_id": state.get("id")},
    )
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
        result = final_review_workspace_service.load_export_file(session_id, file)
        _log_workspace_event(
            db,
            EventLevel.INFO if result.get("success", True) else EventLevel.WARNING,
            "FINAL_REVIEW_EXPORT_LOADED",
            "WORKSPACE_FINAL_REVIEW",
            result.get("message") or "Export cargado para QA",
            payload={"session_id": session_id, "articles_count": result.get("articles_count", 0)},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "FINAL_REVIEW_LOAD_FAILED",
            "WORKSPACE_FINAL_REVIEW",
            str(exc),
            payload={"session_id": session_id},
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/run-checks")
def run_final_review_checks(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        result = final_review_workspace_service.run_checks(session_id)
        checks = result.get("checks") or {}
        level = EventLevel.WARNING if (not result.get("success", True) or (checks.get("issues_total") or 0) > 0) else EventLevel.INFO
        _log_workspace_event(
            db,
            level,
            "FINAL_REVIEW_CHECKS_RUN",
            "WORKSPACE_FINAL_REVIEW",
            "Checks de revision final ejecutados",
            payload={"session_id": session_id, **checks},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "FINAL_REVIEW_CHECKS_FAILED",
            "WORKSPACE_FINAL_REVIEW",
            str(exc),
            payload={"session_id": session_id},
        )
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
        result = final_review_workspace_service.update_article(session_id, article_id, payload)
        _log_workspace_event(
            db,
            EventLevel.INFO if result.get("success", True) else EventLevel.WARNING,
            "FINAL_REVIEW_ARTICLE_UPDATED",
            "WORKSPACE_FINAL_REVIEW",
            result.get("message") or "Articulo QA actualizado",
            payload={"session_id": session_id, "article_id": article_id},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "FINAL_REVIEW_ARTICLE_UPDATE_FAILED",
            "WORKSPACE_FINAL_REVIEW",
            str(exc),
            payload={"session_id": session_id, "article_id": article_id},
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/articles/{article_id}/ai-adjust")
def ai_adjust_final_review_article(session_id: str, article_id: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    instructions = str(payload.get("instructions", "") or "")
    try:
        result = final_review_workspace_service.ai_adjust_article(session_id, article_id, instructions)
        level = EventLevel.INFO if result.get("success") else EventLevel.WARNING
        _log_workspace_event(
            db,
            level,
            "FINAL_REVIEW_AI_ADJUST",
            "WORKSPACE_FINAL_REVIEW",
            result.get("message") or "Ajuste IA en QA",
            payload={"session_id": session_id, "article_id": article_id},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "FINAL_REVIEW_AI_ADJUST_FAILED",
            "WORKSPACE_FINAL_REVIEW",
            str(exc),
            payload={"session_id": session_id, "article_id": article_id},
        )
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/workspace/final-review/sessions/{session_id}/export-reviewed")
def export_final_reviewed(session_id: str, db: Session = Depends(get_db)):
    SettingsResolver.reload(db)
    try:
        result = final_review_workspace_service.export_reviewed(session_id)
        level = EventLevel.INFO if result.get("success") else EventLevel.WARNING
        _log_workspace_event(
            db,
            level,
            "FINAL_REVIEW_EXPORTED",
            "WORKSPACE_FINAL_REVIEW",
            result.get("message") or "Export revisado generado",
            payload={"session_id": session_id, "json_path": result.get("json_path"), "csv_path": result.get("csv_path")},
        )
        return result
    except Exception as exc:
        _log_workspace_event(
            db,
            EventLevel.ERROR,
            "FINAL_REVIEW_EXPORT_FAILED",
            "WORKSPACE_FINAL_REVIEW",
            str(exc),
            payload={"session_id": session_id},
        )
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
        result = {
            "success": False,
            "message": f"Hay {len(active_batches)} lote(s) activos. Espera a que terminen antes de limpiar temporales.",
        }
        _log_workspace_event(
            db,
            EventLevel.WARNING,
            "MANUAL_CLEANUP_BLOCKED",
            "WORKSPACE_SYSTEM",
            result["message"],
            payload={"mode": mode, "dry_run": dry_run, "active_batches": len(active_batches)},
        )
        return result

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

    result = {
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
    _log_workspace_event(
        db,
        EventLevel.INFO if result["success"] else EventLevel.WARNING,
        "MANUAL_CLEANUP_EXECUTED",
        "WORKSPACE_SYSTEM",
        result["message"],
        payload={
            "mode": mode,
            "dry_run": dry_run,
            "planned": total_planned,
            "removed": total_removed,
            "errors": total_errors,
        },
    )
    return result


@router.post("/manual/inbox/upload-tree")
async def upload_manual_tree(
    files: List[UploadFile] = File(...),
    relative_paths: List[str] = Form(...),
    db: Session = Depends(get_db),
):
    SettingsResolver.reload(db)
    result = await manual_tree_service.upload_tree(db, files, relative_paths)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_TREE_UPLOADED",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Carga de arbol manual completada",
        payload={
            "session_id": result.get("session_id"),
            "saved": result.get("saved", 0),
            "rejected": result.get("rejected", 0),
            "invalid_structure": result.get("invalid_structure", 0),
            "groups_count": result.get("groups_count", 0),
        },
    )
    return result


@router.post("/manual/inbox/groups/assign")
def assign_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
        flow_id = UUID(payload.get("flow_id", ""))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    SettingsResolver.reload(db)
    result = manual_tree_service.assign_groups(db, group_ids, flow_id)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_TREE_ASSIGNED",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Asignacion manual de grupos",
        payload={"group_ids": [str(item) for item in group_ids], "flow_id": str(flow_id)},
    )
    return result


@router.post("/manual/inbox/groups/auto-assign")
def auto_assign_manual_tree_groups(
    only_unassigned: bool = Query(True),
    db: Session = Depends(get_db),
):
    SettingsResolver.reload(db)
    result = manual_tree_service.auto_assign_groups(db, only_unassigned=only_unassigned)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_TREE_AUTO_ASSIGNED",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Autoasignacion de grupos",
        payload={"only_unassigned": only_unassigned, "assigned": result.get("assigned", 0), "unresolved": result.get("unresolved", 0)},
    )
    return result


@router.post("/manual/inbox/groups/preview")
def preview_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para previsualizar")

    SettingsResolver.reload(db)
    result = manual_tree_service.preview_groups(db, group_ids)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_TREE_PREVIEW_GENERATED",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Preview de grupos generado",
        payload={"group_ids": [str(item) for item in group_ids]},
    )
    return result


@router.post("/manual/inbox/groups/accept")
def accept_manual_tree_groups(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para aceptar")

    SettingsResolver.reload(db)
    result = manual_tree_service.accept_groups(db, group_ids)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_TREE_GROUPS_ACCEPTED",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Grupos aceptados en borrador verificado",
        payload={"group_ids": [str(item) for item in group_ids], "accepted": result.get("accepted", 0)},
    )
    return result


@router.post("/manual/inbox/groups/finalize-export")
def finalize_manual_tree_groups_export(payload: dict = Body(...), db: Session = Depends(get_db)):
    try:
        group_ids = [UUID(item) for item in payload.get("group_ids", [])]
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Payload invalido: {exc}")

    if not group_ids:
        raise HTTPException(status_code=400, detail="No se han recibido grupos para exportar")

    SettingsResolver.reload(db)
    result = manual_tree_service.finalize_selected_exports(db, group_ids)
    failed = len([item for item in (result.get("exports") or []) if not item.get("success")])
    _log_workspace_event(
        db,
        EventLevel.INFO if failed == 0 else EventLevel.WARNING,
        "MANUAL_TREE_FINAL_EXPORT",
        "WORKSPACE_MANUAL_TREE",
        result.get("message") or "Export final manual por grupos completado",
        payload={"group_ids": [str(item) for item in group_ids], "failed": failed},
    )
    return result


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
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.ERROR,
        "FLOW_RUN_TRIGGERED",
        "WORKSPACE_MANUAL",
        result.get("message") or "Ejecucion de flujo solicitada",
        payload={"flow_id": str(flow.id), "batch_id": result.get("batch_id")},
    )

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
    _log_workspace_event(
        db,
        EventLevel.INFO,
        "MANUAL_FILES_UPLOADED",
        "WORKSPACE_MANUAL",
        f"Archivos manuales cargados ({len(result.get('saved', []))})",
        payload={"flow_id": str(flow.id), "draft_id": result.get("draft_id"), "saved": len(result.get("saved", [])), "rejected": len(result.get("rejected", []))},
    )
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
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_PREVIEW_RUN",
        "WORKSPACE_MANUAL",
        result.get("message") or "Preview manual ejecutado",
        payload={"flow_id": str(flow.id), "draft_id": result.get("draft_id"), "batch_id": result.get("batch_id")},
    )
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
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_PREVIEW_ACCEPTED",
        "WORKSPACE_MANUAL",
        result.get("message") or "Preview manual aceptado",
        payload={"flow_id": str(flow.id), "sequence": result.get("sequence")},
    )
    return result


@router.post("/{flow_id}/manual/discard")
def discard_manual_preview(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    result = manual_flow_service.discard_pending_preview(db, flow)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_PREVIEW_DISCARDED",
        "WORKSPACE_MANUAL",
        result.get("message") or "Preview manual descartado",
        payload={"flow_id": str(flow.id)},
    )
    return result


@router.post("/{flow_id}/manual/finalize-export")
def finalize_manual_export(flow_id: UUID, db: Session = Depends(get_db)):
    flow = flow_repo.get_by_id(db, flow_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow no encontrado")

    SettingsResolver.reload(db)
    result = manual_flow_service.finalize_export(db, flow)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.ERROR,
        "MANUAL_FINAL_EXPORT",
        "WORKSPACE_MANUAL",
        result.get("message") or "Exportacion manual finalizada",
        payload={"flow_id": str(flow.id), "draft_id": result.get("draft_id"), "count": result.get("count")},
    )

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
    result = manual_flow_service.reset_draft(db, flow)
    _log_workspace_event(
        db,
        EventLevel.INFO if result.get("success") else EventLevel.WARNING,
        "MANUAL_DRAFT_RESET",
        "WORKSPACE_MANUAL",
        result.get("message") or "Borrador manual reiniciado",
        payload={"flow_id": str(flow.id), "draft_id": result.get("draft_id")},
    )
    return result


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
