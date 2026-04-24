import json
import logging
import os
import shutil
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.flow_models import Flow
from app.db.models import ManualTreeGroup, ManualTreeGroupPreview, ManualTreeSession
from app.services.export.flow_export import FlowExporter
from app.services.manual_flow import ManualFlowService
from app.services.pipeline.flow_service import FlowService
from app.services.settings.service import SettingsResolver


logger = logging.getLogger(__name__)


ALLOWED_TREE_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt", ".jpg", ".jpeg", ".png"}


class ManualTreeService:
    def __init__(self):
        self.flow_service = FlowService(settings)
        self.manual_flow_service = ManualFlowService()
        self.exporter = FlowExporter()

    def _base_dir(self) -> str:
        base = SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp"
        return os.path.join(base, "manual_tree_uploads")

    def _session_dir(self, session_id: str) -> str:
        return os.path.join(self._base_dir(), session_id)

    def get_or_create_open_session(self, db: Session) -> ManualTreeSession:
        session = (
            db.query(ManualTreeSession)
            .filter(ManualTreeSession.status == "OPEN")
            .order_by(ManualTreeSession.updated_at.desc())
            .first()
        )
        if session:
            return session

        session = ManualTreeSession(status="OPEN")
        db.add(session)
        db.commit()
        db.refresh(session)
        return session

    async def upload_tree(
        self,
        db: Session,
        files: List[UploadFile],
        relative_paths: List[str],
    ) -> Dict[str, Any]:
        if len(files) != len(relative_paths):
            return {
                "success": False,
                "message": "El numero de archivos no coincide con el numero de rutas relativas.",
            }

        session = self.get_or_create_open_session(db)
        root = self._session_dir(str(session.id))
        os.makedirs(root, exist_ok=True)

        saved = 0
        rejected = 0
        rejected_items: List[str] = []
        invalid_structure = 0

        for upload, relative in zip(files, relative_paths):
            sanitized = self._sanitize_relative_path(relative)
            if not sanitized:
                invalid_structure += 1
                continue

            parts = sanitized.split("/")
            if len(parts) < 3:
                invalid_structure += 1
                continue

            ext = os.path.splitext(parts[-1].lower())[1]
            if ext not in ALLOWED_TREE_EXTENSIONS:
                rejected += 1
                rejected_items.append(sanitized)
                continue

            target_path = os.path.join(root, *parts)
            os.makedirs(os.path.dirname(target_path), exist_ok=True)
            final_target = self._resolve_unique_target(target_path)
            with open(final_target, "wb") as out:
                shutil.copyfileobj(upload.file, out)
            saved += 1

        rebuilt = self._rebuild_groups_from_disk(db, session)
        db.query(ManualTreeSession).filter(ManualTreeSession.id == session.id).update({"updated_at": datetime.now()})
        db.commit()

        return {
            "success": True,
            "session_id": str(session.id),
            "saved": saved,
            "rejected": rejected,
            "invalid_structure": invalid_structure,
            "rejected_items": rejected_items[:100],
            "groups_count": rebuilt,
        }

    def _sanitize_relative_path(self, value: str) -> str:
        path = (value or "").strip().replace("\\", "/")
        while "//" in path:
            path = path.replace("//", "/")
        if path.startswith("/"):
            path = path.lstrip("/")
        if not path or ".." in path:
            return ""
        return path

    def _resolve_unique_target(self, target_path: str) -> str:
        if not os.path.exists(target_path):
            return target_path
        base, ext = os.path.splitext(target_path)
        idx = 2
        while True:
            candidate = f"{base}_{idx}{ext}"
            if not os.path.exists(candidate):
                return candidate
            idx += 1

    def _scan_tree_groups(self, session_id: str) -> Dict[str, Dict[str, Any]]:
        root = self._session_dir(session_id)
        groups: Dict[str, Dict[str, Any]] = {}
        if not os.path.exists(root):
            return groups

        for category in sorted(os.listdir(root)):
            cat_path = os.path.join(root, category)
            if not os.path.isdir(cat_path):
                continue

            for article in sorted(os.listdir(cat_path)):
                article_path = os.path.join(cat_path, article)
                if not os.path.isdir(article_path):
                    continue

                group_key = self._build_group_key(category, article)
                files: List[str] = []
                for walk_root, _dirs, names in os.walk(article_path):
                    for name in names:
                        full = os.path.join(walk_root, name)
                        rel = os.path.relpath(full, root).replace("\\", "/")
                        files.append(rel)
                files.sort()

                groups[group_key] = {
                    "group_key": group_key,
                    "category_name": category,
                    "article_name": article,
                    "files": files,
                }
        return groups

    def _build_group_key(self, category_name: str, article_name: str) -> str:
        cat = (category_name or "").strip().lower()
        art = (article_name or "").strip().lower()
        return f"{cat}/{art}"

    def _normalize_category_key(self, value: str) -> str:
        raw = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
        normalized = unicodedata.normalize("NFKD", raw)
        ascii_only = "".join(ch for ch in normalized if not unicodedata.combining(ch))
        compact = "".join(ch for ch in ascii_only if ch.isalnum() or ch == "_")
        compact = "_".join(part for part in compact.split("_") if part)
        aliases = {
            "noticias": "noticies",
            "turismeactiu": "turisme_actiu",
            "nensijoves": "nens_i_joves",
        }
        return aliases.get(compact, compact)

    def _rebuild_groups_from_disk(self, db: Session, session: ManualTreeSession) -> int:
        current_groups = (
            db.query(ManualTreeGroup)
            .filter(ManualTreeGroup.session_id == session.id)
            .all()
        )
        existing_by_key = {g.group_key: g for g in current_groups}

        scanned = self._scan_tree_groups(str(session.id))
        seen_keys = set()
        for data in scanned.values():
            seen_keys.add(data["group_key"])
            errors: List[str] = []
            if not data["files"]:
                errors.append("La carpeta del articulo no contiene archivos.")

            row = existing_by_key.get(data["group_key"])
            if row:
                row.category_name = data["category_name"]
                row.article_name = data["article_name"]
                row.files_json = data["files"]
                row.validation_errors_json = errors
                row.status = "ERROR" if errors else (row.status or ("ASSIGNED" if row.assigned_flow_id else "UNASSIGNED"))
                row.updated_at = datetime.now()
            else:
                row = ManualTreeGroup(
                    session_id=session.id,
                    group_key=data["group_key"],
                    category_name=data["category_name"],
                    article_name=data["article_name"],
                    files_json=data["files"],
                    validation_errors_json=errors,
                    assigned_flow_id=None,
                    status="ERROR" if errors else "UNASSIGNED",
                )
                db.add(row)

        for old_group in current_groups:
            if old_group.group_key in seen_keys:
                continue
            db.delete(old_group)
        db.flush()
        return len(scanned)

    def get_groups_state(self, db: Session) -> Dict[str, Any]:
        session = self.get_or_create_open_session(db)
        groups = (
            db.query(ManualTreeGroup)
            .filter(ManualTreeGroup.session_id == session.id)
            .order_by(ManualTreeGroup.category_name.asc(), ManualTreeGroup.article_name.asc())
            .all()
        )

        SettingsResolver.reload(db)
        active_mode = (SettingsResolver.get("active_source_mode", "smb") or "smb").lower()
        flows = (
            db.query(Flow)
            .filter(Flow.enabled == True)
            .order_by(Flow.category.asc(), Flow.municipality.asc(), Flow.name.asc())
            .all()
        )
        flows = [f for f in flows if (f.source_mode or "smb") == active_mode]
        flows_by_id = {str(f.id): f for f in flows}

        category_preferred_flow: Dict[str, str] = {}
        assigned_by_category: Dict[str, set] = {}
        for group in groups:
            if not group.assigned_flow_id:
                continue
            flow = flows_by_id.get(str(group.assigned_flow_id))
            if not flow:
                continue
            category_key = self._normalize_category_key(group.category_name)
            assigned_by_category.setdefault(category_key, set()).add(str(flow.id))

        for category_key, flow_ids in assigned_by_category.items():
            if len(flow_ids) == 1:
                category_preferred_flow[category_key] = next(iter(flow_ids))

        def detect_suggested_flow(category_name: str) -> Tuple[Optional[Flow], Optional[int]]:
            category_key = self._normalize_category_key(category_name)

            preferred_id = category_preferred_flow.get(category_key)
            if preferred_id and preferred_id in flows_by_id:
                return flows_by_id[preferred_id], 1

            matches = [
                flow
                for flow in flows
                if self._normalize_category_key(flow.category or "") == category_key
            ]
            if len(matches) == 1:
                return matches[0], 1
            if len(matches) > 1:
                return None, len(matches)
            return None, None

        previews = (
            db.query(ManualTreeGroupPreview)
            .filter(ManualTreeGroupPreview.group_id.in_([g.id for g in groups]))
            .all()
            if groups
            else []
        )
        previews_by_group = {str(preview.group_id): preview for preview in previews}

        serialized_groups = []
        counters = {
            "total": 0,
            "unassigned": 0,
            "assigned": 0,
            "error": 0,
            "ready": 0,
            "preview_ready": 0,
            "verified": 0,
            "exported": 0,
        }

        for group in groups:
            counters["total"] += 1
            assigned_flow = flows_by_id.get(str(group.assigned_flow_id)) if group.assigned_flow_id else None
            suggested, suggested_matches = detect_suggested_flow(group.category_name)
            has_errors = bool(group.validation_errors_json)
            preview = previews_by_group.get(str(group.id))
            preview_status = preview.status if preview else None

            if has_errors:
                status = "ERROR"
            elif preview_status == "EXPORTED":
                status = "EXPORTED"
            elif preview_status == "ACCEPTED":
                status = "VERIFIED"
            elif preview_status == "READY":
                status = "PREVIEW_READY"
            elif assigned_flow:
                status = "ASSIGNED"
            else:
                status = "UNASSIGNED"

            ready = bool(status in {"ASSIGNED", "PREVIEW_READY"})

            if status == "ERROR":
                counters["error"] += 1
            elif status == "ASSIGNED":
                counters["assigned"] += 1
                counters["ready"] += 1
            elif status == "PREVIEW_READY":
                counters["assigned"] += 1
                counters["ready"] += 1
                counters["preview_ready"] += 1
            elif status == "VERIFIED":
                counters["assigned"] += 1
                counters["verified"] += 1
            elif status == "EXPORTED":
                counters["assigned"] += 1
                counters["verified"] += 1
                counters["exported"] += 1
            else:
                counters["unassigned"] += 1

            serialized_groups.append(
                {
                    "id": str(group.id),
                    "group_key": group.group_key,
                    "category_name": group.category_name,
                    "article_name": group.article_name,
                    "files_count": len(group.files_json or []),
                    "files": group.files_json or [],
                    "validation_errors": group.validation_errors_json or [],
                    "status": status,
                    "assigned_flow_id": str(assigned_flow.id) if assigned_flow else None,
                    "assigned_flow_label": self._flow_label(assigned_flow) if assigned_flow else None,
                    "suggested_flow_id": str(suggested.id) if suggested else None,
                    "suggested_flow_label": (
                        self._flow_label(suggested)
                        if suggested
                        else (f"Seleccion manual ({suggested_matches} opciones)" if suggested_matches and suggested_matches > 1 else None)
                    ),
                    "preview": {
                        "exists": bool(preview),
                        "status": preview.status if preview else None,
                        "batch_id": preview.source_batch_id if preview else None,
                        "summary": preview.summary if preview else None,
                        "updated_at": preview.updated_at.isoformat() if preview and preview.updated_at else None,
                    },
                }
            )

        flow_options = [{"id": str(f.id), "label": self._flow_label(f)} for f in flows]
        return {
            "success": True,
            "session_id": str(session.id),
            "active_mode": active_mode,
            "groups": serialized_groups,
            "flow_options": flow_options,
            "stats": counters,
        }

    def assign_groups(self, db: Session, group_ids: List[UUID], flow_id: UUID) -> Dict[str, Any]:
        flow = db.query(Flow).filter(Flow.id == flow_id).first()
        if not flow:
            return {"success": False, "message": "Flow no encontrado"}

        groups = db.query(ManualTreeGroup).filter(ManualTreeGroup.id.in_(group_ids)).all()
        if not groups:
            return {"success": False, "message": "No se encontraron grupos para asignar"}

        assigned = 0
        for group in groups:
            if group.validation_errors_json:
                continue
            previous_flow = group.assigned_flow_id
            group.assigned_flow_id = flow.id
            group.status = "ASSIGNED"
            group.updated_at = datetime.now()
            if previous_flow and previous_flow != flow.id:
                db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).delete()
            assigned += 1
        db.commit()

        return {
            "success": True,
            "message": f"{assigned} grupo(s) asignado(s)",
            "assigned": assigned,
        }

    def auto_assign_groups(self, db: Session, only_unassigned: bool = True) -> Dict[str, Any]:
        state = self.get_groups_state(db)
        flow_map = {item["id"]: item for item in state.get("flow_options", [])}
        groups_data = state.get("groups", [])
        group_ids: List[UUID] = []
        flow_ids: List[UUID] = []
        unresolved = 0

        for item in groups_data:
            if item.get("status") == "ERROR":
                continue
            if only_unassigned and item.get("assigned_flow_id"):
                continue
            suggested_id = item.get("suggested_flow_id")
            if not suggested_id or suggested_id not in flow_map:
                unresolved += 1
                continue
            group_ids.append(UUID(item["id"]))
            flow_ids.append(UUID(suggested_id))

        assigned = 0
        for group_id, flow_id in zip(group_ids, flow_ids):
            group = db.query(ManualTreeGroup).filter(ManualTreeGroup.id == group_id).first()
            if not group or group.validation_errors_json:
                continue
            previous_flow = group.assigned_flow_id
            group.assigned_flow_id = flow_id
            group.status = "ASSIGNED"
            group.updated_at = datetime.now()
            if previous_flow and previous_flow != flow_id:
                db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).delete()
            assigned += 1

        db.commit()
        if unresolved:
            message = f"{assigned} grupo(s) autoasignado(s). {unresolved} pendiente(s) de asignacion manual."
        else:
            message = f"{assigned} grupo(s) autoasignado(s)"
        return {
            "success": True,
            "message": message,
            "assigned": assigned,
            "unresolved": unresolved,
        }

    def preview_groups(self, db: Session, group_ids: List[UUID]) -> Dict[str, Any]:
        groups = db.query(ManualTreeGroup).filter(ManualTreeGroup.id.in_(group_ids)).all()
        if not groups:
            return {"success": False, "message": "No se encontraron grupos para previsualizar."}

        previewed = 0
        errors: List[Dict[str, str]] = []

        for group in groups:
            if group.validation_errors_json:
                errors.append({"group_id": str(group.id), "message": "El grupo contiene errores de validacion."})
                continue
            if not group.assigned_flow_id:
                errors.append({"group_id": str(group.id), "message": "El grupo no tiene un flujo asignado."})
                continue

            flow = db.query(Flow).filter(Flow.id == group.assigned_flow_id).first()
            if not flow or not flow.enabled:
                errors.append({"group_id": str(group.id), "message": "El flujo asignado no existe o esta desactivado."})
                continue

            source_path = self._group_source_path(group)
            if not os.path.isdir(source_path):
                errors.append({"group_id": str(group.id), "message": "La carpeta del articulo no existe en staging."})
                continue

            source_info = {
                "mode": "local",
                "resolved_path": source_path,
                "local_temp_dir": None,
                "smb_source_unc": None,
                "relative_source_path": None,
            }
            result = self.flow_service.run_flow(flow, source_info_override=source_info, skip_move_processed=True)
            if not result.get("success"):
                errors.append({"group_id": str(group.id), "message": result.get("message", "Error en previsualizacion")})
                continue

            payload = result.get("export_payload")
            articles = result.get("articles", []) or []
            preview_json = self.flow_service.generate_json(flow, articles, payload)

            preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
            if not preview:
                preview = ManualTreeGroupPreview(group_id=group.id)
                db.add(preview)

            preview.status = "READY"
            preview.source_batch_id = result.get("batch_id")
            preview.payload_json = payload
            preview.articles_json = articles
            preview.summary = result.get("message")
            preview.preview_json = preview_json
            preview.updated_at = datetime.now()
            preview.accepted_at = None

            group.status = "ASSIGNED"
            group.updated_at = datetime.now()
            previewed += 1

        db.commit()
        return {
            "success": previewed > 0,
            "message": f"{previewed} grupo(s) previsualizado(s)",
            "previewed": previewed,
            "errors": errors,
        }

    def accept_groups(self, db: Session, group_ids: List[UUID]) -> Dict[str, Any]:
        groups = db.query(ManualTreeGroup).filter(ManualTreeGroup.id.in_(group_ids)).all()
        if not groups:
            return {"success": False, "message": "No se encontraron grupos para aceptar."}

        accepted = 0
        errors: List[Dict[str, str]] = []

        for group in groups:
            if not group.assigned_flow_id:
                errors.append({"group_id": str(group.id), "message": "Grupo sin flujo asignado."})
                continue

            preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
            if not preview or preview.status != "READY":
                errors.append({"group_id": str(group.id), "message": "No hay preview lista para aceptar."})
                continue

            flow = db.query(Flow).filter(Flow.id == group.assigned_flow_id).first()
            if not flow:
                errors.append({"group_id": str(group.id), "message": "Flow asignado no encontrado."})
                continue

            added = self.manual_flow_service.add_verified_item(
                db,
                flow,
                payload=preview.payload_json or {},
                articles=preview.articles_json or [],
                files=group.files_json or [],
                summary=preview.summary,
                source_batch_id=preview.source_batch_id,
            )
            if not added.get("success"):
                errors.append({"group_id": str(group.id), "message": "No se pudo anadir al borrador final."})
                continue

            preview.status = "ACCEPTED"
            preview.accepted_at = datetime.now()
            preview.updated_at = datetime.now()
            group.status = "VERIFIED"
            group.updated_at = datetime.now()
            accepted += 1

        db.commit()
        return {
            "success": accepted > 0,
            "message": f"{accepted} grupo(s) aceptado(s)",
            "accepted": accepted,
            "errors": errors,
        }

    def get_group_preview(self, db: Session, group_id: UUID) -> Dict[str, Any]:
        preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group_id).first()
        if not preview:
            return {"success": False, "message": "El grupo no tiene previsualizacion."}
        return {
            "success": True,
            "group_id": str(group_id),
            "status": preview.status,
            "batch_id": preview.source_batch_id,
            "summary": preview.summary,
            "preview_json": preview.preview_json,
            "updated_at": preview.updated_at.isoformat() if preview.updated_at else None,
        }

    def update_group_preview_json(self, db: Session, group_id: UUID, preview_json_text: str) -> Dict[str, Any]:
        group = db.query(ManualTreeGroup).filter(ManualTreeGroup.id == group_id).first()
        if not group:
            return {"success": False, "message": "Grupo no encontrado."}

        preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
        if not preview:
            return {"success": False, "message": "El grupo no tiene previsualizacion para editar."}
        if preview.status not in {"READY"}:
            return {"success": False, "message": "Solo se puede editar una preview en estado READY."}

        if not preview_json_text or not preview_json_text.strip():
            return {"success": False, "message": "El JSON no puede estar vacio."}

        original_payload = preview.payload_json
        try:
            parsed = json.loads(preview_json_text)
        except Exception as exc:
            return {"success": False, "message": f"JSON invalido: {exc}"}

        if original_payload is not None:
            shape_ok, shape_error = self._validate_same_shape(original_payload, parsed)
            if not shape_ok:
                return {"success": False, "message": f"El JSON editado rompe la estructura esperada: {shape_error}"}

        preview.payload_json = parsed
        preview.preview_json = json.dumps(parsed, ensure_ascii=False, indent=2)
        preview.summary = "Preview editada manualmente"
        preview.updated_at = datetime.now()
        group.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "message": "Preview actualizada correctamente.",
            "group_id": str(group.id),
            "preview_json": preview.preview_json,
        }

    def recompile_group_preview(self, db: Session, group_id: UUID) -> Dict[str, Any]:
        group = db.query(ManualTreeGroup).filter(ManualTreeGroup.id == group_id).first()
        if not group:
            return {"success": False, "message": "Grupo no encontrado."}

        preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
        if not preview or preview.payload_json is None:
            return {"success": False, "message": "No hay payload para recompilar."}

        flow = db.query(Flow).filter(Flow.id == group.assigned_flow_id).first() if group.assigned_flow_id else None
        if not flow:
            return {"success": False, "message": "No se encontro el flujo asignado para recompilar."}

        normalized = preview.payload_json
        preview.preview_json = self.flow_service.generate_json(flow, [], normalized)
        preview.updated_at = datetime.now()
        preview.summary = "Preview recompilada"
        group.updated_at = datetime.now()
        db.commit()

        csv_content = self.flow_service.generate_csv(flow, [], normalized)
        return {
            "success": True,
            "message": "Preview recompilada correctamente.",
            "group_id": str(group.id),
            "preview_json": preview.preview_json,
            "csv_available": bool(csv_content),
        }

    def apply_ai_changes_to_preview(self, db: Session, group_id: UUID, instructions: str) -> Dict[str, Any]:
        group = db.query(ManualTreeGroup).filter(ManualTreeGroup.id == group_id).first()
        if not group:
            return {"success": False, "message": "Grupo no encontrado."}

        preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
        if not preview or preview.payload_json is None:
            return {"success": False, "message": "No hay preview disponible para aplicar cambios con IA."}
        if preview.status not in {"READY"}:
            return {"success": False, "message": "Solo se puede usar IA sobre previews en estado READY."}
        if not instructions or not instructions.strip():
            return {"success": False, "message": "Debes indicar instrucciones para la IA."}

        from app.services.ai.client import get_active_llm_client

        client = get_active_llm_client()
        if not client:
            client = get_active_llm_client(use_ocr_vision=True)
        if not client:
            return {
                "success": False,
                "message": (
                    "No hay conexion IA activa para aplicar cambios. "
                    "Activa una conexion en Ajustes > AI (estrella ACTIVA) o configura OCR Vision connection."
                ),
            }

        current_json = json.dumps(preview.payload_json, ensure_ascii=False, indent=2)
        system = (
            "Eres un asistente que modifica JSON editorial respetando estructura. "
            "Nunca cambies el tipo raiz ni la estructura de claves obligatorias. "
            "Devuelve solo JSON valido, sin markdown ni explicaciones."
        )
        prompt = (
            f"Instrucciones del usuario:\n{instructions.strip()}\n\n"
            "JSON actual:\n"
            f"{current_json}\n\n"
            "Aplica los cambios pedidos manteniendo estructura y tipos. "
            "No elimines campos obligatorios. Responde solo con JSON valido."
        )

        try:
            response = client.chat(prompt, system=system, max_tokens=5000)
        except Exception as exc:
            if self._is_timeout_error(exc):
                logger.warning("Timeout IA en preview %s, reintentando una vez", group_id)
                try:
                    response = client.chat(prompt, system=system, max_tokens=5000)
                except Exception as retry_exc:
                    logger.warning("No se pudo aplicar cambios IA en preview %s tras reintento: %s", group_id, retry_exc)
                    return {
                        "success": False,
                        "message": (
                            "La IA ha excedido el tiempo de espera. "
                            "Prueba un modelo mas rapido (ej. llama3.1:8b-instruct), revisa carga de Ollama o aumenta llm_timeout_seconds. "
                            f"Detalle: {retry_exc}"
                        ),
                    }
            else:
                logger.warning("No se pudo aplicar cambios IA en preview %s: %s", group_id, exc)
                return {"success": False, "message": f"La IA no devolvio un JSON valido: {exc}"}

        try:
            candidate_text = self._extract_json_text(response)
            candidate = json.loads(candidate_text)
        except Exception as exc:
            return {"success": False, "message": f"La IA no devolvio un JSON valido: {exc}"}

        if not isinstance(candidate, (dict, list)):
            return {"success": False, "message": "La IA devolvio un formato invalido. Debe ser JSON objeto o lista."}

        shape_ok, shape_error = self._validate_same_shape(preview.payload_json, candidate)
        if not shape_ok:
            return {"success": False, "message": f"La propuesta de IA rompe la estructura: {shape_error}"}

        if candidate == preview.payload_json:
            return {
                "success": True,
                "message": "La IA no ha propuesto cambios sobre el JSON actual.",
                "group_id": str(group.id),
                "preview_json": preview.preview_json or json.dumps(preview.payload_json, ensure_ascii=False, indent=2),
                "unchanged": True,
            }

        preview.payload_json = candidate
        preview.preview_json = json.dumps(candidate, ensure_ascii=False, indent=2)
        preview.summary = "Preview ajustada con IA"
        preview.updated_at = datetime.now()
        group.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "message": "Cambios de IA aplicados correctamente.",
            "group_id": str(group.id),
            "preview_json": preview.preview_json,
            "unchanged": False,
        }

    def delete_groups(self, db: Session, group_ids: List[UUID]) -> Dict[str, Any]:
        groups = db.query(ManualTreeGroup).filter(ManualTreeGroup.id.in_(group_ids)).all()
        if not groups:
            return {"success": False, "message": "No se encontraron grupos para borrar."}

        deleted = 0
        for group in groups:
            source_path = self._group_source_path(group)
            if os.path.isdir(source_path):
                shutil.rmtree(source_path, ignore_errors=True)
            db.delete(group)
            deleted += 1

        # Rebuild from disk so DB reflects remaining folders
        session_ids = {str(group.session_id) for group in groups}
        db.flush()
        for session_id in session_ids:
            session = db.query(ManualTreeSession).filter(ManualTreeSession.id == UUID(session_id)).first()
            if session:
                self._rebuild_groups_from_disk(db, session)
                session.updated_at = datetime.now()
        db.commit()

        return {"success": True, "message": f"{deleted} grupo(s) eliminado(s)", "deleted": deleted}

    def finalize_selected_exports(self, db: Session, group_ids: List[UUID]) -> Dict[str, Any]:
        groups = db.query(ManualTreeGroup).filter(ManualTreeGroup.id.in_(group_ids)).all()
        if not groups:
            return {"success": False, "message": "No se encontraron grupos para exportar."}

        selected_by_flow: Dict[UUID, List[Tuple[ManualTreeGroup, ManualTreeGroupPreview]]] = {}
        errors: List[Dict[str, str]] = []

        for group in groups:
            if not group.assigned_flow_id:
                errors.append({"group_id": str(group.id), "message": "Grupo sin flujo asignado."})
                continue

            preview = db.query(ManualTreeGroupPreview).filter(ManualTreeGroupPreview.group_id == group.id).first()
            if not preview or preview.status not in {"ACCEPTED", "EXPORTED"}:
                errors.append({"group_id": str(group.id), "message": "El grupo debe estar aceptado antes de exportar."})
                continue

            selected_by_flow.setdefault(group.assigned_flow_id, []).append((group, preview))

        if not selected_by_flow:
            return {"success": False, "message": "No hay grupos aceptados para exportar.", "errors": errors}

        exports: List[Dict[str, Any]] = []
        for flow_id, items in selected_by_flow.items():
            flow = db.query(Flow).filter(Flow.id == flow_id).first()
            if not flow:
                errors.append({"group_id": "-", "message": f"Flow {flow_id} no encontrado."})
                continue

            payloads = [preview.payload_json for _group, preview in items if preview.payload_json is not None]
            merged_payload = self.flow_service._merge_export_payloads(payloads)
            if merged_payload is None:
                errors.append({"group_id": "-", "message": f"No se pudo construir payload para flow {flow.id}."})
                continue

            json_content = self.flow_service.generate_json(flow, [], merged_payload)
            csv_content = self.flow_service.generate_csv(flow, [], merged_payload)

            ok_json, msg_json = self.exporter.upload_to_outfolder(flow.municipality, flow.output_filename, json_content, content_label="JSON")
            ok_csv = True
            msg_csv = ""
            if csv_content:
                base_name, _ext = os.path.splitext(flow.output_filename)
                csv_name = f"{base_name}.csv" if base_name else f"{flow.output_filename}.csv"
                ok_csv, msg_csv = self.exporter.upload_to_outfolder(flow.municipality, csv_name, csv_content, content_label="CSV")

            export_ok = bool(ok_json and ok_csv)
            message = msg_json if not msg_csv else f"{msg_json} | {msg_csv}"

            if export_ok:
                for group, preview in items:
                    preview.status = "EXPORTED"
                    preview.updated_at = datetime.now()
                    group.status = "EXPORTED"
                    group.updated_at = datetime.now()

            flow.last_run_at = datetime.now()
            flow.last_run_status = "EXPORTED" if export_ok else "ERROR"
            flow.last_run_summary = message[:255]

            exports.append(
                {
                    "flow_id": str(flow.id),
                    "flow_label": self._flow_label(flow),
                    "groups": len(items),
                    "success": export_ok,
                    "message": message,
                }
            )

        db.commit()

        success_count = len([item for item in exports if item.get("success")])
        return {
            "success": success_count > 0,
            "message": f"{success_count} exportacion(es) completada(s)",
            "exports": exports,
            "errors": errors,
        }

    def _group_source_path(self, group: ManualTreeGroup) -> str:
        return os.path.join(
            self._session_dir(str(group.session_id)),
            group.category_name,
            group.article_name,
        )

    def _extract_json_text(self, text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned

    def _is_timeout_error(self, exc: Exception) -> bool:
        text = str(exc or "").lower()
        if "timed out" in text or "timeout" in text:
            return True
        return False

    def _validate_same_shape(self, base: Any, candidate: Any, path: str = "$") -> Tuple[bool, str]:
        if isinstance(base, dict):
            if not isinstance(candidate, dict):
                return False, f"{path} debe ser objeto"
            base_keys = set(base.keys())
            cand_keys = set(candidate.keys())
            if base_keys != cand_keys:
                missing = sorted(base_keys - cand_keys)
                extra = sorted(cand_keys - base_keys)
                return False, f"{path} claves distintas (faltan={missing}, sobran={extra})"
            for key in base_keys:
                ok, err = self._validate_same_shape(base[key], candidate[key], f"{path}.{key}")
                if not ok:
                    return ok, err
            return True, ""

        if isinstance(base, list):
            if not isinstance(candidate, list):
                return False, f"{path} debe ser lista"
            if not base or not candidate:
                return True, ""
            sample_base = base[0]
            for idx, item in enumerate(candidate):
                ok, err = self._validate_same_shape(sample_base, item, f"{path}[{idx}]")
                if not ok:
                    return ok, err
            return True, ""

        if isinstance(base, bool):
            if not isinstance(candidate, bool):
                return False, f"{path} debe ser boolean"
            return True, ""

        if isinstance(base, int) and not isinstance(base, bool):
            if not isinstance(candidate, int) or isinstance(candidate, bool):
                return False, f"{path} debe ser entero"
            return True, ""

        if isinstance(base, float):
            if not isinstance(candidate, (float, int)) or isinstance(candidate, bool):
                return False, f"{path} debe ser numerico"
            return True, ""

        if base is None:
            return True, ""

        if isinstance(base, str):
            if not isinstance(candidate, str):
                return False, f"{path} debe ser texto"
            return True, ""

        return True, ""

    def _flow_label(self, flow: Optional[Flow]) -> str:
        if not flow:
            return ""
        name = (flow.name or "").strip()
        if name:
            return name
        return f"{flow.municipality} · {flow.category}"

    def check_ai_connection(self) -> Dict[str, Any]:
        from app.services.ai.client import get_active_llm_client
        import httpx

        client = get_active_llm_client()
        if not client:
            client = get_active_llm_client(use_ocr_vision=True)
        if not client:
            return {
                "success": False,
                "provider": None,
                "model": None,
                "message": "No hay conexion IA activa. Configurala en Ajustes > AI.",
            }

        provider = str(client.provider or "").lower()
        model = str(client.model or "")

        try:
            if provider == "ollama":
                base_url = (client.base_url or "http://localhost:11434").rstrip("/")
                tags_resp = httpx.get(f"{base_url}/api/tags", timeout=8)
                tags_resp.raise_for_status()
                models = [str(item.get("name", "")) for item in tags_resp.json().get("models", [])]
                if model and model not in models:
                    return {
                        "success": False,
                        "provider": provider,
                        "model": model,
                        "message": f"El modelo '{model}' no esta disponible en Ollama ({base_url}).",
                    }

                _ = client.chat(
                    "Responde solo OK.",
                    system="Eres un asistente tecnico.",
                    max_tokens=16,
                    timeout_seconds=20,
                )
                return {
                    "success": True,
                    "provider": provider,
                    "model": model,
                    "message": f"Conexion IA OK ({provider}/{model}).",
                }

            _ = client.chat(
                "Responde solo OK.",
                system="Eres un asistente tecnico.",
                max_tokens=16,
                timeout_seconds=20,
            )
            return {
                "success": True,
                "provider": provider,
                "model": model,
                "message": f"Conexion IA OK ({provider}/{model}).",
            }
        except Exception as exc:
            return {
                "success": False,
                "provider": provider,
                "model": model,
                "message": f"La conexion IA no responde en test rapido: {exc}",
            }
