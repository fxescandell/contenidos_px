import json
import base64
import html
import logging
import mimetypes
import os
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from app.schemas.all_schemas import EditorialBuildResult, ImageProcessingResult
from app.schemas.classification import FinalClassificationResult
from app.services.categories.service import (
    get_category_export_config,
    parse_json_example,
    build_strict_payload_from_example,
    normalize_strict_payload_exact_fields,
    normalize_strict_payload_municipality_fields,
    normalize_strict_payload_consells_fields,
    resolve_consells_type,
)

logger = logging.getLogger(__name__)


class EditorialBuilderService:

    def build_editorial_content(
        self,
        classification: FinalClassificationResult,
        extracted_text: str,
        images: List[ImageProcessingResult],
        metadata: Dict[str, Any],
    ) -> EditorialBuildResult:
        warnings = []
        errors = []

        source_context = self._prepare_source_text(extracted_text)
        prepared_text = source_context["cleaned_text"]

        if not prepared_text or not prepared_text.strip():
            warnings.append("Texto extraido vacio, no se puede generar contenido editorial.")
            return EditorialBuildResult(
                final_title="(Sin titulo)",
                final_summary="",
                final_body_html="",
                warnings=warnings,
                errors=errors,
                editorial_confidence=0.0,
            )

        municipality = classification.municipality.value if classification.municipality else ""
        category = classification.category.value if classification.category else ""
        subtype = classification.subtype.value if classification.subtype else ""
        category_config = get_category_export_config(category)

        llm_result = self._try_llm(prepared_text, municipality, category, subtype, category_config, source_context)
        if llm_result:
            structured_fields = self._extract_structured_fields(llm_result, category, prepared_text)
            if images and images[0].optimized_path:
                structured_fields["_featured_image_path"] = images[0].optimized_path

            final_title, final_summary, final_body_html, structured_fields = self._finalize_editorial_output(
                title=llm_result.get("title", ""),
                summary=llm_result.get("summary", ""),
                body_html=llm_result.get("body_html", ""),
                body_text=prepared_text,
                images=images,
                structured_fields=structured_fields,
                source_context=source_context,
                metadata=metadata,
            )

            self._normalize_category_specific_fields(structured_fields, llm_result, category, prepared_text)
            strict_payload = self._resolve_strict_payload(
                llm_result=llm_result,
                category_config=category_config,
                title=final_title,
                summary=final_summary,
                body_html=final_body_html,
                body_text=prepared_text,
                municipality=municipality,
                category=category,
                subtype=subtype,
                featured_image_path=images[0].optimized_path if images and images[0].optimized_path else "",
                structured_fields=structured_fields,
            )
            if strict_payload is not None:
                structured_fields["_strict_export_payload"] = strict_payload
            return EditorialBuildResult(
                final_title=final_title,
                final_summary=final_summary,
                final_body_html=final_body_html,
                structured_fields=structured_fields,
                warnings=warnings,
                errors=errors,
                editorial_confidence=0.9,
                inserted_images=structured_fields.get("inserted_images", []),
                featured_image_ref=structured_fields.get("featured_image_ref"),
            )

        return self._fallback_build(prepared_text, classification, images, warnings, errors, category_config, source_context)

    def _try_llm(
        self,
        text: str,
        municipality: str,
        category: str,
        subtype: str,
        category_config: Dict[str, Any],
        source_context: Dict[str, Any],
    ) -> Optional[Dict[str, str]]:
        try:
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client()
            if not client:
                return None
        except Exception:
            return None

        truncated = text[:8000]
        strict_example = (category_config.get("json_example") or "").strip()
        extra_instructions = (category_config.get("instructions") or "").strip()
        system = (
            "Ets un assistent editorial per a publicacions locals catalanes. "
            "Genera contingut web a partir del text extret de documents. "
            "Respon SEMPRE en JSON valid amb aquests camps: title (titol breu), "
            "summary (resum 1-2 frases), body_html (cos en HTML net amb <p>, <h2>, <ul>, <strong>) "
            "i strict_export_payload (objecte JSON final si hi ha plantilla estricta). "
            "Idioma: catala. No facis servir Markdown, nomes HTML."
        )
        prompt = (
            f"Municipi: {municipality}\n"
            f"Categoria: {category}\n"
            f"Subtipus: {subtype}\n\n"
            f"Text extret:\n{truncated}\n\n"
        )
        if source_context.get("author_source"):
            prompt += "La signatura final del text indica autoria original. No la deixis com una linia solta dins del body_html; el sistema l'afegira com a nota final d'autoria.\n\n"
        if source_context.get("has_highlight_marker"):
            prompt += "S'ha detectat un apartat Destacat o Destacado. Integra'l en el punt adequat del body_html com un bloc destacat visualment diferenciat, pero sense mostrar literalment les paraules Destacat o Destacado al lector.\n\n"
        if extra_instructions:
            prompt += f"Indicacions especifiques:\n{extra_instructions}\n\n"
        if strict_example:
            prompt += (
                "Has de generar strict_export_payload respectant exactament la mateixa estructura, ordre de claus i tipus que aquest exemple JSON. "
                "Pots canviar nomes els valors per omplir-los amb el contingut extret.\n"
                f"Exemple JSON estricte:\n{strict_example}\n\n"
            )
        if category == "CONSELLS":
            prompt += (
                "Per al camp 'consell' o 'consell_type' nomes pots fer servir una d'aquestes categories: "
                "Bellesa, Eco, Immobiliàries, Mascotes, Motor, Professionals, Salut. "
                "Nomes has d'usar una categoria especifica si el text tracta clarament aquell sector. "
                "Si hi ha dubte o si el tema es generic de serveis, empresa, llar, jardineria, piscines, reformes o recomanacions professionals, fes servir Professionals. "
                "No classifiquis com Bellesa per simple to estetic o decoratiu si el sector real no es bellesa.\n\n"
            )
        prompt += (
            "Optimitza el title, el summary i el body_html per SEO sense inventar dades i mantenint la fidelitat al contingut base. "
            "No deixis signatures com AMIC o Redaccio dins del cos de l'article. Estructura el body_html en blocs o seccions naturals per facilitar la insercio intercalada d'imatges dins del contingut.\n\n"
        )
        prompt += (
            "Respon amb JSON: {\"title\": \"...\", \"summary\": \"...\", \"body_html\": \"...\", \"strict_export_payload\": {...}}"
        )

        try:
            response = client.chat(prompt, system=system)
            cleaned = response.strip()
            if cleaned.startswith("```"):
                cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
                cleaned = re.sub(r"\s*```$", "", cleaned)
            parsed = json.loads(cleaned)
            if "title" in parsed and "body_html" in parsed:
                return parsed
            logger.warning("LLM response JSON lacks required fields")
            return None
        except Exception as e:
            logger.error(f"Error LLM editorial: {e}")
            return None

    def _fallback_build(
        self,
        text: str,
        classification: FinalClassificationResult,
        images: List[ImageProcessingResult],
        warnings: List[str],
        errors: List[str],
        category_config: Dict[str, Any],
        source_context: Dict[str, Any],
    ) -> EditorialBuildResult:
        warnings.append("LLM no disponible, s'ha usat el generador per defecte.")

        category = classification.category.value if classification.category else ""

        lines = [l.strip() for l in text.split("\n") if l.strip()]
        title = lines[0][:120] if lines else "(Sense titul)"
        summary_lines = lines[1:4] if len(lines) > 1 else lines[:3]
        summary = " ".join(summary_lines)[:300]

        body_parts = []
        for line in lines:
            if line == lines[0]:
                continue
            body_parts.append(f"<p>{line}</p>")
        body_html = "\n".join(body_parts[:50])
        if not body_html:
            body_html = f"<p>{text[:500]}</p>"

        structured_fields: Dict[str, Any] = {}

        date_pattern = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")
        dates_found = date_pattern.findall(text)
        if dates_found and category in ("AGENDA", "ESPORTS", "CULTURA", "TURISME_ACTIU"):
            d = dates_found[0]
            formatted = f"{d[2]}-{d[1].zfill(2)}-{d[0].zfill(2)}"
            if len(d[2]) == 2:
                formatted = f"20{d[2]}-{d[1].zfill(2)}-{d[0].zfill(2)}"
            structured_fields["event_date"] = formatted
            structured_fields["search_dates"] = [formatted]

        if images:
            structured_fields["_featured_image_path"] = images[0].optimized_path or ""

        title, summary, body_html, structured_fields = self._finalize_editorial_output(
            title=title,
            summary=summary,
            body_html=body_html,
            body_text=text,
            images=images,
            structured_fields=structured_fields,
            source_context=source_context,
            metadata={},
        )

        self._normalize_category_specific_fields(structured_fields, {}, category, text)

        strict_payload = self._resolve_strict_payload(
            llm_result={},
            category_config=category_config,
            title=title,
            summary=summary,
            body_html=body_html,
            body_text=text,
            municipality=classification.municipality.value if classification.municipality else "",
            category=classification.category.value if classification.category else "",
            subtype=classification.subtype.value if classification.subtype else "",
            featured_image_path=images[0].optimized_path if images and images[0].optimized_path else "",
            structured_fields=structured_fields,
        )
        if strict_payload is not None:
            structured_fields["_strict_export_payload"] = strict_payload

        return EditorialBuildResult(
            final_title=title,
            final_summary=summary,
            final_body_html=body_html,
            structured_fields=structured_fields,
            warnings=warnings,
            errors=errors,
            editorial_confidence=0.5,
            inserted_images=structured_fields.get("inserted_images", []),
            featured_image_ref=structured_fields.get("featured_image_ref"),
        )

    def _extract_structured_fields(
        self, llm_result: Dict[str, str], category: str, text: str
    ) -> Dict[str, Any]:
        fields: Dict[str, Any] = {}

        date_pattern = re.compile(r"(\d{1,2})[/.-](\d{1,2})[/.-](\d{2,4})")
        dates_found = date_pattern.findall(text)
        if dates_found and category in ("AGENDA", "ESPORTS", "CULTURA", "TURISME_ACTIU"):
            d = dates_found[0]
            formatted = f"{d[2]}-{d[1].zfill(2)}-{d[0].zfill(2)}"
            if len(d[2]) == 2:
                formatted = f"20{d[2]}-{d[1].zfill(2)}-{d[0].zfill(2)}"
            fields["event_date"] = formatted
            fields["search_dates"] = [formatted]

        return fields

    def _resolve_strict_payload(
        self,
        llm_result: Dict[str, Any],
        category_config: Dict[str, Any],
        title: str,
        summary: str,
        body_html: str,
        body_text: str,
        municipality: str,
        category: str,
        subtype: str,
        featured_image_path: str,
        structured_fields: Dict[str, Any],
    ) -> Optional[Any]:
        direct_payload = llm_result.get("strict_export_payload")
        example_payload = parse_json_example(category_config.get("json_example", ""))
        slug = self._slugify(title)
        publish_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event_date = structured_fields.get("event_date", "")
        start_date = structured_fields.get("start_date", event_date)
        end_date = structured_fields.get("end_date", event_date)

        payload_values = {
            "id": slug or "article-id",
            "title": title,
            "summary": summary,
            "body_html": body_html,
            "body_text": body_text,
            "municipality": municipality,
            "category": category,
            "subtype": subtype,
            "featured_image_path": featured_image_path,
            "event_date": event_date,
            "start_date": start_date,
            "end_date": end_date,
            "search_dates": structured_fields.get("search_dates", []),
            "publish_date": publish_date,
            "slug": slug,
            "consell_type": structured_fields.get("consell_type", "Professionals"),
            **structured_fields,
        }

        base_payload = None
        if example_payload is not None:
            base_payload = build_strict_payload_from_example(example_payload, payload_values)

        if direct_payload is not None:
            merged_payload = self._merge_strict_payload(base_payload, direct_payload)
            normalized_payload = normalize_strict_payload_exact_fields(merged_payload, payload_values)
            normalized_payload = normalize_strict_payload_municipality_fields(normalized_payload, municipality)
            normalized_payload = normalize_strict_payload_exact_fields(normalized_payload, payload_values)
            if category == "CONSELLS":
                normalized_payload = normalize_strict_payload_consells_fields(
                    normalized_payload,
                    structured_fields.get("consell_type", "Professionals"),
                )
            return normalized_payload

        if base_payload is None:
            return None

        normalized_payload = normalize_strict_payload_exact_fields(base_payload, payload_values)
        normalized_payload = normalize_strict_payload_municipality_fields(normalized_payload, municipality)
        if category == "CONSELLS":
            normalized_payload = normalize_strict_payload_consells_fields(
                normalized_payload,
                structured_fields.get("consell_type", "Professionals"),
            )
        return normalized_payload

    def _normalize_category_specific_fields(
        self,
        structured_fields: Dict[str, Any],
        llm_result: Dict[str, Any],
        category: str,
        extracted_text: str,
    ) -> None:
        if category != "CONSELLS":
            return

        raw_type = structured_fields.get("consell_type")
        if not raw_type:
            raw_type = llm_result.get("consell_type")

        if not raw_type and isinstance(llm_result.get("strict_export_payload"), dict):
            raw_type = self._extract_consells_type_from_payload(llm_result.get("strict_export_payload"))

        strict_payload = structured_fields.get("_strict_export_payload")
        if not raw_type and isinstance(strict_payload, dict):
            raw_type = self._extract_consells_type_from_payload(strict_payload)

        resolved_type = resolve_consells_type(raw_type, f"{llm_result.get('title', '')}\n{llm_result.get('summary', '')}\n{extracted_text}")
        structured_fields["consell_type"] = resolved_type

        if strict_payload is not None:
            structured_fields["_strict_export_payload"] = normalize_strict_payload_consells_fields(strict_payload, resolved_type)

    def _finalize_editorial_output(
        self,
        title: str,
        summary: str,
        body_html: str,
        body_text: str,
        images: List[ImageProcessingResult],
        structured_fields: Dict[str, Any],
        source_context: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> tuple[str, str, str, Dict[str, Any]]:
        final_title = self._clean_text_line(title) or self._derive_title_from_text(body_text)
        final_summary = self._build_summary(summary, body_text)
        selection_images = metadata.get("featured_selection_images") or images
        featured_image = self._select_featured_image(final_title, final_summary, body_text, images, selection_images)
        featured_image_path = featured_image.optimized_path if featured_image and featured_image.optimized_path else ""

        sanitized_body_html = self._sanitize_body_html(body_html, body_text, final_title, source_context)
        final_body_html, inserted_images = self._insert_inline_images(
            sanitized_body_html,
            images,
            featured_image.source_file_id if featured_image else None,
            final_title,
        )

        seo_fields = self._build_seo_fields(
            title=final_title,
            summary=final_summary,
            body_html=final_body_html,
            featured_image_path=featured_image_path,
            author_source=source_context.get("author_source", ""),
        )

        structured_fields.update(seo_fields)
        structured_fields["source_attribution"] = source_context.get("author_source", "")
        structured_fields["inserted_images"] = inserted_images
        structured_fields["featured_image_ref"] = str(featured_image.source_file_id) if featured_image else None
        return final_title, final_summary, final_body_html, structured_fields

    def _select_featured_image(
        self,
        title: str,
        summary: str,
        body_text: str,
        editorial_images: List[ImageProcessingResult],
        selection_images: List[ImageProcessingResult],
    ) -> Optional[ImageProcessingResult]:
        if not editorial_images:
            return None
        if len(editorial_images) == 1:
            return editorial_images[0]

        selected_source_id = self._select_featured_image_with_ai(title, summary, body_text, selection_images)
        if selected_source_id:
            for image in editorial_images:
                if image.source_file_id == selected_source_id:
                    return image

        return self._select_featured_image_fallback(editorial_images)

    def _select_featured_image_with_ai(
        self,
        title: str,
        summary: str,
        body_text: str,
        images: List[ImageProcessingResult],
    ) -> Optional[Any]:
        if len(images) < 2:
            return images[0].source_file_id if images else None

        try:
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client()
            if not client:
                return None
        except Exception:
            return None

        prepared_images = []
        for idx, image in enumerate(images[:6], start=1):
            payload = self._build_llm_image_payload(image.optimized_path or image.thumbnail_path or "")
            if not payload:
                continue
            prepared_images.append({"index": idx, "source_file_id": image.source_file_id, "payload": payload})

        if len(prepared_images) < 2:
            return None

        prompt = (
            f"Titol de l'article: {title}\n"
            f"Resum: {summary}\n"
            f"Context: {self._limit_text(body_text, 1200)}\n\n"
            f"S'han adjuntat {len(prepared_images)} imatges en aquest ordre. "
            "Escull quina representa millor el contingut principal de l'article com a imatge destacada. "
            "Prioritza la imatge mes informativa, clara i alineada amb el tema central, no la mes decorativa. "
            "Respon nomes amb JSON valid: {\"featured_image_index\": N}."
        )
        image_payloads = [item["payload"] for item in prepared_images]

        try:
            response = client.chat(prompt, images=image_payloads, max_tokens=60)
            match = re.search(r'"featured_image_index"\s*:\s*(\d+)', response or "")
            if not match:
                match = re.search(r"\b(\d+)\b", response or "")
            if not match:
                return None

            selected_index = int(match.group(1))
            for item in prepared_images:
                if item["index"] == selected_index:
                    return item["source_file_id"]
        except Exception:
            return None

        return None

    def _build_llm_image_payload(self, image_path: str) -> Optional[Dict[str, Any]]:
        if not image_path:
            return None
        if image_path.startswith(("http://", "https://", "data:")):
            return {"type": "image_url", "image_url": {"url": image_path}}
        if not os.path.exists(image_path):
            return None

        mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
        try:
            with open(image_path, "rb") as f:
                encoded = base64.b64encode(f.read()).decode("utf-8")
        except Exception:
            return None
        return {"type": "image_url", "image_url": {"url": f"data:{mime_type};base64,{encoded}"}}

    def _select_featured_image_fallback(self, images: List[ImageProcessingResult]) -> Optional[ImageProcessingResult]:
        if not images:
            return None

        def sort_key(image: ImageProcessingResult) -> tuple[int, int, int]:
            area = int(getattr(image, "width", 0) or 0) * int(getattr(image, "height", 0) or 0)
            landscape_bonus = 1 if int(getattr(image, "width", 0) or 0) >= int(getattr(image, "height", 0) or 0) else 0
            return (landscape_bonus, area, 1 if getattr(image, "role", "") == "FEATURED" else 0)

        return max(images, key=sort_key)

    def _insert_inline_images(
        self,
        body_html: str,
        images: List[ImageProcessingResult],
        featured_image_ref: Optional[Any],
        title: str,
    ) -> tuple[str, List[str]]:
        inline_images = [
            image for image in images
            if image.source_file_id != featured_image_ref and self._can_embed_image(image.optimized_path or "")
        ]
        if not inline_images:
            return body_html, []

        blocks = self._split_html_blocks(body_html)
        if not blocks:
            blocks = [body_html] if body_html.strip() else []

        inserted_images: List[str] = []
        if not blocks:
            for image in inline_images:
                src = image.optimized_path or ""
                blocks.append(self._render_inline_image_block(src, title))
                inserted_images.append(src)
            return "\n".join(blocks), inserted_images

        total_blocks = len(blocks)
        for offset, image in enumerate(inline_images, start=1):
            src = image.optimized_path or ""
            target_block = max(1, min(total_blocks, (offset * total_blocks + len(inline_images)) // (len(inline_images) + 1)))
            insert_index = min(len(blocks), target_block + offset - 1)
            blocks.insert(insert_index, self._render_inline_image_block(src, title))
            inserted_images.append(src)

        return "\n".join(blocks), inserted_images

    def _split_html_blocks(self, body_html: str) -> List[str]:
        block_pattern = re.compile(
            r"(?is)<(?:h[1-6]|p|ul|ol|blockquote|figure|div)(?:\s[^>]*)?>.*?</(?:h[1-6]|p|ul|ol|blockquote|figure|div)>"
        )
        return [match.group(0).strip() for match in block_pattern.finditer(body_html) if match.group(0).strip()]

    def _render_inline_image_block(self, src: str, title: str) -> str:
        escaped_title = html.escape(self._limit_text(title, 120))
        return (
            '<figure class="panxing-inline-image" style="margin:28px 0;">'
            f'<img src="{html.escape(src)}" alt="{escaped_title}" style="display:block;width:100%;height:auto;border-radius:8px;">'
            '</figure>'
        )

    def _can_embed_image(self, path: str) -> bool:
        return bool(path) and path.startswith(("http://", "https://", "data:"))

    def _prepare_source_text(self, text: str) -> Dict[str, Any]:
        lines = text.splitlines()
        while lines and not lines[-1].strip():
            lines.pop()

        author_source = ""
        while lines:
            detected = self._detect_author_marker(lines[-1])
            if not detected:
                break
            author_source = detected
            lines.pop()
            while lines and not lines[-1].strip():
                lines.pop()

        cleaned_text = "\n".join(lines).strip()
        return {
            "cleaned_text": cleaned_text,
            "author_source": author_source,
            "has_highlight_marker": bool(re.search(r"(?im)^\s*(destacat|destacado)\s*:?,?", cleaned_text)),
        }

    def _detect_author_marker(self, value: str) -> str:
        normalized = self._normalize_token(value)
        if normalized == "amic":
            return "AMIC"
        if normalized in {"redaccio", "redaccion"}:
            return "PANXING"
        return ""

    def _build_summary(self, summary: str, body_text: str) -> str:
        clean_summary = self._clean_text_line(self._strip_html(summary))
        if clean_summary:
            return self._limit_text(clean_summary, 260)

        plain_text = self._clean_text_line(self._strip_html(body_text))
        if not plain_text:
            return ""

        sentences = re.split(r"(?<=[.!?])\s+", plain_text)
        selected = " ".join(sentence for sentence in sentences[:2] if sentence).strip()
        return self._limit_text(selected or plain_text, 260)

    def _sanitize_body_html(self, body_html: str, body_text: str, title: str, source_context: Dict[str, Any]) -> str:
        normalized_body = (body_html or "").strip()
        if not normalized_body:
            normalized_body = self._body_html_from_text(body_text, title)

        normalized_body = re.sub(r"(?is)<p>\s*(?:amic|redacci[oó]|redaccio)\s*</p>\s*$", "", normalized_body).strip()
        normalized_body = self._apply_highlighted_block_format(normalized_body)

        author_note = self._build_author_note_html(source_context.get("author_source", ""))
        if author_note:
            normalized_body = f"{normalized_body}\n{author_note}".strip()

        return normalized_body

    def _apply_highlighted_block_format(self, body_html: str) -> str:
        def replace_heading_block(match: re.Match) -> str:
            title_text = self._clean_text_line(match.group(1))
            paragraph_html = match.group(2).strip()
            return self._render_highlight_block(title_text, paragraph_html)

        heading_pattern = re.compile(
            r"(?is)<h[1-6]>\s*(?:destacat|destacado)\s*:?\s*(.*?)\s*</h[1-6]>\s*(<p>.*?</p>)"
        )
        body_html = heading_pattern.sub(replace_heading_block, body_html)

        def replace_inline_block(match: re.Match) -> str:
            title_text = self._clean_text_line(match.group(1))
            content_text = self._clean_text_line(match.group(2))
            paragraph_html = f"<p>{html.escape(content_text)}</p>" if content_text else ""
            return self._render_highlight_block(title_text, paragraph_html)

        inline_pattern = re.compile(
            r"(?is)<p>\s*<strong>\s*(?:destacat|destacado)\s*:?\s*</strong>\s*(.*?)</p>(?:\s*<p>(.*?)</p>)?"
        )
        body_html = inline_pattern.sub(replace_inline_block, body_html)

        plain_paragraph_pattern = re.compile(
            r"(?is)<p>\s*(?:destacat|destacado)\s*:?\s*(.*?)</p>(?:\s*<p>(.*?)</p>)?"
        )
        return plain_paragraph_pattern.sub(replace_inline_block, body_html)

    def _render_highlight_block(self, title_text: str, paragraph_html: str) -> str:
        title_html = f"<h4 style=\"margin:0 0 8px 0; font-size:18px; line-height:1.3;\">{html.escape(title_text)}</h4>" if title_text else ""
        content_html = paragraph_html or ""
        return (
            '<div class="panxing-destacat" style="margin:24px 0;padding:16px 18px;border-left:4px solid #caa34d;'
            'background:#f8f3e8;border-radius:8px;">'
            f"{title_html}{content_html}</div>"
        )

    def _build_author_note_html(self, author_source: str) -> str:
        if author_source == "AMIC":
            return "<p><em>Article original d'Amic adaptat per Pànxing.</em></p>"
        if author_source == "PANXING":
            return "<p><em>Autoria: Pànxing.</em></p>"
        return ""

    def _build_seo_fields(
        self,
        title: str,
        summary: str,
        body_html: str,
        featured_image_path: str,
        author_source: str,
    ) -> Dict[str, Any]:
        plain_body = self._clean_text_line(self._strip_html(body_html))
        focus_keyword = self._build_focus_keyword(title)
        seo_title = self._build_seo_title(title, focus_keyword)
        seo_description = self._build_seo_description(summary, plain_body, focus_keyword)
        creator_name = self._resolve_creator_name(author_source)
        featured_file_name = self._extract_file_name(featured_image_path)

        return {
            "focus_keyword": focus_keyword,
            "rank_math_focus_keyword": focus_keyword,
            "rank_math_pillar_content": "",
            "rank_math_title": seo_title,
            "rank_math_description": seo_description,
            "rank_math_facebook_title": seo_title,
            "rank_math_facebook_description": seo_description,
            "rank_math_facebook_image": featured_image_path or "",
            "rank_math_facebook_enable_image_overlay": "",
            "rank_math_facebook_image_overlay": "",
            "rank_math_twitter_use_facebook": "",
            "rank_math_twitter_title": seo_title,
            "rank_math_twitter_description": seo_description,
            "rank_math_twitter_card_type": "summary_large_image" if featured_image_path else "summary",
            "rank_math_twitter_app_description": "",
            "rank_math_twitter_app_iphone_name": "",
            "rank_math_twitter_app_iphone_id": "",
            "rank_math_twitter_app_iphone_url": "",
            "rank_math_twitter_app_ipad_name": "",
            "rank_math_twitter_app_ipad_id": "",
            "rank_math_twitter_app_ipad_url": "",
            "rank_math_twitter_app_googleplay_name": "",
            "rank_math_twitter_app_googleplay_id": "",
            "rank_math_twitter_app_googleplay_url": "",
            "rank_math_twitter_app_country": "",
            "rank_math_twitter_player_url": "",
            "rank_math_twitter_player_size": "",
            "rank_math_twitter_player_stream": "",
            "rank_math_twitter_player_stream_ctype": "",
            "rank_math_advanced_robots": "",
            "rank_math_canonical_url": "",
            "headline": seo_title,
            "schema_description": seo_description,
            "article_type": "",
            "index": "",
            "nofollow": "",
            "noimageindex": "",
            "noindex": "",
            "noarchive": "",
            "nosnippet": "",
            "redirection_type": "",
            "destination_url": "",
            "_wp_old_slug": "",
            "ds_name": "",
            "ds_description": "",
            "ds_url": "",
            "ds_same_as": "",
            "ds_identifier": "",
            "ds_keywords": focus_keyword,
            "ds_license": "",
            "ds_cat_name": "",
            "ds_temp_coverage": "",
            "ds_spatial_coverage": "",
            "encoding_format": "text/html",
            "content_url": "",
            "creator_type": "Organization" if creator_name else "",
            "creator_name": creator_name,
            "creator_same_as": "",
            "types_caption": "",
            "types_alt_text": self._limit_text(title, 120),
            "types_description": seo_description,
            "types_file_name": featured_file_name,
            "types_title": self._limit_text(title, 120),
        }

    def _build_focus_keyword(self, title: str) -> str:
        candidate = self._clean_text_line(title)
        if not candidate:
            return ""

        first_clause = re.split(r"\s*[:\-|–]\s*", candidate, maxsplit=1)[0].strip()
        if first_clause and len(first_clause.split()) <= 8:
            return self._limit_text(first_clause, 60)

        return self._limit_text(" ".join(candidate.split()[:6]), 60)

    def _build_seo_title(self, title: str, focus_keyword: str) -> str:
        clean_title = self._clean_text_line(title)
        if not clean_title:
            return focus_keyword

        if focus_keyword and self._normalize_token(focus_keyword) not in self._normalize_token(clean_title):
            clean_title = f"{focus_keyword}: {clean_title}"

        return self._limit_text(clean_title, 60)

    def _build_seo_description(self, summary: str, plain_body: str, focus_keyword: str) -> str:
        base_text = self._clean_text_line(summary) or self._clean_text_line(plain_body)
        if focus_keyword and self._normalize_token(focus_keyword) not in self._normalize_token(base_text):
            base_text = f"{focus_keyword}. {base_text}".strip()
        return self._limit_text(base_text, 160)

    def _resolve_creator_name(self, author_source: str) -> str:
        if author_source == "AMIC":
            return "Amic / Pànxing"
        return "Pànxing"

    def _body_html_from_text(self, text: str, title: str) -> str:
        paragraphs = [paragraph.strip() for paragraph in re.split(r"\n{2,}", text) if paragraph.strip()]
        clean_title = self._clean_text_line(title)
        if paragraphs and self._clean_text_line(paragraphs[0]) == clean_title:
            paragraphs = paragraphs[1:]

        html_parts = []
        for paragraph in paragraphs:
            html_parts.append(f"<p>{html.escape(paragraph)}</p>")
        return "\n".join(html_parts[:50])

    def _derive_title_from_text(self, text: str) -> str:
        for line in text.splitlines():
            clean_line = self._clean_text_line(line)
            if clean_line:
                return self._limit_text(clean_line, 120)
        return "(Sense titul)"

    def _clean_text_line(self, text: str) -> str:
        return re.sub(r"\s+", " ", str(text or "")).strip()

    def _strip_html(self, text: str) -> str:
        without_tags = re.sub(r"(?is)<br\s*/?>", " ", str(text or ""))
        without_tags = re.sub(r"(?is)</p>|</div>|</h[1-6]>|</li>", "\n", without_tags)
        without_tags = re.sub(r"(?is)<[^>]+>", " ", without_tags)
        return html.unescape(without_tags)

    def _limit_text(self, text: str, max_chars: int) -> str:
        clean_text = self._clean_text_line(text)
        if len(clean_text) <= max_chars:
            return clean_text

        truncated = clean_text[: max_chars + 1].rsplit(" ", 1)[0].strip()
        return truncated or clean_text[:max_chars].strip()

    def _extract_file_name(self, path_or_url: str) -> str:
        if not path_or_url:
            return ""
        parsed = urlparse(path_or_url)
        target = parsed.path or path_or_url
        return os.path.basename(target)

    def _normalize_token(self, text: str) -> str:
        normalized = self._slugify(text or "")
        return normalized.replace("-", " ")

    def _extract_consells_type_from_payload(self, payload: Any) -> str:
        if isinstance(payload, dict):
            for key, value in payload.items():
                if str(key).lower() == "consell":
                    return str(value or "")
                found = self._extract_consells_type_from_payload(value)
                if found:
                    return found
        elif isinstance(payload, list):
            for item in payload:
                found = self._extract_consells_type_from_payload(item)
                if found:
                    return found
        return ""

    def _merge_strict_payload(self, base_payload: Any, override_payload: Any) -> Any:
        if base_payload is None:
            return override_payload

        if isinstance(base_payload, dict) and isinstance(override_payload, dict):
            if self._looks_like_single_record_payload(base_payload) and self._looks_like_single_record_payload(override_payload):
                base_key, base_value = next(iter(base_payload.items()))
                override_key, override_value = next(iter(override_payload.items()))
                final_key = override_key or base_key
                return {
                    final_key: self._merge_strict_payload(base_value, override_value)
                }

            merged = {}
            for key in base_payload.keys():
                if key in override_payload:
                    merged[key] = self._merge_strict_payload(base_payload[key], override_payload[key])
                else:
                    merged[key] = base_payload[key]
            return merged

        if isinstance(base_payload, list) and isinstance(override_payload, list):
            if not base_payload:
                return []

            merged = []
            for index, base_item in enumerate(base_payload):
                if index < len(override_payload):
                    merged.append(self._merge_strict_payload(base_item, override_payload[index]))
                else:
                    merged.append(base_item)
            return merged

        if self._is_empty_payload_value(override_payload) and not self._is_empty_payload_value(base_payload):
            return base_payload

        return override_payload

    def _looks_like_single_record_payload(self, payload: Any) -> bool:
        return isinstance(payload, dict) and len(payload) == 1 and isinstance(next(iter(payload.values())), dict)

    def _is_empty_payload_value(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return value.strip() == ""
        if isinstance(value, (list, dict)):
            return len(value) == 0
        return False

    def _slugify(self, text: str) -> str:
        text = (text or "").strip().lower()
        replacements = {
            "à": "a",
            "á": "a",
            "è": "e",
            "é": "e",
            "í": "i",
            "ï": "i",
            "ò": "o",
            "ó": "o",
            "ú": "u",
            "ü": "u",
            "ç": "c",
            "·": "-",
        }
        for source, target in replacements.items():
            text = text.replace(source, target)
        text = re.sub(r"[^a-z0-9\s-]", "", text)
        text = re.sub(r"[\s_-]+", "-", text)
        return text.strip("-")
