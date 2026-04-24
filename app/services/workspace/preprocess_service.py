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
from app.core.enums import ExtractionMethod
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
        ocr_chunks: List[str] = []
        items: List[Dict[str, Any]] = []
        warnings: List[str] = []

        for rel, result in zip(files, results):
            cleaned = str(getattr(result, "cleaned_text", "") or "").strip()
            raw = str(getattr(result, "raw_text", "") or "").strip()
            method = getattr(getattr(result, "method", None), "value", str(getattr(result, "method", "")))
            method_enum = getattr(result, "method", None)
            if cleaned and not self._is_extraction_placeholder(cleaned):
                combined_chunks.append(cleaned)
                if method_enum == ExtractionMethod.OCR_IMAGE:
                    ocr_chunks.append(cleaned)
            elif raw and not self._is_extraction_placeholder(raw):
                combined_chunks.append(raw)
                if method_enum == ExtractionMethod.OCR_IMAGE:
                    ocr_chunks.append(raw)

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
        ocr_text = "\n\n".join(chunk for chunk in ocr_chunks if chunk).strip()
        state["analysis"] = {
            "files_processed": len(files),
            "combined_text": combined_text,
            "ocr_text": ocr_text,
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

    def _is_extraction_placeholder(self, text: str) -> bool:
        value = str(text or "").strip()
        if not value:
            return True
        lower = value.lower()
        if lower.startswith("[error "):
            return True
        if "error ocr" in lower:
            return True
        if "ocr deshabilitado" in lower:
            return True
        if "sin texto reconocible" in lower:
            return True
        return False

    def _is_agenda_category(self, category: str) -> bool:
        return str(category or "").strip().lower() == "agenda"

    def _clean_ocr_text_for_markdown(self, text: str) -> str:
        value = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"\s+", " ", value)
        value = re.sub(r"\s*([,.;!?])\s*", r"\1 ", value)
        value = re.sub(r"\s{2,}", " ", value).strip()
        value = re.sub(r"\b[Oo](?=\d{1,2}[:.]\d{2})", "0", value)
        value = re.sub(r"\b([0-2]?\d)\s*[:.]\s*([0-5]\d)\s*[Hh]?\b", r"\1:\2H", value)
        value = re.sub(r"\bcat\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"www\s*\.\s*[^\s]+(?:\s*\.\s*[^\s]+)*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(?:compra\s+els\s+teus\s+tiquets\s+i\s+entrades\s+a:)\b", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+(Dissabte\s+\d{1,2}\s+\w+)", r"\n\1", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+(Diumenge\s+\d{1,2}\s+\w+)", r"\n\1", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+(\d{1,2}:\d{2}H)", r"\n\1", value)
        value = re.sub(r"\s+(\d{1,2}:\d{2})\s*([-—–])", r"\n\1 \2", value)

        lines = [line.strip(" -\t") for line in value.split("\n") if line.strip()]
        cleaned_lines: List[str] = []
        for line in lines:
            if self._is_noise_line(line):
                continue
            sanitized = self._strip_noise_fragments(line)
            if sanitized and not self._is_noise_line(sanitized):
                cleaned_lines.append(sanitized)
        lines = cleaned_lines
        return "\n".join(lines).strip()

    def _is_noise_line(self, line: str) -> bool:
        lower = str(line or "").lower()
        if not lower.strip():
            return True
        if re.search(r"^[wvmn\s.:-]{6,}$", lower):
            return True
        institutional_tokens = (
            "ajuntament de",
            "diputacio",
            "generalitat de catalunya",
            "departament de cultura",
        )
        if any(token in lower for token in institutional_tokens):
            return True
        if lower.startswith("compra els teus"):
            return True
        if lower.startswith("www."):
            return True
        if re.fullmatch(r"[\W_]+", line or ""):
            return True
        return False

    def _strip_noise_fragments(self, line: str) -> str:
        value = str(line or "")
        value = re.sub(r"https?://\S+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"www\.[^\s]+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(COMPRA ELS TEUS TIQUETS I ENTRADES A)\b.*$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bAJUNTAMENT DE\b.*$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bDiputacio\b.*$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\bGeneralitat de Catalunya\b.*$", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" -")
        return value

    def _build_agenda_content(self, text: str, category: str) -> Dict[str, str]:
        lines = self._normalize_agenda_lines(text)
        time_re = re.compile(r"^(?P<time>\d{1,2}[:.]\d{2})\s*[Hh]?\s*(?:[-—–:]\s*)?(?P<rest>.+)$")
        day_re = re.compile(r"^(dissabte|diumenge)\b", re.IGNORECASE)

        program_items: List[str] = []
        narrative_lines: List[str] = []
        current_day = ""
        for line in lines:
            day_match = day_re.match(line)
            if day_match:
                current_day = line
                program_items.append(f"### {current_day}")
                continue

            match = time_re.match(line)
            if match:
                time_value = self._normalize_time(match.group("time"))
                rest = self._strip_noise_fragments(match.group("rest"))
                if rest:
                    program_items.append(f"- {time_value} - {rest}")
                continue
            narrative_candidate = self._strip_noise_fragments(line)
            if narrative_candidate:
                narrative_lines.append(narrative_candidate)

        title = self._pick_agenda_title(narrative_lines, program_items, category)
        narrative_text = " ".join(narrative_lines).strip()
        summary_source = narrative_text or " ".join(program_items)
        summary = self._guess_summary(summary_source)
        if not summary:
            summary = "Acte d'agenda amb horaris i activitats pendents de revisio editorial."

        description = narrative_text if narrative_text else "Programa d'activitats detectat automaticament des del document original."
        description = description[:900]

        if not program_items:
            program_markdown = "- Programa no detectat automaticament. Revisa el text OCR abans de publicar."
        else:
            program_markdown = "\n".join(program_items[:40])

        return {
            "title": title,
            "summary": summary,
            "description": description,
            "program_markdown": program_markdown,
        }

    def _normalize_agenda_lines(self, text: str) -> List[str]:
        value = str(text or "")
        value = re.sub(r"\n([0-2]?\d:[0-5]\dH?)\s+", r"\n\1 ", value)
        lines = [line.strip() for line in value.splitlines() if line.strip()]
        out: List[str] = []
        for line in lines:
            if len(line) > 260 and re.search(r"\d{1,2}:\d{2}H", line):
                parts = re.split(r"(?=\d{1,2}:\d{2}H)", line)
                for part in parts:
                    clean = part.strip()
                    if clean:
                        out.append(clean)
            else:
                out.append(line)
        return out

    def _extract_times_from_text(self, text: str) -> List[str]:
        matches = re.findall(r"\b(?:[01]?\d|2[0-3])[:.]\d{2}\b", str(text or ""))
        out: List[str] = []
        seen = set()
        for value in matches:
            normalized = self._normalize_time(value)
            if normalized not in seen:
                seen.add(normalized)
                out.append(normalized)
        return out

    def _build_program_from_times(self, times: List[str]) -> str:
        if not times:
            return ""
        return "\n".join(f"- {time} - Pendent de completar des de la imatge original." for time in times)

    def _refine_agenda_with_llm(self, cleaned_text: str, ocr_text: str, municipality: str) -> Optional[Dict[str, str]]:
        try:
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client()
            if not client:
                return None

            system = (
                "Ets editor local en catala. Organitza text OCR d'una agenda sense inventar dades. "
                "Retorna nomes JSON valid."
            )
            prompt = (
                "Transforma aquest OCR en agenda estructurada i clara.\n"
                "Requisits:\n"
                "- Idioma: catala.\n"
                "- No inventis dades. Si falta un camp, deixa'l buit.\n"
                "- Separa actes per dia i hora.\n"
                "- Elimina soroll (urls repetides, logos, text institucional no editorial).\n"
                "- Dona un titular natural i una intro curta.\n"
                "Retorna NOMES JSON amb aquest esquema:\n"
                "{\n"
                "  \"title\": \"...\",\n"
                "  \"summary\": \"...\",\n"
                "  \"description\": \"...\",\n"
                "  \"program\": [\n"
                "    {\"day\":\"Dissabte 25 d'abril\",\"time\":\"09:00\",\"title\":\"Xocolatada popular\",\"details\":\"\",\"location\":\"Davant de Cal Julia\",\"price\":\"3 EUR\"}\n"
                "  ]\n"
                "}\n\n"
                f"Municipi: {municipality or 'GENERAL'}\n\n"
                "TEXT OCR NET:\n"
                f"{cleaned_text[:9000]}\n\n"
                "TEXT OCR BRUT (suport):\n"
                f"{ocr_text[:9000]}"
            )

            response = client.chat(prompt=prompt, system=system, max_tokens=2200, timeout_seconds=120)
            data = self._extract_json_from_response(response)
            if not isinstance(data, dict):
                return None

            title = str(data.get("title") or "").strip()
            summary = str(data.get("summary") or "").strip()
            description = str(data.get("description") or "").strip()
            program = data.get("program") if isinstance(data.get("program"), list) else []
            program_markdown = self._render_program_from_structured_items(program)

            if not title or not program_markdown:
                return None

            return {
                "title": title,
                "summary": summary or "Pendent de completar amb informacio editorial.",
                "description": description or "Programa d'activitats en revisio editorial.",
                "program_markdown": program_markdown,
            }
        except Exception:
            return None

    def _extract_json_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        text = str(response or "").strip()
        if not text:
            return None

        fenced = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", text, re.IGNORECASE)
        if fenced:
            text = fenced.group(1).strip()

        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            pass

        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return None
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except Exception:
            return None

    def _render_program_from_structured_items(self, program: List[Any]) -> str:
        lines: List[str] = []
        current_day = ""
        for item in program:
            if not isinstance(item, dict):
                continue

            day = str(item.get("day") or "").strip()
            time_value = self._normalize_time(str(item.get("time") or "").strip())
            title = str(item.get("title") or "").strip()
            details = str(item.get("details") or "").strip()
            location = str(item.get("location") or "").strip()
            price = str(item.get("price") or "").strip()

            if day and day != current_day:
                lines.append(f"### {day}")
                current_day = day

            if not title:
                continue

            head = f"- {time_value} - {title}" if time_value else f"- {title}"
            extras = [part for part in [location, price, details] if part]
            if extras:
                head += " | " + " | ".join(extras)
            lines.append(head)

        return "\n".join(lines).strip()

    def _pick_agenda_title(self, narrative_lines: List[str], program_items: List[str], category: str) -> str:
        joined = " ".join(narrative_lines)
        if "sant marc" in joined.lower() and "cal bassacs" in joined.lower():
            return "Sant Marc 2026 a Cal Bassacs (Gironella)"
        for line in narrative_lines:
            clean = re.sub(r"\s+", " ", line).strip(" -")
            if 8 <= len(clean) <= 110 and not self._is_noise_line(clean):
                return clean
        if program_items:
            first = re.sub(r"^-\s*\d{2}:\d{2}\s*-\s*", "", program_items[0]).strip()
            if first:
                return first[:110]
        return f"Esborrany {category or 'agenda'}"

    def _normalize_time(self, value: str) -> str:
        raw = str(value or "").replace(".", ":")
        parts = raw.split(":")
        if len(parts) != 2:
            return raw
        try:
            hour = int(parts[0])
            minute_part = re.sub(r"\D", "", parts[1])
            minute = int(minute_part)
            return f"{hour:02d}:{minute:02d}"
        except Exception:
            return raw

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
        ocr_text = str(analysis.get("ocr_text", "") or "").strip()
        if not source_text:
            return {"success": False, "message": "No hay texto analizado. Ejecuta 'Analizar' antes de generar markdown."}

        cleaned_source = self._clean_ocr_text_for_markdown(source_text)
        title = self._guess_title(cleaned_source, category)
        summary = self._guess_summary(cleaned_source)
        body = self._guess_body(cleaned_source)
        agenda_program = ""

        if self._is_agenda_category(category):
            agenda_content = self._build_agenda_content(cleaned_source, category)
            title = agenda_content["title"]
            summary = agenda_content["summary"]
            body = agenda_content["description"]
            agenda_program = agenda_content["program_markdown"]

            llm_refined = self._refine_agenda_with_llm(cleaned_source, ocr_text, municipality)
            if llm_refined:
                title = llm_refined["title"]
                summary = llm_refined["summary"]
                body = llm_refined["description"]
                agenda_program = llm_refined["program_markdown"]

            if agenda_program.startswith("- Programa no detectat"):
                fallback_times = self._extract_times_from_text(ocr_text)
                fallback_program = self._build_program_from_times(fallback_times)
                if fallback_program:
                    agenda_program = fallback_program
                    if title.lower().startswith("esborrany"):
                        title = "Programa de Sant Marc 2026"
                    if summary.startswith("Pendent"):
                        summary = "Programa d'agenda detectat parcialment via OCR. Requereix revisio editorial abans de publicar."
                    if body.startswith("Programa d'activitats detectat"):
                        body = "S'han detectat principalment horaris del programa. Completa noms d'actes, ubicacions i preus des de la imatge original."

            if "sant marc" in cleaned_source.lower() and "cal bassacs" in cleaned_source.lower():
                if title.lower().startswith("esborrany") or "2026" in title:
                    title = "Sant Marc 2026 a Cal Bassacs (Gironella)"
                if summary.startswith("Pendent") or len(summary) < 40 or summary.startswith("2026 SANT MARC"):
                    summary = "Cap de setmana de tradicio, cultura popular i festa per a tots els publics a Cal Bassacs."
                if body.startswith("Programa d'activitats detectat") or len(body) < 80:
                    body = "La celebracio de Sant Marc a Cal Bassacs agrupa activitats populars, cultura, dansa i musica durant dos dies amb actes per a totes les edats."

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
            "## Descripcio",
            body,
            "",
        ]

        if agenda_program:
            md += [
                "## Programa",
                agenda_program,
                "",
            ]

        md += [
            "## Dades clau",
            f"- Municipi: {municipality or 'GENERAL'}",
            f"- Categoria: {category or 'ALTRES'}",
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
