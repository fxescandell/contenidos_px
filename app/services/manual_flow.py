import os
import shutil
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.flow_models import Flow
from app.db.models import ManualExportDraft, ManualExportItem
from app.services.export.flow_export import FlowExporter
from app.services.pipeline.flow_service import FlowService
from app.services.settings.service import SettingsResolver


ALLOWED_EXTENSIONS = {".pdf", ".docx", ".md", ".markdown", ".txt", ".jpg", ".jpeg", ".png"}


class ManualFlowService:
    def __init__(self):
        self.flow_service = FlowService(settings)
        self.exporter = FlowExporter()

    def _base_temp_dir(self) -> str:
        base = SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp"
        return os.path.join(base, "manual_flow_drafts")

    def _draft_dir(self, draft_id: str) -> str:
        return os.path.join(self._base_temp_dir(), draft_id)

    def _incoming_dir(self, draft_id: str) -> str:
        return os.path.join(self._draft_dir(draft_id), "incoming")

    def _accepted_dir(self, draft_id: str) -> str:
        return os.path.join(self._draft_dir(draft_id), "accepted")

    def _safe_filename(self, filename: str) -> str:
        name = os.path.basename(filename or "")
        return name.replace("..", "_")

    def _extension_allowed(self, filename: str) -> bool:
        ext = os.path.splitext(filename.lower())[1]
        return ext in ALLOWED_EXTENSIONS

    def get_or_create_open_draft(self, db: Session, flow: Flow) -> ManualExportDraft:
        draft = (
            db.query(ManualExportDraft)
            .filter(ManualExportDraft.flow_id == flow.id, ManualExportDraft.status == "OPEN")
            .order_by(ManualExportDraft.updated_at.desc())
            .first()
        )
        if draft:
            return draft

        draft = ManualExportDraft(flow_id=flow.id, status="OPEN")
        db.add(draft)
        db.commit()
        db.refresh(draft)
        return draft

    def get_draft_state(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        incoming_files = self.list_incoming_files(str(draft.id))
        items = (
            db.query(ManualExportItem)
            .filter(ManualExportItem.draft_id == draft.id)
            .order_by(ManualExportItem.sequence.asc())
            .all()
        )

        return {
            "draft_id": str(draft.id),
            "status": draft.status,
            "pending": {
                "exists": bool(draft.pending_payload_json),
                "batch_id": draft.pending_batch_id,
                "summary": draft.pending_summary,
                "created_at": draft.pending_created_at.isoformat() if draft.pending_created_at else None,
                "files": draft.pending_files_json or [],
            },
            "incoming_files": incoming_files,
            "verified_items": [
                {
                    "id": str(item.id),
                    "sequence": item.sequence,
                    "batch_id": item.source_batch_id,
                    "summary": item.summary,
                    "files": item.files_json or [],
                    "created_at": item.created_at.isoformat() if item.created_at else None,
                }
                for item in items
            ],
            "verified_count": len(items),
            "final_export_message": draft.final_export_message,
            "finalized_at": draft.finalized_at.isoformat() if draft.finalized_at else None,
        }

    def list_incoming_files(self, draft_id: str) -> List[str]:
        incoming = self._incoming_dir(draft_id)
        if not os.path.exists(incoming):
            return []
        files: List[str] = []
        for root, _dirs, names in os.walk(incoming):
            for name in names:
                rel = os.path.relpath(os.path.join(root, name), incoming)
                files.append(rel)
        files.sort()
        return files

    async def upload_files(self, db: Session, flow: Flow, files: List[UploadFile]) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        incoming = self._incoming_dir(str(draft.id))
        os.makedirs(incoming, exist_ok=True)

        saved: List[str] = []
        rejected: List[str] = []

        for upload in files:
            filename = self._safe_filename(upload.filename or "")
            if not filename:
                rejected.append("(nombre vacio)")
                continue
            if not self._extension_allowed(filename):
                rejected.append(filename)
                continue

            final_name = filename
            final_path = os.path.join(incoming, final_name)
            index = 2
            while os.path.exists(final_path):
                base, ext = os.path.splitext(filename)
                final_name = f"{base}_{index}{ext}"
                final_path = os.path.join(incoming, final_name)
                index += 1

            with open(final_path, "wb") as target:
                shutil.copyfileobj(upload.file, target)
            saved.append(final_name)

        db.query(ManualExportDraft).filter(ManualExportDraft.id == draft.id).update({"updated_at": datetime.now()})
        db.commit()

        return {
            "draft_id": str(draft.id),
            "saved": saved,
            "rejected": rejected,
            "incoming_files": self.list_incoming_files(str(draft.id)),
        }

    def run_preview(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        incoming = self._incoming_dir(str(draft.id))
        incoming_files = self.list_incoming_files(str(draft.id))
        if not incoming_files:
            return {"success": False, "message": "No hay archivos cargados para previsualizar."}

        return self.run_preview_from_source(db, flow, incoming, incoming_files)

    def get_pending_preview(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        if not draft.pending_payload_json:
            return {"success": False, "message": "No hay previsualizacion pendiente para mostrar."}

        preview_json = self.flow_service.generate_json(
            flow,
            draft.pending_articles_json or [],
            draft.pending_payload_json,
        )

        return {
            "success": True,
            "draft_id": str(draft.id),
            "batch_id": draft.pending_batch_id,
            "preview_json": preview_json,
            "summary": draft.pending_summary,
            "pending_files": draft.pending_files_json or [],
            "created_at": draft.pending_created_at.isoformat() if draft.pending_created_at else None,
        }

    def run_preview_from_source(
        self,
        db: Session,
        flow: Flow,
        source_path: str,
        source_files: List[str],
    ) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)

        source_info = {
            "mode": "local",
            "resolved_path": source_path,
            "local_temp_dir": None,
            "smb_source_unc": None,
            "relative_source_path": None,
        }

        result = self.flow_service.run_flow(flow, source_info_override=source_info, skip_move_processed=True)
        if not result.get("success"):
            return result

        export_payload = result.get("export_payload")
        preview_json = self.flow_service.generate_json(flow, result.get("articles", []), export_payload)

        draft.pending_batch_id = result.get("batch_id")
        draft.pending_payload_json = export_payload
        draft.pending_articles_json = result.get("articles", [])
        draft.pending_files_json = source_files
        draft.pending_summary = result.get("message")
        draft.pending_created_at = datetime.now()
        draft.updated_at = datetime.now()
        db.commit()
        db.refresh(draft)

        return {
            "success": True,
            "draft_id": str(draft.id),
            "batch_id": result.get("batch_id"),
            "message": result.get("message"),
            "preview_json": preview_json,
            "articles_count": len(result.get("articles", [])),
            "pending_files": source_files,
        }

    def add_verified_item(
        self,
        db: Session,
        flow: Flow,
        payload: Dict[str, Any],
        articles: List[Dict[str, Any]],
        files: List[str],
        summary: Optional[str],
        source_batch_id: Optional[str],
    ) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        current_max = (
            db.query(ManualExportItem)
            .filter(ManualExportItem.draft_id == draft.id)
            .order_by(ManualExportItem.sequence.desc())
            .first()
        )
        next_seq = (current_max.sequence + 1) if current_max else 1

        item = ManualExportItem(
            draft_id=draft.id,
            sequence=next_seq,
            source_batch_id=source_batch_id,
            payload_json=payload,
            articles_json=articles or [],
            files_json=files or [],
            summary=summary,
        )
        db.add(item)
        draft.updated_at = datetime.now()
        db.commit()
        return {"success": True, "sequence": next_seq, "draft_id": str(draft.id)}

    def accept_pending_preview(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        if not draft.pending_payload_json:
            return {"success": False, "message": "No hay previsualizacion pendiente para aceptar."}

        current_max = (
            db.query(ManualExportItem)
            .filter(ManualExportItem.draft_id == draft.id)
            .order_by(ManualExportItem.sequence.desc())
            .first()
        )
        next_seq = (current_max.sequence + 1) if current_max else 1

        item = ManualExportItem(
            draft_id=draft.id,
            sequence=next_seq,
            source_batch_id=draft.pending_batch_id,
            payload_json=draft.pending_payload_json,
            articles_json=draft.pending_articles_json or [],
            files_json=draft.pending_files_json or [],
            summary=draft.pending_summary,
        )
        db.add(item)

        self._archive_and_clear_incoming_files(str(draft.id), next_seq)
        self._clear_pending(draft)
        draft.updated_at = datetime.now()
        db.commit()

        return {"success": True, "message": "Previsualizacion aceptada y anadida al borrador.", "sequence": next_seq}

    def discard_pending_preview(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        if not draft.pending_payload_json:
            return {"success": False, "message": "No hay previsualizacion pendiente para descartar."}

        self._clear_incoming_files(str(draft.id))
        self._clear_pending(draft)
        draft.updated_at = datetime.now()
        db.commit()
        return {"success": True, "message": "Previsualizacion descartada."}

    def finalize_export(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)
        items = (
            db.query(ManualExportItem)
            .filter(ManualExportItem.draft_id == draft.id)
            .order_by(ManualExportItem.sequence.asc())
            .all()
        )
        if not items:
            return {"success": False, "message": "No hay previsualizaciones verificadas para exportar."}

        payloads = [item.payload_json for item in items if item.payload_json is not None]
        merged_payload = self.flow_service._merge_export_payloads(payloads)
        if merged_payload is None:
            return {"success": False, "message": "No se pudo construir el payload final."}

        final_json = self.flow_service.generate_json(flow, [], merged_payload)
        final_csv = self.flow_service.generate_csv(flow, [], merged_payload)

        ok_json, msg_json = self.exporter.upload_to_outfolder(flow.municipality, flow.output_filename, final_json, content_label="JSON")
        ok_csv = True
        msg_csv = ""
        if final_csv:
            base_name, _ext = os.path.splitext(flow.output_filename)
            csv_name = f"{base_name}.csv" if base_name else f"{flow.output_filename}.csv"
            ok_csv, msg_csv = self.exporter.upload_to_outfolder(flow.municipality, csv_name, final_csv, content_label="CSV")

        success = bool(ok_json and ok_csv)
        message = msg_json if not msg_csv else f"{msg_json} | {msg_csv}"

        draft.final_export_message = message
        draft.final_export_path = message
        draft.finalized_at = datetime.now() if success else draft.finalized_at
        draft.updated_at = datetime.now()
        if draft.pending_payload_json:
            self._clear_pending(draft)
        db.commit()

        return {
            "success": success,
            "message": message,
            "items_exported": len(items),
        }

    def reset_draft(self, db: Session, flow: Flow) -> Dict[str, Any]:
        draft = self.get_or_create_open_draft(db, flow)

        removed_items = (
            db.query(ManualExportItem)
            .filter(ManualExportItem.draft_id == draft.id)
            .delete(synchronize_session=False)
        )

        self._clear_pending(draft)
        self._clear_incoming_files(str(draft.id))

        accepted_root = self._accepted_dir(str(draft.id))
        if os.path.exists(accepted_root):
            shutil.rmtree(accepted_root, ignore_errors=True)

        draft.final_export_message = None
        draft.final_export_path = None
        draft.finalized_at = None
        draft.updated_at = datetime.now()
        db.commit()

        return {
            "success": True,
            "message": "Borrador manual reiniciado correctamente.",
            "removed_items": int(removed_items or 0),
            "draft_id": str(draft.id),
        }

    def _clear_pending(self, draft: ManualExportDraft) -> None:
        draft.pending_batch_id = None
        draft.pending_payload_json = None
        draft.pending_articles_json = None
        draft.pending_files_json = None
        draft.pending_summary = None
        draft.pending_created_at = None

    def _clear_incoming_files(self, draft_id: str) -> None:
        incoming = self._incoming_dir(draft_id)
        if os.path.exists(incoming):
            shutil.rmtree(incoming, ignore_errors=True)
        os.makedirs(incoming, exist_ok=True)

    def _archive_and_clear_incoming_files(self, draft_id: str, sequence: int) -> None:
        incoming = self._incoming_dir(draft_id)
        if not os.path.exists(incoming):
            os.makedirs(incoming, exist_ok=True)
            return

        accepted_root = self._accepted_dir(draft_id)
        os.makedirs(accepted_root, exist_ok=True)
        archive_path = os.path.join(accepted_root, f"item_{sequence}")
        if os.path.exists(archive_path):
            shutil.rmtree(archive_path, ignore_errors=True)
        shutil.move(incoming, archive_path)
        os.makedirs(incoming, exist_ok=True)
