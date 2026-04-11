import json
import os
import shutil
import tempfile
import csv
from io import StringIO
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

from app.db.flow_models import Flow
from app.db.session import SessionLocal
from app.db.repositories.flow_repos import flow_repo
from app.services.ingestion.service import IngestionService
from app.services.grouping.orchestrator import GroupingOrchestrator
from app.services.extraction.orchestrator import ExtractionOrchestrator
from app.services.classification.orchestrator import ClassificationOrchestrator
from app.services.editorial.builder import EditorialBuilderService
from app.services.images.processor import ImageProcessingService
from app.services.export.builder import WordPressJsonExportBuilder
from app.adapters.factory import AdapterFactory
from app.services.pipeline.events import event_logger
from app.services.settings.service import SettingsResolver
from app.core.enums import EventLevel, CandidateGroupingStrategy
from app.core.states import BatchStatus, CandidateStatus
from app.db.repositories.all_repos import (
    source_batch_repo, source_file_repo, content_candidate_repo,
    canonical_content_repo, processing_event_repo
)

SUPPORTED_EXTENSIONS = ('.pdf', '.docx', '.jpg', '.jpeg', '.png')


class FlowService:
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

    def resolve_source_info(self, flow: Flow) -> Dict[str, Any]:
        source_mode = SettingsResolver.get("active_source_mode", "smb") or "smb"
        info = {"mode": source_mode, "local_temp_dir": None, "smb_source_unc": None, "resolved_path": None, "relative_source_path": None}

        if source_mode == "smb":
            from app.services.remote.clients import SmbRemoteInboxClient
            client = SmbRemoteInboxClient()
            cfg = client._get_config()
            share = cfg["share"] or ""
            host = cfg["host"] or ""

            municipality_path = self._get_municipality_hotfolder_path(flow.municipality)
            subfolder = (flow.source_folder or "").strip("/")

            parts = [municipality_path, subfolder]
            path_suffix = "/".join(p for p in parts if p)

            unc_base = f"\\\\{host}\\{share}"
            if path_suffix:
                unc_base += f"\\{path_suffix.replace('/', chr(92))}"

            full_remote_path = f"{host}/{share}/{path_suffix}" if path_suffix else f"{host}/{share}"

            info["resolved_path"] = full_remote_path
            info["smb_source_unc"] = unc_base
            info["relative_source_path"] = path_suffix
            info["smb_config"] = cfg
        else:
            local_base = SettingsResolver.get("hot_folder_local_path")
            municipality_path = self._get_municipality_hotfolder_path(flow.municipality).lstrip("/")
            subfolder = (flow.source_folder or "").strip("/")
            parts = [local_base, municipality_path, subfolder]
            local_path = os.path.join(*[p for p in parts if p])
            info["resolved_path"] = local_path

        return info

    def _get_municipality_hotfolder_path(self, municipality: str) -> str:
        import json as json_mod
        source_mode = SettingsResolver.get("active_source_mode", "smb") or "smb"
        setting_key = "hotfolder_local_folders" if source_mode == "local" else "hotfolder_folders"
        folders_json = SettingsResolver.get(setting_key)
        if not folders_json:
            return municipality.lower()
        try:
            folders = json_mod.loads(folders_json)
            if isinstance(folders, list):
                for f in folders:
                    name = f.get("name", "")
                    if name.upper() == municipality.upper():
                        return (f.get("base_path") or "").strip("/")
        except Exception:
            pass
        return municipality.lower()

    def _list_remote_files(self, unc_path: str) -> Tuple[List[str], Optional[str]]:
        from smbclient import register_session, listdir, reset_connection_cache, stat as smb_stat
        from app.services.remote.clients import SmbRemoteInboxClient

        client = SmbRemoteInboxClient()
        cfg = client._get_config()

        try:
            register_session(
                server=cfg["host"],
                username=client._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            files = []
            self._scan_smb_dir(unc_path, unc_path, files, cfg)
            reset_connection_cache()
            return files, None
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            return [], str(e)

    def _scan_smb_dir(self, base_unc: str, current_unc: str, files: List[str], cfg: dict) -> None:
        from smbclient import listdir, stat as smb_stat

        entries = listdir(current_unc)
        for e in entries:
            name = str(e)
            if name.startswith('.'):
                continue
            try:
                st = smb_stat(f"{current_unc}\\{name}")
                is_dir = bool(st.st_file_attributes & 0x10)
                if is_dir:
                    self._scan_smb_dir(base_unc, f"{current_unc}\\{name}", files, cfg)
                    continue
            except Exception:
                continue
            if name.lower().endswith(SUPPORTED_EXTENSIONS):
                relative = current_unc[len(base_unc):].lstrip("\\")
                if relative:
                    relative = relative.replace("\\", "/") + "/" + name
                else:
                    relative = name
                files.append(relative)

    def _download_from_smb(self, unc_path: str, relative_files: List[str]) -> Tuple[str, Optional[str]]:
        from smbclient import register_session, open_file, reset_connection_cache
        from app.services.remote.clients import SmbRemoteInboxClient

        client = SmbRemoteInboxClient()
        cfg = client._get_config()

        local_temp = tempfile.mkdtemp(prefix="flow_smb_")
        try:
            register_session(
                server=cfg["host"],
                username=client._resolve_username(cfg) or None,
                password=cfg["pass"] or None,
                port=cfg["port"],
                connection_timeout=cfg["timeout"],
            )
            for rel_path in relative_files:
                src = f"{unc_path}\\{rel_path.replace('/', chr(92))}"
                dst = os.path.join(local_temp, rel_path.replace("/", os.sep))
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                with open_file(src, mode="rb") as src_f:
                    with open(dst, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
            reset_connection_cache()
            return local_temp, None
        except Exception as e:
            try:
                reset_connection_cache()
            except Exception:
                pass
            shutil.rmtree(local_temp, ignore_errors=True)
            return "", str(e)

    def run_flow(self, flow: Flow) -> Dict[str, Any]:
        db = SessionLocal()
        batch_id = None
        source_info = None
        downloaded_files = []
        local_temp_dir = None

        try:
            source_info = self.resolve_source_info(flow)

            if source_info["mode"] == "smb":
                remote_files, err = self._list_remote_files(source_info["smb_source_unc"])
                if err:
                    return {"success": False, "message": f"Error listando SMB {source_info['resolved_path']}: {err}"}
                if not remote_files:
                    return {"success": False, "message": f"No hay ficheros procesables en SMB: {source_info['resolved_path']}"}
                downloaded_files = remote_files
                local_temp_dir, err = self._download_from_smb(source_info["smb_source_unc"], remote_files)
                if err:
                    return {"success": False, "message": f"Error descargando ficheros SMB: {err}"}
                source_path = local_temp_dir
            else:
                source_path = source_info["resolved_path"]
                if not source_path or not os.path.exists(source_path):
                    return {"success": False, "message": f"Carpeta no encontrada: {source_path}"}
                local_files = []
                for root, _, files in os.walk(source_path):
                    for filename in files:
                        if filename.startswith('.') or not filename.lower().endswith(SUPPORTED_EXTENSIONS):
                            continue
                        rel_path = os.path.relpath(os.path.join(root, filename), source_path)
                        local_files.append(rel_path)
                if not local_files:
                    return {"success": False, "message": f"No hay ficheros procesables en: {source_path}"}
                downloaded_files = local_files

            ingestion_data = self.ingestion_service.ingest_batch(source_path)
            existing = source_batch_repo.get_by_sha256(db, ingestion_data["batch_sha256"])
            if existing and (existing.municipality_hint or "").upper() == flow.municipality.upper() and (existing.category_hint or "").upper() == flow.category.upper():
                try:
                    old_candidates = [c for c in content_candidate_repo.get_all(db) if c.batch_id == existing.id]
                    for c in old_candidates:
                        try:
                            canonical = canonical_content_repo.get_by_candidate_id(db, c.id)
                            if canonical:
                                canonical_content_repo.delete(db, id=canonical.id)
                        except Exception:
                            pass
                        content_candidate_repo.delete(db, id=c.id)
                    old_files = [f for f in source_file_repo.get_all(db) if f.batch_id == existing.id]
                    for f in old_files:
                        source_file_repo.delete(db, id=f.id)
                    source_batch_repo.delete(db, id=existing.id)
                except Exception as clean_err:
                    event_logger.log(db, EventLevel.WARNING, "CLEAN_DUPLICATE_FAILED", "FLOW", f"No se pudo limpiar lote duplicado {existing.id}: {clean_err}")
                    return {"success": False, "message": f"Lote duplicado. Error limpiando lote anterior: {clean_err}"}

            batch = source_batch_repo.create(db, obj_in={
                "external_name": ingestion_data["external_name"],
                "original_path": ingestion_data["original_path"],
                "working_path": ingestion_data["working_path"],
                "batch_sha256": ingestion_data["batch_sha256"],
                "municipality_hint": flow.municipality,
                "category_hint": flow.category,
                "status": BatchStatus.DETECTED
            })
            batch_id = batch.id

            source_files = []
            for file_data in ingestion_data["files"]:
                file_data["batch_id"] = batch.id
                source_files.append(source_file_repo.create(db, obj_in=file_data))

            event_logger.log(db, EventLevel.INFO, "BATCH_INGESTED", "FLOW", f"Flow {flow.name} ({source_info['resolved_path']})", batch_id=batch.id)
            source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.PROCESSING})

            docs = [f for f in source_files if f.extension in [".pdf", ".docx"]]
            imgs = [f for f in source_files if f.extension in [".jpg", ".jpeg", ".png"]]

            if not docs and not imgs:
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED, "error_message": "No hay documentos ni imagenes procesables"})
                return {"success": False, "message": "No se encontraron documentos validos tras la ingesion"}

            groups = self.grouping_orchestrator.group_batch(batch, source_files)
            if not groups:
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED, "error_message": "No se pudieron agrupar los contenidos"})
                return {"success": False, "message": "No se pudieron agrupar los contenidos del lote"}

            hints = {
                "municipality_hint": flow.municipality or "",
                "category_hint": flow.category or ""
            }

            from app.services.export.flow_export import FlowExporter
            exporter = FlowExporter()

            articles = []
            export_payloads = []
            image_uploads = []
            classifications = []
            candidate_statuses = []

            for group in groups:
                assigned_ids = [item.get("id") for item in group.assigned_files]
                assigned_files = [f for f in source_files if f.id in assigned_ids]
                group_docs = [f for f in assigned_files if f.extension in [".pdf", ".docx"]]
                group_imgs = [f for f in assigned_files if f.extension in [".jpg", ".jpeg", ".png"]]

                if not group_docs and not group_imgs:
                    continue

                candidate = content_candidate_repo.create(db, obj_in={
                    "batch_id": batch.id,
                    "candidate_key": group.candidate_key,
                    "grouping_strategy": group.strategy,
                    "grouping_confidence": group.confidence,
                    "status": CandidateStatus.CREATED
                })

                extractions = self.extraction_orchestrator.process_files(
                    [{"id": f.id, "path": f.working_path} for f in group_docs + group_imgs]
                )
                classification = self.classification_orchestrator.classify_candidate(group, extractions, hints)
                processed_images = self.image_processor.process_images(candidate, group_imgs)

                candidate_image_uploads = exporter.plan_image_uploads(flow.municipality, processed_images)
                public_image_map = {item.get("source_file_id", ""): item for item in candidate_image_uploads}
                editorial_images = []
                for image in processed_images:
                    mapped = public_image_map.get(str(image.source_file_id), {})
                    editorial_images.append(image.model_copy(update={
                        "optimized_path": mapped.get("optimized_public_url") or image.optimized_path,
                        "thumbnail_path": mapped.get("thumbnail_public_url") or image.thumbnail_path,
                    }))

                combined_text = "\n".join([e.cleaned_text for e in extractions])
                editorial = self.editorial_builder.build_editorial_content(classification, combined_text, editorial_images, {})

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

                if editorial.featured_image_ref:
                    try:
                        content_candidate_repo.update(db, db_obj=candidate, obj_in={"featured_source_file_id": editorial.featured_image_ref})
                    except Exception:
                        db.rollback()

                adapter = AdapterFactory.get_adapter(classification.category)
                adapter_result = adapter.build_payload(canonical)
                if adapter_result.raw_payload is not None:
                    export_payloads.append(adapter_result.raw_payload)

                if not adapter_result.is_ready_for_export:
                    canonical_content_repo.update(db, db_obj=canonical, obj_in={"requires_review": True})
                    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": CandidateStatus.REVIEW_REQUIRED})
                    candidate_statuses.append(CandidateStatus.REVIEW_REQUIRED)
                    event_logger.log(db, EventLevel.WARNING, "CANDIDATE_REVIEW_REQUIRED", "FLOW", "Validacion fallida", candidate_id=candidate.id)
                else:
                    content_candidate_repo.update(db, db_obj=candidate, obj_in={"status": CandidateStatus.EXPORTED})
                    candidate_statuses.append(CandidateStatus.EXPORTED)
                    event_logger.log(db, EventLevel.INFO, "CANDIDATE_EXPORTED", "FLOW", "Candidato exportado", candidate_id=candidate.id)

                image_uploads.extend(candidate_image_uploads)
                classifications.append({
                    "municipality": classification.municipality,
                    "category": classification.category,
                    "confidence": classification.classification_confidence,
                    "review_required": classification.requires_review,
                    "reasons": classification.review_reasons,
                    "candidate_key": group.candidate_key,
                })
                articles.append({
                    "title": editorial.final_title,
                    "summary": editorial.final_summary,
                    "body_html": editorial.final_body_html,
                    "images": [item.get("optimized_public_url") for item in candidate_image_uploads if item.get("optimized_public_url")],
                    "municipality": classification.municipality,
                    "category": classification.category,
                    "structured_fields": editorial.structured_fields,
                    "candidate_key": group.candidate_key,
                })

            if not articles:
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED, "error_message": "No se pudieron generar contenidos exportables"})
                return {"success": False, "message": "No se pudieron generar contenidos exportables"}

            if any(status == CandidateStatus.REVIEW_REQUIRED for status in candidate_statuses):
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.REVIEW_REQUIRED})
            else:
                source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FINISHED})

            self._move_processed_files(source_info, downloaded_files)

            return {
                "success": True,
                "message": f"Procesados {len(articles)} contenidos y {len(source_files)} ficheros de {flow.name}",
                "articles": articles,
                "classification": classifications[0] if classifications else None,
                "classifications": classifications,
                "export_payload": self._merge_export_payloads(export_payloads),
                "image_uploads": image_uploads,
                "files_count": len(source_files),
                "batch_id": str(batch.id)
            }

        except Exception as e:
            if batch_id:
                batch = source_batch_repo.get_by_id(db, batch_id)
                if batch:
                    source_batch_repo.update(db, db_obj=batch, obj_in={"status": BatchStatus.FAILED, "error_message": str(e)})
            event_logger.log(db, EventLevel.CRITICAL, "FLOW_ERROR", "FLOW", str(e), batch_id=batch_id)
            return {"success": False, "message": str(e)}
        finally:
            if local_temp_dir and os.path.exists(local_temp_dir):
                shutil.rmtree(local_temp_dir, ignore_errors=True)
            db.close()

    def build_export_payload(self, flow: Flow, articles: List[Dict[str, Any]], export_payload: Optional[Any] = None) -> Any:
        if export_payload is not None:
            return export_payload
        return {
            "municipality": flow.municipality,
            "category": flow.category,
            "generated_at": datetime.now().isoformat(),
            "flow_name": flow.name,
            "articles": articles
        }

    def generate_json(self, flow: Flow, articles: List[Dict[str, Any]], export_payload: Optional[Any] = None) -> str:
        data = self.build_export_payload(flow, articles, export_payload)
        return json.dumps(data, ensure_ascii=False, indent=2)

    def generate_csv(self, flow: Flow, articles: List[Dict[str, Any]], export_payload: Optional[Any] = None) -> str:
        data = self.build_export_payload(flow, articles, export_payload)
        rows = self._payload_to_csv_rows(data)
        if not rows:
            return ""

        headers: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in headers:
                    headers.append(key)

        buffer = StringIO()
        writer = csv.DictWriter(buffer, fieldnames=headers)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: self._serialize_csv_value(row.get(key)) for key in headers})
        return buffer.getvalue()

    def _payload_to_csv_rows(self, payload: Any) -> List[Dict[str, Any]]:
        if isinstance(payload, dict):
            if isinstance(payload.get("articles"), list) and all(isinstance(item, dict) for item in payload.get("articles", [])):
                return payload["articles"]

            if set(payload.keys()) >= {"source", "version", "adapter", "data"} and isinstance(payload.get("data"), dict):
                return [payload["data"]]

            if payload and all(isinstance(value, dict) for value in payload.values()):
                rows = []
                for root_key, value in payload.items():
                    row = dict(value)
                    if "ID" not in row and "id" not in row:
                        row["ID"] = root_key
                    rows.append(row)
                return rows

            return [payload]

        if isinstance(payload, list):
            if all(isinstance(item, dict) for item in payload):
                return payload
            return [{"value": item} for item in payload]

        return [{"value": payload}]

    def _serialize_csv_value(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _merge_export_payloads(self, payloads: List[Any]) -> Optional[Any]:
        if not payloads:
            return None
        if len(payloads) == 1:
            return payloads[0]

        if all(isinstance(payload, dict) for payload in payloads):
            merged: Dict[str, Any] = {}
            for payload in payloads:
                for key, value in payload.items():
                    final_key = key
                    suffix = 2
                    while final_key in merged:
                        final_key = f"{key}_{suffix}"
                        suffix += 1
                    merged[final_key] = value
            return merged

        if all(isinstance(payload, list) for payload in payloads):
            merged_list: List[Any] = []
            for payload in payloads:
                merged_list.extend(payload)
            return merged_list

        return payloads

    def _move_processed_files(self, source_info: Dict[str, Any], filenames: List[str]) -> None:
        try:
            from app.services.export.flow_export import FlowExporter
            exporter = FlowExporter()
            source_path = source_info.get("resolved_path", "")
            if source_info["mode"] == "smb" and source_info.get("smb_source_unc"):
                ok, msg = exporter._move_smb_processed(source_info["smb_source_unc"], filenames)
            elif source_info["mode"] == "local" and source_path:
                ok, msg = exporter._move_local_processed(source_path, filenames)
            else:
                return
            if not ok:
                event_logger.log(SessionLocal(), EventLevel.WARNING, "MOVE_FAILED", "FLOW", msg)
        except Exception as e:
            event_logger.log(SessionLocal(), EventLevel.WARNING, "MOVE_ERROR", "FLOW", str(e))
