import json
import logging
import re
from datetime import datetime
from typing import List, Dict, Any, Optional

from app.schemas.all_schemas import EditorialBuildResult, ImageProcessingResult
from app.schemas.classification import FinalClassificationResult
from app.services.categories.service import get_category_export_config, parse_json_example, build_strict_payload_from_example

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

        if not extracted_text or not extracted_text.strip():
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

        llm_result = self._try_llm(extracted_text, municipality, category, subtype, category_config)
        if llm_result:
            structured_fields = self._extract_structured_fields(llm_result, category, extracted_text)
            if images and images[0].optimized_path:
                structured_fields["_featured_image_path"] = images[0].optimized_path
            strict_payload = self._resolve_strict_payload(
                llm_result=llm_result,
                category_config=category_config,
                title=llm_result.get("title", ""),
                summary=llm_result.get("summary", ""),
                body_html=llm_result.get("body_html", ""),
                body_text=extracted_text,
                municipality=municipality,
                category=category,
                subtype=subtype,
                featured_image_path=images[0].optimized_path if images and images[0].optimized_path else "",
                structured_fields=structured_fields,
            )
            if strict_payload is not None:
                structured_fields["_strict_export_payload"] = strict_payload
            return EditorialBuildResult(
                final_title=llm_result.get("title", ""),
                final_summary=llm_result.get("summary", ""),
                final_body_html=llm_result.get("body_html", ""),
                structured_fields=structured_fields,
                warnings=warnings,
                errors=errors,
                editorial_confidence=0.9,
                featured_image_ref=str(images[0].source_file_id) if images else None,
            )

        return self._fallback_build(extracted_text, classification, images, warnings, errors, category_config)

    def _try_llm(
        self, text: str, municipality: str, category: str, subtype: str, category_config: Dict[str, Any]
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
        if extra_instructions:
            prompt += f"Indicacions especifiques:\n{extra_instructions}\n\n"
        if strict_example:
            prompt += (
                "Has de generar strict_export_payload respectant exactament la mateixa estructura, claus i tipus que aquest exemple JSON. "
                "Pots canviar nomes els valors per omplir-los amb el contingut extret.\n"
                f"Exemple JSON estricte:\n{strict_example}\n\n"
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
            featured_image_ref=str(images[0].source_file_id) if images else None,
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
        if direct_payload is not None:
            return direct_payload

        example_payload = parse_json_example(category_config.get("json_example", ""))
        if example_payload is None:
            return None

        slug = self._slugify(title)
        publish_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        event_date = structured_fields.get("event_date", "")
        start_date = structured_fields.get("start_date", event_date)
        end_date = structured_fields.get("end_date", event_date)

        return build_strict_payload_from_example(example_payload, {
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
        })

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
