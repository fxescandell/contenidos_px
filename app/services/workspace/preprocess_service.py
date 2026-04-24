import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from uuid import uuid4

import requests

from app.db.flow_models import Flow
from app.services.extraction.orchestrator import ExtractionOrchestrator
from app.services.settings.service import SettingsResolver


class PreprocessWorkspaceService:
    def __init__(self):
        self.extractor = ExtractionOrchestrator()

    def create_session(self) -> Dict[str, Any]:
        session_id = str(uuid4())
        root = self._session_root(session_id)
        (root / "incoming").mkdir(parents=True, exist_ok=True)
        (root / "generated").mkdir(parents=True, exist_ok=True)
        (root / "package").mkdir(parents=True, exist_ok=True)

        state = {
            "id": session_id,
            "created_at": datetime.now().isoformat(),
            "incoming_files": [],
            "analysis": {
                "files_processed": 0,
                "combined_text": "",
                "items": [],
                "warnings": [],
            },
            "generated_markdown": "",
            "generated_markdown_path": "",
            "web_enrichment": {
                "enabled": False,
                "query": "",
                "summary": "",
                "source": "",
            },
            "package_path": "",
            "published_input_path": "",
            "municipality": "",
            "category": "",
            "flow_id": "",
            "updated_at": datetime.now().isoformat(),
        }
        self._save_state(session_id, state)
        return state

    def get_state(self, session_id: str) -> Dict[str, Any]:
        return self._load_state(session_id)

    def upload_files(self, session_id: str, uploads: List[Any]) -> Dict[str, Any]:
        state = self._load_state(session_id)
        incoming = self._session_root(session_id) / "incoming"
        incoming.mkdir(parents=True, exist_ok=True)

        saved: List[str] = []
        for upload in uploads:
            original = self._safe_name(getattr(upload, "filename", "") or "")
            if not original:
                continue
            target = incoming / original
            target = self._resolve_unique_path(target)
            with open(target, "wb") as out:
                shutil.copyfileobj(upload.file, out)
            saved.append(str(target.relative_to(incoming)))

        state["incoming_files"] = self._list_relative_files(incoming)
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "saved": saved,
            "incoming_files": state["incoming_files"],
        }

    def analyze(self, session_id: str) -> Dict[str, Any]:
        state = self._load_state(session_id)
        incoming = self._session_root(session_id) / "incoming"
        files = self._list_relative_files(incoming)
        if not files:
            return {"success": False, "message": "No hay archivos para analizar."}

        infos = []
        for rel in files:
            abs_path = str(incoming / rel)
            infos.append({"path": abs_path, "id": str(uuid4())})

        results = self.extractor.process_files(infos)
        combined_chunks: List[str] = []
        items: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for rel, result in zip(files, results):
            cleaned = str(getattr(result, "cleaned_text", "") or "").strip()
            raw = str(getattr(result, "raw_text", "") or "").strip()
            method = getattr(getattr(result, "method", None), "value", str(getattr(result, "method", "")))
            if cleaned:
                combined_chunks.append(cleaned)
            elif raw:
                combined_chunks.append(raw)

            marker_text = cleaned or raw
            if "OCR deshabilitado" in marker_text or "Error OCR" in marker_text or "sin texto reconocible" in marker_text.lower():
                warnings.append(f"{rel}: {marker_text[:180]}")

            items.append(
                {
                    "file": rel,
                    "method": method,
                    "confidence": float(getattr(result, "confidence", 0.0) or 0.0),
                    "text_preview": marker_text[:500],
                }
            )

        combined_text = "\n\n".join(chunk for chunk in combined_chunks if chunk).strip()
        state["analysis"] = {
            "files_processed": len(files),
            "combined_text": combined_text,
            "items": items,
            "warnings": warnings,
        }
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "analysis": state["analysis"],
            "message": f"Analizados {len(files)} archivo(s).",
        }

    def generate_markdown(
        self,
        session_id: str,
        municipality: str,
        category: str,
        flow_id: str,
        enable_web_enrichment: bool = False,
        web_query: str = "",
    ) -> Dict[str, Any]:
        state = self._load_state(session_id)
        analysis = state.get("analysis") or {}
        source_text = str(analysis.get("combined_text", "") or "").strip()
        if not source_text:
            return {"success": False, "message": "No hay texto analizado. Ejecuta 'Analizar' antes de generar markdown."}

        title = self._guess_title(source_text, category)
        summary = self._guess_summary(source_text)
        body = self._guess_body(source_text)

        web_summary = ""
        web_source = ""
        if enable_web_enrichment and web_query.strip():
            web_summary, web_source = self._fetch_web_context(web_query.strip())

        md = [
            f"# {title}",
            "",
            "## Resum",
            summary,
            "",
            "## Cos",
            body,
            "",
            "## Dades clau",
            f"- Municipi: {municipality or 'GENERAL'}",
            f"- Categoria: {category or 'ALTRES'}",
            "",
            "## Notes d'origen",
            "- Document preparat en fase de preprocesat per facilitar el pipeline de flujos.",
        ]
        if web_summary:
            md += [
                "",
                "## Context web addicional (revisar abans de publicar)",
                web_summary,
                "",
                f"Font: {web_source}",
            ]

        markdown = "\n".join(md).strip() + "\n"
        generated_path = self._session_root(session_id) / "generated" / "contenido.md"
        generated_path.parent.mkdir(parents=True, exist_ok=True)
        generated_path.write_text(markdown, encoding="utf-8")

        state["municipality"] = municipality or ""
        state["category"] = category or ""
        state["flow_id"] = flow_id or ""
        state["generated_markdown"] = markdown
        state["generated_markdown_path"] = str(generated_path)
        state["web_enrichment"] = {
            "enabled": bool(enable_web_enrichment),
            "query": web_query,
            "summary": web_summary,
            "source": web_source,
        }
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "markdown": markdown,
            "markdown_path": str(generated_path),
            "message": "Markdown generado correctamente.",
        }

    def package_article(self, session_id: str, article_folder_name: str = "") -> Dict[str, Any]:
        state = self._load_state(session_id)
        markdown_path = Path(str(state.get("generated_markdown_path") or ""))
        if not markdown_path.exists():
            return {"success": False, "message": "No hay markdown generado. Genera markdown antes de empaquetar."}

        incoming = self._session_root(session_id) / "incoming"
        package_root = self._session_root(session_id) / "package"
        package_root.mkdir(parents=True, exist_ok=True)

        name = self._safe_name(article_folder_name or "") or f"article_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        article_dir = package_root / name
        article_dir = self._resolve_unique_path(article_dir)
        article_dir.mkdir(parents=True, exist_ok=True)

        for rel in self._list_relative_files(incoming):
            src = incoming / rel
            dst = article_dir / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)

        shutil.copy2(markdown_path, article_dir / "contenido.md")

        state["package_path"] = str(article_dir)
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "package_path": str(article_dir),
            "message": "Paquete preparado correctamente.",
        }

    def publish_to_flow_input(self, session_id: str, flow: Flow) -> Dict[str, Any]:
        state = self._load_state(session_id)
        package_path = Path(str(state.get("package_path") or ""))
        if not package_path.exists() or not package_path.is_dir():
            return {"success": False, "message": "No hay paquete preparado. Ejecuta 'Empaquetar' antes de publicar."}

        active_mode = (SettingsResolver.get("active_source_mode", "smb") or "smb").lower()
        if active_mode != "local":
            return {
                "success": False,
                "message": "La publicacion directa del preprocesado solo esta disponible en modo local en esta fase.",
            }

        destination_root = self._resolve_local_flow_input_path(flow)
        if not destination_root:
            return {"success": False, "message": "No se pudo resolver la carpeta de entrada del flujo."}

        os.makedirs(destination_root, exist_ok=True)
        target = Path(destination_root) / package_path.name
        if target.exists():
            target = Path(self._resolve_unique_path(target))
        shutil.copytree(package_path, target)

        state["published_input_path"] = str(target)
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "published_input_path": str(target),
            "message": "Paquete publicado en la carpeta de entrada del flujo.",
        }

    def _resolve_local_flow_input_path(self, flow: Flow) -> str:
        local_base = str(SettingsResolver.get("hot_folder_local_path") or "").strip()
        if not local_base:
            return ""

        municipality_base = self._resolve_local_municipality_folder(flow.municipality)
        source_folder = str(flow.source_folder or "").strip("/")
        parts = [local_base, municipality_base, source_folder]
        return os.path.join(*[part for part in parts if part])

    def _resolve_local_municipality_folder(self, municipality: str) -> str:
        raw = SettingsResolver.get("hotfolder_local_folders", "[]")
        try:
            folders = json.loads(raw) if isinstance(raw, str) else raw
        except Exception:
            folders = []
        if isinstance(folders, list):
            for item in folders:
                if str(item.get("name", "")).upper() == str(municipality or "").upper():
                    return str(item.get("base_path") or "").strip("/")
        return str(municipality or "general").lower()

    def _fetch_web_context(self, query: str) -> tuple[str, str]:
        url = f"https://es.wikipedia.org/api/rest_v1/page/summary/{quote(query)}"
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            payload = response.json()
            extract = str(payload.get("extract") or "").strip()
            source = str(payload.get("content_urls", {}).get("desktop", {}).get("page") or url)
            return extract[:1800], source
        except Exception:
            return "", ""

    def _guess_title(self, text: str, category: str) -> str:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        first = lines[0] if lines else ""
        first = re.sub(r"\s+", " ", first)
        if first and len(first) <= 110:
            return first
        return f"Esborrany {category or 'article'}"

    def _guess_summary(self, text: str) -> str:
        cleaned = re.sub(r"\s+", " ", text).strip()
        if not cleaned:
            return "Pendent de completar amb informacio editorial."
        sentences = re.split(r"(?<=[.!?])\s+", cleaned)
        summary = " ".join(sentences[:2]).strip()
        return summary[:400] if summary else cleaned[:400]

    def _guess_body(self, text: str) -> str:
        cleaned = re.sub(r"\r\n", "\n", text)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        return cleaned[:8000]

    def _session_root(self, session_id: str) -> Path:
        base = Path(str(SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp"))
        root = base / "workspace_preprocess" / session_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _state_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "session.json"

    def _load_state(self, session_id: str) -> Dict[str, Any]:
        path = self._state_path(session_id)
        if not path.exists():
            raise ValueError("Sesion de preprocesado no encontrada")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, session_id: str, state: Dict[str, Any]) -> None:
        path = self._state_path(session_id)
        path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _list_relative_files(self, root: Path) -> List[str]:
        if not root.exists():
            return []
        files: List[str] = []
        for path in root.rglob("*"):
            if path.is_file():
                files.append(str(path.relative_to(root)).replace("\\", "/"))
        files.sort()
        return files

    def _safe_name(self, value: str) -> str:
        name = os.path.basename(str(value or "").strip())
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        return name.strip("._")

    def _resolve_unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        has_suffix = bool(path.suffix)
        base = path.with_suffix("") if has_suffix else path
        ext = path.suffix if has_suffix else ""
        suffix = 2
        while True:
            candidate = Path(f"{base}_{suffix}{ext}")
            if not candidate.exists():
                return candidate
            suffix += 1


preprocess_workspace_service = PreprocessWorkspaceService()
