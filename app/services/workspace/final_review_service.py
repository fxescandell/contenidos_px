import csv
import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse
from uuid import uuid4

from app.services.settings.service import SettingsResolver


class FinalReviewWorkspaceService:
    def create_session(self) -> Dict[str, Any]:
        session_id = str(uuid4())
        root = self._session_root(session_id)
        (root / "input").mkdir(parents=True, exist_ok=True)
        (root / "output").mkdir(parents=True, exist_ok=True)

        state = {
            "id": session_id,
            "created_at": datetime.now().isoformat(),
            "payload_shape": "",
            "payload": None,
            "articles": [],
            "checks": {
                "run_at": None,
                "issues_total": 0,
                "errors_total": 0,
                "warnings": 0,
                "duplicates": 0,
                "title_duplicates": 0,
            },
            "last_sync": {"json_path": "", "csv_path": "", "updated_at": None},
            "last_export": "",
            "updated_at": datetime.now().isoformat(),
        }
        self._save_state(session_id, state)
        return state

    def get_state(self, session_id: str) -> Dict[str, Any]:
        return self._load_state(session_id)

    def load_export_file(self, session_id: str, upload: Any) -> Dict[str, Any]:
        state = self._load_state(session_id)
        input_dir = self._session_root(session_id) / "input"
        filename = self._safe_name(getattr(upload, "filename", "") or "export.json")
        target = input_dir / filename
        target = self._resolve_unique_path(target)
        with open(target, "wb") as out:
            import shutil

            shutil.copyfileobj(upload.file, out)

        ext = target.suffix.lower()
        if ext == ".json":
            payload = json.loads(target.read_text(encoding="utf-8"))
            shape, articles = self._extract_articles(payload)
        elif ext == ".csv":
            payload, articles = self._load_csv_payload(target)
            shape = "dict_articles"
        else:
            return {"success": False, "message": "Formato no soportado. Solo JSON o CSV."}

        state["payload_shape"] = shape
        state["payload"] = payload
        state["articles"] = articles
        state["checks"] = {
            "run_at": None,
            "issues_total": 0,
            "errors_total": 0,
            "warnings": 0,
            "duplicates": 0,
            "title_duplicates": 0,
        }
        state["last_sync"] = {"json_path": "", "csv_path": "", "updated_at": None}
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "session_id": session_id,
            "articles_count": len(articles),
            "message": f"Export cargado con {len(articles)} articulo(s).",
        }

    def run_checks(self, session_id: str) -> Dict[str, Any]:
        state = self._load_state(session_id)
        articles = state.get("articles") or []
        if not articles:
            return {"success": False, "message": "No hay articulos cargados para revisar."}

        body_index: Dict[str, List[str]] = {}
        title_index: Dict[str, List[str]] = {}
        duplicates = 0
        title_duplicates = 0
        warnings = 0
        errors_total = 0
        issues_total = 0

        for article in articles:
            data = article.get("data") or {}
            issues: List[Dict[str, str]] = []
            title = self._pick(data, ["title", "post_title", "final_title"]) or ""
            summary = self._pick(data, ["summary", "excerpt", "final_summary", "post_excerpt"]) or ""
            body = self._pick(data, ["body_html", "content", "post_content", "final_body_html"]) or ""

            if not str(title).strip():
                issues.append({"severity": "error", "code": "MISSING_TITLE", "message": "Falta titulo"})
            if str(title).strip() and len(str(title).strip()) > 120:
                issues.append({"severity": "warning", "code": "LONG_TITLE", "message": "Titulo demasiado largo para uso editorial/SEO."})
            if not str(body).strip():
                issues.append({"severity": "error", "code": "MISSING_BODY", "message": "Falta cuerpo del articulo"})
            has_summary_key = any(key in data for key in ["summary", "excerpt", "final_summary", "post_excerpt"])
            if has_summary_key and not str(summary).strip():
                issues.append({"severity": "warning", "code": "MISSING_SUMMARY", "message": "Falta resumen/excerpt"})
            if body and len(self._normalize_text_for_dup(body)) < 260:
                issues.append({"severity": "warning", "code": "SHORT_BODY", "message": "Cuerpo del articulo demasiado corto"})
            if summary and body and self._summary_duplicates_body(summary, body):
                issues.append({"severity": "warning", "code": "SUMMARY_DUPLICATES_BODY", "message": "El resumen parece duplicar el inicio del cuerpo."})
            if self._contains_placeholder_text(title, summary, body):
                issues.append({"severity": "error", "code": "PLACEHOLDER_TEXT", "message": "Se detecto texto placeholder o error tecnico en el contenido."})

            has_featured_key = any(key in data for key in ["featured_image", "image", "post_image"])
            featured_value = self._pick(data, ["featured_image", "image", "post_image"]) or ""
            if has_featured_key and not str(featured_value).strip():
                issues.append({"severity": "warning", "code": "MISSING_FEATURED_IMAGE", "message": "No hay imagen destacada configurada."})

            html_issues = self._detect_html_structure_issues(body)
            if html_issues:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "BROKEN_HTML",
                        "message": f"HTML potencialmente roto: {', '.join(html_issues[:2])}",
                    }
                )

            link_checks = self._check_links_in_html(body)
            if link_checks.get("empty"):
                issues.append(
                    {
                        "severity": "warning",
                        "code": "EMPTY_LINKS",
                        "message": f"Se detectaron {link_checks['empty']} enlace(s) vacio(s) o de placeholder.",
                    }
                )
            if link_checks.get("invalid"):
                issues.append(
                    {
                        "severity": "warning",
                        "code": "INVALID_LINKS",
                        "message": f"Se detectaron {link_checks['invalid']} URL(s) con formato invalido.",
                    }
                )

            normalized_body = self._normalize_text_for_dup(body)
            if normalized_body:
                body_index.setdefault(normalized_body, []).append(article["id"])

            normalized_title = self._normalize_text_for_dup(title)
            if normalized_title:
                title_index.setdefault(normalized_title, []).append(article["id"])

            repeated = self._detect_repeated_sentences(body)
            if repeated:
                issues.append(
                    {
                        "severity": "warning",
                        "code": "REPEATED_SENTENCES",
                        "message": f"Posible repeticion de frases: {', '.join(repeated[:3])}",
                    }
                )

            if summary and len(str(summary)) < 35:
                issues.append({"severity": "warning", "code": "SHORT_SUMMARY", "message": "Resumen demasiado corto"})

            article["issues"] = issues

        for ids in body_index.values():
            if len(ids) > 1:
                duplicates += len(ids) - 1
                for article in articles:
                    if article["id"] in ids:
                        article.setdefault("issues", []).append(
                            {
                                "severity": "warning",
                                "code": "DUPLICATE_BODY",
                                "message": "Contenido muy similar a otro articulo del mismo archivo.",
                            }
                        )

        for ids in title_index.values():
            if len(ids) > 1:
                title_duplicates += len(ids) - 1
                for article in articles:
                    if article["id"] in ids:
                        article.setdefault("issues", []).append(
                            {
                                "severity": "warning",
                                "code": "DUPLICATE_TITLE",
                                "message": "Titulo repetido en varios articulos del mismo export.",
                            }
                        )

        for article in articles:
            issues = article.get("issues") or []
            issues_total += len(issues)
            warnings += sum(1 for issue in issues if issue.get("severity") == "warning")
            errors_total += sum(1 for issue in issues if issue.get("severity") == "error")

        state["articles"] = articles
        state["checks"] = {
            "run_at": datetime.now().isoformat(),
            "issues_total": issues_total,
            "errors_total": errors_total,
            "duplicates": duplicates,
            "title_duplicates": title_duplicates,
            "warnings": warnings,
        }
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {"success": True, "session_id": session_id, "checks": state["checks"], "articles": articles}

    def list_articles(self, session_id: str) -> List[Dict[str, Any]]:
        state = self._load_state(session_id)
        return state.get("articles") or []

    def update_article(self, session_id: str, article_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        state = self._load_state(session_id)
        articles = state.get("articles") or []
        article = next((item for item in articles if item.get("id") == article_id), None)
        if not article:
            return {"success": False, "message": "Articulo no encontrado."}

        data = article.get("data") or {}
        if "title" in payload:
            self._set_first_existing_key(data, ["title", "post_title", "final_title"], str(payload.get("title") or ""))
        if "summary" in payload:
            self._set_first_existing_key(data, ["summary", "excerpt", "final_summary", "post_excerpt"], str(payload.get("summary") or ""))
        if "body_html" in payload:
            self._set_first_existing_key(data, ["body_html", "content", "post_content", "final_body_html"], str(payload.get("body_html") or ""))

        article["data"] = data
        state["updated_at"] = datetime.now().isoformat()
        sync = self._sync_review_outputs(session_id, state)
        self._save_state(session_id, state)
        return {"success": True, "message": "Articulo actualizado.", "article": article, "sync": sync}

    def ai_adjust_article(self, session_id: str, article_id: str, instructions: str) -> Dict[str, Any]:
        if not instructions or not instructions.strip():
            return {"success": False, "message": "Debes indicar instrucciones para la IA."}

        from app.services.ai.client import get_active_llm_client

        state = self._load_state(session_id)
        articles = state.get("articles") or []
        article = next((item for item in articles if item.get("id") == article_id), None)
        if not article:
            return {"success": False, "message": "Articulo no encontrado."}

        client = get_active_llm_client() or get_active_llm_client(use_ocr_vision=True)
        if not client:
            return {"success": False, "message": "No hay conexion IA activa para revisar articulos."}

        current = article.get("data") or {}
        prompt = (
            "Instrucciones del editor:\n"
            f"{instructions.strip()}\n\n"
            "Articulo actual (JSON):\n"
            f"{json.dumps(current, ensure_ascii=False, indent=2)}\n\n"
            "Devuelve SOLO JSON valido con la misma estructura y claves."
        )

        try:
            response = client.chat(prompt, system="Eres editor final. Mantienes estructura JSON.", max_tokens=3500)
            candidate = json.loads(self._extract_json(response))
        except Exception as exc:
            return {"success": False, "message": f"No se pudo aplicar IA: {exc}"}

        if not isinstance(candidate, dict):
            return {"success": False, "message": "La IA devolvio un formato invalido para articulo."}

        if "data" in candidate and isinstance(candidate.get("data"), dict):
            nested = candidate.get("data") or {}
            if nested:
                candidate = nested

        article["data"] = self._merge_ai_candidate(current, candidate)
        state["updated_at"] = datetime.now().isoformat()
        sync = self._sync_review_outputs(session_id, state)
        self._save_state(session_id, state)
        return {"success": True, "message": "Articulo ajustado con IA.", "article": article, "sync": sync}

    def export_reviewed(self, session_id: str) -> Dict[str, Any]:
        state = self._load_state(session_id)
        articles = state.get("articles") or []
        if not articles:
            return {"success": False, "message": "No hay articulos para exportar."}

        payload = self._rebuild_payload(state)
        output_root = Path(str(SettingsResolver.get("export_output_path") or "/tmp/editorial_export")) / "workspace_reviewed"
        output_root.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        json_path = output_root / f"reviewed_{session_id}_{stamp}.json"
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        rows = [item.get("data") or {} for item in articles]
        csv_path = output_root / f"reviewed_{session_id}_{stamp}.csv"
        self._write_csv(csv_path, rows)

        state["last_export"] = str(json_path)
        state["updated_at"] = datetime.now().isoformat()
        self._save_state(session_id, state)
        return {
            "success": True,
            "message": "Export revisado generado correctamente.",
            "json_path": str(json_path),
            "csv_path": str(csv_path),
        }

    def _write_csv(self, path: Path, rows: List[Dict[str, Any]]) -> None:
        headers: List[str] = []
        for row in rows:
            for key in row.keys():
                if key not in headers:
                    headers.append(key)

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for row in rows:
                writer.writerow({key: self._to_csv(row.get(key)) for key in headers})

    def _to_csv(self, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    def _extract_articles(self, payload: Any) -> tuple[str, List[Dict[str, Any]]]:
        if isinstance(payload, dict) and isinstance(payload.get("articles"), list):
            articles = [{"id": str(i + 1), "key": str(i), "data": item, "issues": []} for i, item in enumerate(payload.get("articles") or []) if isinstance(item, dict)]
            return "dict_articles", articles

        if isinstance(payload, list):
            articles = [{"id": str(i + 1), "key": str(i), "data": item, "issues": []} for i, item in enumerate(payload) if isinstance(item, dict)]
            return "list_articles", articles

        if isinstance(payload, dict) and payload and all(isinstance(value, dict) for value in payload.values()):
            articles = []
            for idx, (key, value) in enumerate(payload.items()):
                articles.append({"id": str(idx + 1), "key": key, "data": value, "issues": []})
            return "dict_by_key", articles

        if isinstance(payload, dict):
            return "single", [{"id": "1", "key": "single", "data": payload, "issues": []}]

        return "single", [{"id": "1", "key": "single", "data": {"value": payload}, "issues": []}]

    def _load_csv_payload(self, path: Path) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
        rows: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for idx, row in enumerate(reader):
                rows.append(dict(row))
        articles = [{"id": str(i + 1), "key": str(i), "data": row, "issues": []} for i, row in enumerate(rows)]
        return {"articles": rows}, articles

    def _rebuild_payload(self, state: Dict[str, Any]) -> Any:
        shape = state.get("payload_shape")
        original = state.get("payload")
        articles = state.get("articles") or []

        if shape == "dict_articles" and isinstance(original, dict):
            payload = dict(original)
            payload["articles"] = [item.get("data") or {} for item in articles]
            return payload

        if shape == "list_articles":
            return [item.get("data") or {} for item in articles]

        if shape == "dict_by_key":
            rebuilt: Dict[str, Any] = {}
            for item in articles:
                rebuilt[str(item.get("key") or item.get("id"))] = item.get("data") or {}
            return rebuilt

        if articles:
            return articles[0].get("data") or {}
        return original

    def _sync_review_outputs(self, session_id: str, state: Dict[str, Any]) -> Dict[str, str]:
        output_dir = self._session_root(session_id) / "output"
        output_dir.mkdir(parents=True, exist_ok=True)

        payload = self._rebuild_payload(state)
        json_path = output_dir / "reviewed_latest.json"
        csv_path = output_dir / "reviewed_latest.csv"

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        rows = [item.get("data") or {} for item in (state.get("articles") or [])]
        self._write_csv(csv_path, rows)

        sync_info = {
            "json_path": str(json_path),
            "csv_path": str(csv_path),
            "updated_at": datetime.now().isoformat(),
        }
        state["last_sync"] = sync_info
        return sync_info

    def _pick(self, data: Dict[str, Any], keys: List[str]) -> Optional[Any]:
        for key in keys:
            if key in data:
                return data.get(key)
        return None

    def _set_first_existing_key(self, data: Dict[str, Any], keys: List[str], value: Any) -> None:
        for key in keys:
            if key in data:
                data[key] = value
                return
        data[keys[0]] = value

    def _set_first_existing_key_if_present(self, data: Dict[str, Any], keys: List[str], value: Any) -> None:
        for key in keys:
            if key in data:
                data[key] = value
                return

    def _normalize_text_for_dup(self, text: Any) -> str:
        value = re.sub(r"<[^>]+>", " ", str(text or ""))
        value = re.sub(r"\s+", " ", value).strip().lower()
        return value

    def _detect_repeated_sentences(self, body: Any) -> List[str]:
        text = re.sub(r"<[^>]+>", " ", str(body or ""))
        sentences = [re.sub(r"\s+", " ", s).strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
        counter: Dict[str, int] = {}
        for sentence in sentences:
            normalized = sentence.lower()
            counter[normalized] = counter.get(normalized, 0) + 1
        return [sentence for sentence, count in counter.items() if count > 1 and len(sentence) > 35]

    def _summary_duplicates_body(self, summary: Any, body: Any) -> bool:
        summary_norm = self._normalize_text_for_dup(summary)
        body_norm = self._normalize_text_for_dup(body)
        if not summary_norm or not body_norm:
            return False
        if len(summary_norm) < 30:
            return False
        return body_norm.startswith(summary_norm) or summary_norm in body_norm[: max(300, len(summary_norm) + 40)]

    def _contains_placeholder_text(self, title: Any, summary: Any, body: Any) -> bool:
        combined = "\n".join([str(title or ""), str(summary or ""), str(body or "")]).lower()
        placeholders = (
            "[error",
            "error ocr",
            "pendiente de completar",
            "pendent de completar",
            "programa no detectat",
            "lorem ipsum",
        )
        return any(token in combined for token in placeholders)

    def _detect_html_structure_issues(self, body: Any) -> List[str]:
        text = str(body or "")
        if "<" not in text or ">" not in text:
            return []

        tag_re = re.compile(r"<\s*(/)?\s*([a-zA-Z][\w:-]*)[^>]*?>")
        void_tags = {
            "br",
            "hr",
            "img",
            "input",
            "meta",
            "link",
            "source",
            "track",
            "wbr",
            "col",
            "area",
            "base",
            "embed",
            "param",
        }

        stack: List[str] = []
        problems: List[str] = []
        for match in tag_re.finditer(text):
            is_closing = bool(match.group(1))
            tag = str(match.group(2) or "").lower()
            raw = match.group(0)
            self_closing = raw.rstrip().endswith("/>")

            if tag in void_tags or self_closing:
                continue

            if is_closing:
                if not stack:
                    problems.append(f"cierre inesperado </{tag}>")
                    continue
                if stack[-1] == tag:
                    stack.pop()
                    continue
                problems.append(f"orden de cierre invalido </{tag}>")
                if tag in stack:
                    while stack and stack[-1] != tag:
                        stack.pop()
                    if stack and stack[-1] == tag:
                        stack.pop()
            else:
                stack.append(tag)

        if stack:
            pending = ", ".join(f"<{tag}>" for tag in stack[:3])
            problems.append(f"etiquetas sin cierre {pending}")

        unique: List[str] = []
        for problem in problems:
            if problem not in unique:
                unique.append(problem)
        return unique

    def _check_links_in_html(self, body: Any) -> Dict[str, int]:
        text = str(body or "")
        hrefs = re.findall(r"href\s*=\s*[\"']([^\"']*)[\"']", text, flags=re.IGNORECASE)
        empty = 0
        invalid = 0
        for href in hrefs:
            value = str(href or "").strip()
            lower = value.lower()
            if not value or lower in {"#", "javascript:;", "javascript:void(0)"}:
                empty += 1
                continue
            if lower.startswith("javascript:"):
                invalid += 1
                continue
            if value.startswith(("mailto:", "tel:", "/", "#")):
                continue
            if value.startswith(("http://", "https://")):
                parsed = urlparse(value)
                if not parsed.netloc or " " in value:
                    invalid += 1
                continue
            if " " in value:
                invalid += 1
        return {"empty": empty, "invalid": invalid}

    def _merge_ai_candidate(self, current: Dict[str, Any], candidate: Dict[str, Any]) -> Dict[str, Any]:
        merged = dict(current)

        for key in list(current.keys()):
            if key in candidate:
                merged[key] = candidate.get(key)

        ai_title = self._pick(candidate, ["title", "post_title", "final_title"])
        ai_summary = self._pick(candidate, ["summary", "excerpt", "final_summary", "post_excerpt"])
        ai_body = self._pick(candidate, ["body_html", "content", "post_content", "final_body_html"])

        if ai_title is not None and str(ai_title).strip():
            self._set_first_existing_key_if_present(merged, ["title", "post_title", "final_title"], str(ai_title))
        if ai_summary is not None and str(ai_summary).strip():
            self._set_first_existing_key_if_present(merged, ["summary", "excerpt", "final_summary", "post_excerpt"], str(ai_summary))
        if ai_body is not None and str(ai_body).strip():
            self._set_first_existing_key_if_present(merged, ["body_html", "content", "post_content", "final_body_html"], str(ai_body))

        return merged

    def _extract_json(self, text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.strip("`")
            if cleaned.lower().startswith("json"):
                cleaned = cleaned[4:]
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start : end + 1]
        return cleaned

    def _session_root(self, session_id: str) -> Path:
        base = Path(str(SettingsResolver.get("temp_folder_path") or "/tmp/editorial_temp"))
        root = base / "workspace_final_review" / session_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def _state_path(self, session_id: str) -> Path:
        return self._session_root(session_id) / "session.json"

    def _load_state(self, session_id: str) -> Dict[str, Any]:
        path = self._state_path(session_id)
        if not path.exists():
            raise ValueError("Sesion de revision final no encontrada")
        return json.loads(path.read_text(encoding="utf-8"))

    def _save_state(self, session_id: str, state: Dict[str, Any]) -> None:
        self._state_path(session_id).write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    def _safe_name(self, value: str) -> str:
        name = os.path.basename(str(value or "").strip())
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", name)
        return name.strip("._") or "export.json"

    def _resolve_unique_path(self, path: Path) -> Path:
        if not path.exists():
            return path
        base = path.with_suffix("")
        ext = path.suffix
        suffix = 2
        while True:
            candidate = Path(f"{base}_{suffix}{ext}")
            if not candidate.exists():
                return candidate
            suffix += 1


final_review_workspace_service = FinalReviewWorkspaceService()
