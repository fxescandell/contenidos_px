import json
import base64
import html
import logging
import mimetypes
import os
import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from app.schemas.all_schemas import EditorialBuildResult, ImageProcessingResult
from app.schemas.classification import FinalClassificationResult
from app.services.editorial.agenda_parser import parse_agenda, render_agenda_html, render_highlight_box
from app.services.editorial.final_review import final_review_service
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
MARKDOWN_HEADING_RE = re.compile(r"^\[\[H([1-6])\]\]\s*(.+)$")
MARKDOWN_LIST_RE = re.compile(r"^\[\[LI\]\]\s*(.+)$")

AGENDA_CATEGORY_OPTIONS = [
    "Festes populars",
    "Oci i activitats",
    "Agenda cultural",
    "Agenda d'esports",
    "Activitats en familia",
    "Tallers i xerrades",
    "Mercats",
    "General",
    "Concert",
    "AGENDA",
    "Fira",
    "Agenda General",
    "Esport",
    "Teatre",
]

AGENDA_CATEGORY_KEYWORDS = {
    "Agenda d'esports": ["esport", "partit", "cursa", "torneig", "campionat", "trail", "btt", "futbol", "basquet"],
    "Concert": ["concert", "musica", "música", "acustic", "acústic", "dj", "orquestra", "recital"],
    "Teatre": ["teatre", "teatro", "obra", "clown", "espectacle teatral", "dramat"],
    "Activitats en familia": ["familia", "família", "infantil", "nens", "nenes", "familiar", "canalla"],
    "Tallers i xerrades": ["taller", "xerrada", "conferencia", "conferència", "ponencia", "ponència", "masterclass"],
    "Mercats": ["mercat", "mercado", "flea", "parades", "artesania"],
    "Fira": ["fira", "feria", "mostra", "certamen"],
    "Agenda cultural": ["cultura", "cultural", "patrimoni", "exposicio", "exposició", "museu", "biblioteca"],
    "Festes populars": ["festa", "festes", "major", "correfoc", "cercavila", "prego", "pregó", "tradicio", "tradició"],
    "Oci i activitats": ["oci", "activitat", "activitats", "cap de setmana", "programa", "agenda"],
}

AGENDA_LOW_QUALITY_TITLES = {
    "a",
    "de",
    "i",
    "o",
    "la",
    "el",
    "les",
    "els",
    "del",
    "dels",
    "al",
    "als",
    "amb",
    "per",
    "en",
    "programa",
    "programacio",
    "data",
    "hora",
    "lloc",
    "de a",
    "i de",
}

AGENDA_DAY_TOKENS = {
    "dilluns",
    "dimarts",
    "dimecres",
    "dijous",
    "divendres",
    "dissabte",
    "diumenge",
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
}

AGENDA_EXTRA_INFO_RE = re.compile(
    r"\b(Gratu[iï]t|Inscripci[oó]\s+pr[eè]via|Inscripci[oó]|Obert\s+a\s+tothom)\b",
    re.IGNORECASE,
)

MONTH_NAME_TO_NUMBER = {
    "gener": 1,
    "enero": 1,
    "january": 1,
    "febrer": 2,
    "febrero": 2,
    "february": 2,
    "marc": 3,
    "març": 3,
    "marzo": 3,
    "march": 3,
    "abril": 4,
    "april": 4,
    "maig": 5,
    "mayo": 5,
    "may": 5,
    "juny": 6,
    "junio": 6,
    "june": 6,
    "juliol": 7,
    "julio": 7,
    "july": 7,
    "agost": 8,
    "agosto": 8,
    "august": 8,
    "setembre": 9,
    "septiembre": 9,
    "setiembre": 9,
    "september": 9,
    "octubre": 10,
    "october": 10,
    "novembre": 11,
    "noviembre": 11,
    "november": 11,
    "desembre": 12,
    "diciembre": 12,
    "december": 12,
}


class EditorialBuilderService:

    def __init__(self):
        self.final_review_service = final_review_service

    def build_editorial_content(
        self,
        classification: FinalClassificationResult,
        extracted_text: str,
        images: List[ImageProcessingResult],
        metadata: Dict[str, Any],
    ) -> EditorialBuildResult:
        warnings = []
        errors = []

        effective_text = self._build_effective_source_text(extracted_text, metadata, images)
        source_context = self._prepare_source_text(effective_text)
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

        llm_result = self._try_llm(prepared_text, municipality, category, subtype, category_config, source_context, metadata)
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
                metadata={**metadata, "category": category},
            )
            final_title, final_summary, final_body_html, structured_fields = self._apply_final_review(
                municipality=municipality,
                category=category,
                subtype=subtype,
                original_text=prepared_text,
                vision_context_text=self._clean_text_line(metadata.get("vision_context_text", "")),
                title=final_title,
                summary=final_summary,
                body_html=final_body_html,
                structured_fields=structured_fields,
                images=images,
                source_context=source_context,
                metadata={**metadata, "category": category},
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
                featured_image_path=structured_fields.get("rank_math_facebook_image") or (images[0].optimized_path if images and images[0].optimized_path else ""),
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

    def _build_effective_source_text(
        self,
        extracted_text: str,
        metadata: Dict[str, Any],
        images: List[ImageProcessingResult],
    ) -> str:
        primary_text = str(extracted_text or "").strip()
        if primary_text:
            return primary_text

        candidates: List[str] = []
        vision_context = self._clean_text_line(metadata.get("vision_context_text", ""))
        if vision_context:
            candidates.append(vision_context)

        image_name_context = self._clean_text_line(metadata.get("image_name_context", ""))
        if image_name_context:
            candidates.append(self._humanize_image_context(image_name_context))

        if not candidates and images:
            file_names = []
            for image in images:
                path = image.optimized_path or image.thumbnail_path or ""
                name = self._extract_file_name(path)
                if name:
                    file_names.append(os.path.splitext(name)[0])
            if file_names:
                candidates.append(self._humanize_image_context("\n".join(file_names)))

        return "\n\n".join(part for part in candidates if part).strip()

    def _humanize_image_context(self, text: str) -> str:
        lines = []
        for raw_line in str(text or "").splitlines():
            clean_line = self._clean_text_line(raw_line)
            if not clean_line:
                continue
            file_name = self._extract_file_name(clean_line)
            stem = os.path.splitext(file_name or clean_line)[0]
            stem = re.sub(r"(?:_opt|_thumb|scaled-\d+|scaled)$", "", stem, flags=re.IGNORECASE)
            stem = re.sub(r"[_-]+", " ", stem)
            stem = re.sub(r"\s+", " ", stem).strip()
            if not stem:
                continue
            if stem.upper() == stem:
                stem = stem.title()
            else:
                stem = stem[0].upper() + stem[1:]
            lines.append(stem)
        return "\n".join(lines)

    def _try_llm(
        self,
        text: str,
        municipality: str,
        category: str,
        subtype: str,
        category_config: Dict[str, Any],
        source_context: Dict[str, Any],
        metadata: Dict[str, Any],
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
            "Idioma obligatori: catala. No pots redactar cap contingut editorial en castella ni en cap altre idioma, excepte noms propis, marques o cites literals imprescindibles. "
            "El body_html ha de tenir jerarquia visual real: usa h2 i h3 quan hi hagi apartats o subapartats, <strong> per remarcar idees o etiquetes clau i <em> quan calgui un matis editorial. "
            "No facis servir Markdown, nomes HTML."
        )
        prompt = (
            f"Municipi: {municipality}\n"
            f"Categoria: {category}\n"
            f"Subtipus: {subtype}\n\n"
            f"Text extret:\n{truncated}\n\n"
        )
        vision_context = self._clean_text_line(metadata.get("vision_context_text", ""))
        if vision_context:
            prompt += (
                "Text complementari extret d'imatges o cartells:\n"
                f"{self._limit_text(vision_context, 2500)}\n\n"
                "Fes-lo servir nomes com a suport contextual si encaixa clarament amb el contingut principal. "
                "No el copiïs ni l'afegeixis com un bloc separat o com si fos informacio nova desconnectada del text base.\n\n"
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
        if category == "AGENDA":
            prompt += (
                "Per a agenda, el body_html ha de tenir una introduccio editorial breu i despres els esdeveniments ben estructurats visualment. "
                "Cada activitat ha d'apareixer com un bloc propi, amb el titol destacat, la data i hora amb un format diferenciat, el lloc amb un altre format i la descripcio en un paragraf clar. "
                "No perdis cap activitat del text original i no fusionis activitats diferents en un sol paragraf.\n\n"
            )
        prompt += (
            "Si el contingut conté un llistat de diversos esdeveniments, activitats, empreses, restaurants, escoles, hotels, establiments o altres elements diferenciats, "
            "afegeix tambe un camp JSON 'content_items' amb una llista d'objectes. Cada objecte ha de tenir: "
            "title, datetime_label, location, description, extra_info i image_ref. "
            "image_ref es pot deixar buit; el sistema intentara assignar la imatge correcta automaticament. "
            "Per a continguts d'agenda, si retorna activitats, pots incloure tambe 'activities' amb la mateixa estructura.\n\n"
        )
        prompt += (
            "Optimitza el title, el summary i el body_html per SEO sense inventar dades i mantenint la fidelitat al contingut base. "
            "No deixis signatures com AMIC o Redaccio dins del cos de l'article. Estructura el body_html en blocs o seccions naturals per facilitar la insercio intercalada d'imatges dins del contingut. "
            "La redaccio final ha de ser sempre en catala. "
            "No deixis tot el contingut en simples <p>: decideix quan calen titols, subtitols, negretes o italica per fer el text mes clar i atractiu. "
            "No pots resumir reduint informacio: has de conservar tots els apartats, activitats, esdeveniments o seccions del text original i, si cal, ampliar-los amb context real i verificable.\n\n"
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
            metadata={"category": category},
        )
        title, summary, body_html, structured_fields = self._apply_final_review(
            municipality=classification.municipality.value if classification.municipality else "",
            category=category,
            subtype=classification.subtype.value if classification.subtype else "",
            original_text=text,
            vision_context_text="",
            title=title,
            summary=summary,
            body_html=body_html,
            structured_fields=structured_fields,
            images=images,
            source_context=source_context,
            metadata={"category": category},
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
            featured_image_path=structured_fields.get("rank_math_facebook_image") or (images[0].optimized_path if images and images[0].optimized_path else ""),
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

        if isinstance(llm_result.get("content_items"), list):
            fields["content_items"] = self._normalize_activity_items(llm_result.get("content_items"))
        if isinstance(llm_result.get("activities"), list):
            fields["activities"] = self._normalize_activity_items(llm_result.get("activities"))
            if "content_items" not in fields:
                fields["content_items"] = list(fields["activities"])

        if category == "AGENDA":
            return self._enrich_agenda_structured_fields(fields, llm_result, text)

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
        start_date = structured_fields.get("start_date", "")
        end_date = structured_fields.get("end_date", "")

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
            "search_dates_string": structured_fields.get("search_dates_string", ""),
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

    def _apply_final_review(
        self,
        municipality: str,
        category: str,
        subtype: str,
        original_text: str,
        vision_context_text: str,
        title: str,
        summary: str,
        body_html: str,
        structured_fields: Dict[str, Any],
        images: List[ImageProcessingResult],
        source_context: Dict[str, Any],
        metadata: Dict[str, Any],
    ) -> tuple[str, str, str, Dict[str, Any]]:
        reviewed = self.final_review_service.review_content(
            municipality=municipality,
            category=category,
            subtype=subtype,
            original_text=original_text,
            vision_context_text=vision_context_text,
            draft_title=title,
            draft_summary=summary,
            draft_body_html=body_html,
        )

        reviewed_title = self._clean_text_line(reviewed.get("title", "")) or title
        reviewed_summary = self._build_summary(reviewed.get("summary", ""), original_text)
        if (metadata.get("category") or category) == "AGENDA":
            reviewed_summary = self._clean_agenda_summary(reviewed_summary)
        reviewed_body_html = self._clean_text_line(reviewed.get("body_html", "")) and reviewed.get("body_html", "") or body_html
        if "<figure" in body_html and "<figure" not in reviewed_body_html:
            reviewed_body_html = body_html
        reviewed_body_html = self._ensure_source_text_is_preserved(
            reviewed_body_html,
            original_text,
            reviewed_summary,
            metadata.get("category") or category,
            self._prepare_listing_items(structured_fields),
        )
        reviewed_body_html = self._sanitize_body_html(reviewed_body_html, original_text, reviewed_title, source_context)
        reviewed_body_html = self._enhance_html_structure(reviewed_body_html, metadata.get("category") or category)
        reviewed_summary = self._ensure_summary_not_duplicate_with_body(reviewed_summary, reviewed_body_html)
        reviewed_body_html = self._remove_summary_duplication_from_body(reviewed_body_html, reviewed_summary)

        featured_image_path = structured_fields.get("rank_math_facebook_image") or structured_fields.get("_featured_image_path") or (images[0].optimized_path if images and images[0].optimized_path else "")
        seo_fields = self._build_seo_fields(
            title=reviewed_title,
            summary=reviewed_summary,
            body_html=reviewed_body_html,
            featured_image_path=featured_image_path,
            author_source=source_context.get("author_source", ""),
        )
        structured_fields.update(seo_fields)
        if reviewed.get("notes"):
            structured_fields["final_review_notes"] = reviewed.get("notes")
        return reviewed_title, reviewed_summary, reviewed_body_html, structured_fields

    def _normalize_category_specific_fields(
        self,
        structured_fields: Dict[str, Any],
        llm_result: Dict[str, Any],
        category: str,
        extracted_text: str,
    ) -> None:
        if category == "AGENDA":
            structured_fields.update(self._enrich_agenda_structured_fields(structured_fields, llm_result, extracted_text))
            return

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
        if (metadata.get("category") or "") == "AGENDA":
            final_summary = self._clean_agenda_summary(final_summary)
        selection_images = metadata.get("featured_selection_images") or images
        featured_image = self._select_featured_image(final_title, final_summary, body_text, images, selection_images)
        featured_image_path = featured_image.optimized_path if featured_image and featured_image.optimized_path else ""

        source_listing_items = self._extract_content_items_from_source(body_text, metadata.get("category") or "")
        listing_items = self._prepare_listing_items(structured_fields)
        if source_listing_items and len(source_listing_items) >= len(listing_items):
            listing_items = source_listing_items

        sanitized_body_html = self._sanitize_body_html(body_html, body_text, final_title, source_context)
        sanitized_body_html = self._ensure_source_text_is_preserved(
            sanitized_body_html,
            body_text,
            final_summary,
            metadata.get("category") or "",
            listing_items,
        )
        final_summary = self._ensure_summary_not_duplicate_with_body(final_summary, sanitized_body_html)
        sanitized_body_html = self._remove_summary_duplication_from_body(sanitized_body_html, final_summary)
        listing_items = self._assign_activity_image_refs(
            listing_items,
            images,
            metadata.get("featured_selection_images") or images,
            final_title,
            final_summary,
            body_text,
        )
        if listing_items:
            structured_fields["content_items"] = listing_items
            if structured_fields.get("activities") or self._looks_like_listing_category(metadata.get("category") or ""):
                structured_fields["activities"] = listing_items
        final_body_html, inserted_images = self._insert_inline_images(
            sanitized_body_html,
            images,
            featured_image.source_file_id if featured_image else None,
            final_title,
            listing_items,
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
            "Si una de les imatges es un cartell, poster o programa visual que resumeix globalment l'esdeveniment o el contingut, aquesta ha de ser la portada preferent. "
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

        poster_candidate = self._select_poster_image_by_filename(images)
        if poster_candidate is not None:
            return poster_candidate

        def sort_key(image: ImageProcessingResult) -> tuple[int, int, int]:
            area = int(getattr(image, "width", 0) or 0) * int(getattr(image, "height", 0) or 0)
            landscape_bonus = 1 if int(getattr(image, "width", 0) or 0) >= int(getattr(image, "height", 0) or 0) else 0
            return (landscape_bonus, area, 1 if getattr(image, "role", "") == "FEATURED" else 0)

        return max(images, key=sort_key)

    def _select_poster_image_by_filename(self, images: List[ImageProcessingResult]) -> Optional[ImageProcessingResult]:
        poster_tokens = {"cartell", "cartel", "poster", "flyer", "programa", "agenda", "ok"}
        for image in images:
            image_path = image.optimized_path or image.thumbnail_path or ""
            image_tokens = self._extract_image_name_tokens(image_path)
            image_stem = self._normalize_image_stem(image_path)
            if image_tokens.intersection(poster_tokens) or image_stem.lower().endswith("-ok") or image_stem.lower().endswith("_ok"):
                return image
        return None

    def _normalize_activity_items(self, activities: Any) -> List[Dict[str, Any]]:
        if not isinstance(activities, list):
            return []

        normalized = []
        for item in activities:
            if not isinstance(item, dict):
                continue
            normalized.append({
                "title": self._clean_text_line(item.get("title", "")),
                "datetime_label": self._clean_text_line(item.get("datetime_label", "")),
                "location": self._clean_text_line(item.get("location", "")),
                "description": self._clean_text_line(item.get("description", "")),
                "extra_info": self._clean_text_line(item.get("extra_info", "")),
                "image_ref": item.get("image_ref", "") or "",
            })
        return normalized

    def _enrich_agenda_structured_fields(
        self,
        structured_fields: Dict[str, Any],
        llm_result: Dict[str, Any],
        extracted_text: str,
    ) -> Dict[str, Any]:
        enriched = dict(structured_fields or {})
        items = self._collect_agenda_items(enriched, llm_result, extracted_text)
        if items:
            enriched["activities"] = items
            enriched["content_items"] = items

        date_fields = self._build_agenda_date_fields(enriched, items, extracted_text)
        enriched.update(date_fields)
        enriched["search_dates_string"] = "|".join(date_fields.get("search_dates", []))

        activity_fields = self._build_agenda_activity_export_fields(
            items,
            date_fields.get("event_date", "") or (date_fields.get("search_dates", [""])[0] if date_fields.get("search_dates") else ""),
        )
        enriched.update(activity_fields)

        raw_category = self._clean_text_line(
            enriched.get("agenda_category", "")
            or llm_result.get("agenda_category", "")
            or llm_result.get("categoria-d-agenda", "")
        )
        normalized_category = self._normalize_agenda_category(raw_category)
        if not normalized_category:
            normalized_category = self._infer_agenda_category(extracted_text, items)
        enriched["agenda_category"] = normalized_category

        return enriched

    def _collect_agenda_items(
        self,
        structured_fields: Dict[str, Any],
        llm_result: Dict[str, Any],
        extracted_text: str,
    ) -> List[Dict[str, Any]]:
        candidates: List[List[Dict[str, Any]]] = []

        markdown_items = self._sanitize_agenda_items(self._extract_markdown_agenda_items(extracted_text))
        if markdown_items:
            candidates.append(markdown_items)

        prose_items = self._sanitize_agenda_items(self._extract_agenda_items_from_prose(extracted_text))
        if prose_items:
            candidates.append(prose_items)

        for value in [
            structured_fields.get("activities"),
            structured_fields.get("content_items"),
            llm_result.get("activities"),
            llm_result.get("content_items"),
        ]:
            normalized = self._sanitize_agenda_items(self._normalize_activity_items(value))
            if normalized:
                candidates.append(normalized)

        source_items = self._sanitize_agenda_items(
            self._build_source_agenda_items_with_day_context(parse_agenda(extracted_text).get("events", []))
        )
        if source_items:
            candidates.append(source_items)

        if not candidates:
            return []

        return max(candidates, key=self._agenda_items_quality_score)

    def _extract_agenda_items_from_prose(self, extracted_text: str) -> List[Dict[str, Any]]:
        source = str(extracted_text or "").replace("\r\n", "\n").replace("\r", "\n")
        if not source.strip():
            return []

        blocks = [block.strip() for block in re.split(r"\n\s*\n+", source) if block.strip()]
        if not blocks:
            return []

        reference_year = self._infer_reference_year(source)
        items: List[Dict[str, Any]] = []

        for block in blocks:
            lines = [self._clean_text_line(line) for line in block.split("\n") if self._clean_text_line(line)]
            if not lines:
                continue

            heading = lines[0]
            body_text = " ".join(lines[1:]).strip()

            if not body_text:
                compact_match = re.match(
                    r"^(.*?\b\d{1,2}(?:\s*(?:i|y)\s*\d{1,2})?\s*(?:de|d['’])?\s*[A-Za-zÀ-ÿ]+(?:\s+de\s+\d{4})?)(?:\s*[–:-]\s*|\s+)(.+)$",
                    heading,
                    re.IGNORECASE,
                )
                if compact_match:
                    heading = self._clean_text_line(compact_match.group(1))
                    body_text = self._clean_text_line(compact_match.group(2))

            heading_dates = self._extract_iso_dates_from_text(heading, reference_year)
            if not heading_dates:
                if items:
                    tail_text = self._clean_agenda_inline_text(block)
                    if tail_text and len(tail_text) < 180 and self._normalize_token(tail_text) not in {
                        "redaccio",
                        "redaccion",
                    }:
                        last = items[-1]
                        combined = self._clean_text_line(" ".join(part for part in [last.get("description", ""), tail_text] if part))
                        last["description"] = combined
                continue

            if not self._looks_like_agenda_prose_heading(heading):
                continue

            details = self._clean_agenda_inline_text(body_text)
            if not details:
                continue

            title = self._clean_agenda_inline_text(details.split(".", 1)[0])

            if not title or self._is_calendar_heading_title(title) or self._is_low_quality_activity_title(title):
                continue

            location, description = self._extract_agenda_location_from_description(details)
            description, extra_info = self._extract_agenda_extra_info_from_description(description)

            datetime_label = self._clean_agenda_inline_text(heading)

            items.append({
                "title": self._trim_agenda_title(title),
                "datetime_label": datetime_label,
                "location": location,
                "description": description,
                "extra_info": extra_info,
                "image_ref": "",
            })

        return items

    def _looks_like_agenda_prose_heading(self, heading: str) -> bool:
        clean = self._clean_agenda_inline_text(heading)
        if not clean:
            return False
        if len(clean) > 90 or "." in clean:
            return False

        tokens = [token for token in clean.split() if token]
        if len(tokens) > 14:
            return False

        if self._looks_like_agenda_day_heading(clean):
            return True

        dates = self._extract_iso_dates_from_text(clean, self._infer_reference_year(clean))
        return bool(dates) and len(tokens) <= 8

    def _extract_markdown_agenda_items(self, extracted_text: str) -> List[Dict[str, Any]]:
        source = str(extracted_text or "")
        if "**" not in source:
            return []

        day_heading_re = re.compile(r"^\*\*(.+?)\*\*$")
        event_line_re = re.compile(
            r"^\*\*(?P<time>[^*]+?)\*\*\s*[–-]\s*\*\*(?P<title>[^*]+?)\*\*(?:_(?P<desc>.+?)_)?$",
            re.IGNORECASE,
        )

        current_day = ""
        items: List[Dict[str, Any]] = []

        for raw_line in source.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            line = self._clean_text_line(raw_line)
            if not line:
                continue

            day_match = day_heading_re.match(line)
            if day_match:
                heading_text = self._clean_agenda_inline_text(day_match.group(1))
                if self._looks_like_agenda_day_heading(heading_text):
                    current_day = heading_text
                continue

            event_match = event_line_re.match(line)
            if not event_match:
                continue

            time_label = self._clean_agenda_inline_text(event_match.group("time"))
            title = self._clean_agenda_inline_text(event_match.group("title"))
            description = self._clean_agenda_inline_text(event_match.group("desc") or "")

            location, description = self._extract_agenda_location_from_description(description)
            description, extra_info = self._extract_agenda_extra_info_from_description(description)

            datetime_label = f"{current_day} {time_label}".strip() if current_day else time_label

            items.append({
                "title": self._trim_agenda_title(title),
                "datetime_label": datetime_label,
                "location": location,
                "description": description,
                "extra_info": extra_info,
                "image_ref": "",
            })

        return items

    def _looks_like_agenda_day_heading(self, value: str) -> bool:
        normalized = self._normalize_token(value).replace("-", " ")
        tokens = [token for token in re.split(r"\s+", normalized) if token]
        if not tokens:
            return False
        has_day = any(token in AGENDA_DAY_TOKENS for token in tokens)
        return has_day and bool(re.search(r"\b\d{1,2}\b", value))

    def _extract_agenda_location_from_description(self, description: str) -> tuple[str, str]:
        text = self._clean_agenda_inline_text(description)
        if not text:
            return "", ""

        location_patterns = [
            r"\bInici\s+a\s+(?:la|l['’]|el)\s+(.+?)(?=(?:\s+Recital\b|\s+Amb\b|\s+Organitza\b|$))",
            r"\bInici\s+al\s+(.+?)(?=(?:\s+Recital\b|\s+Amb\b|\s+Organitza\b|$))",
            r"\bA\s+(?:la|l['’]|el)\s+(.+?)(?=(?:\s+Amb\b|\s+Cal\b|\s+Organitza\b|$))",
            r"\bAl\s+(.+?)(?=(?:\s+Amb\b|\s+Cal\b|\s+Organitza\b|$))",
        ]

        for pattern in location_patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if not match:
                continue
            location = self._clean_agenda_inline_text(match.group(1))
            if not location:
                continue
            without_location = self._clean_text_line((text[:match.start()] + " " + text[match.end():]).strip(" -–,:;"))
            return location, without_location

        # Support compact strings like "A la Biblioteca Ramon Vinyes i CluetCal inscripció prèvia"
        compact_match = re.search(r"\bA\s+(?:la|l['’]|el)\s+(.+?)(Cal\s+inscripci[oó]\s+pr[eè]via)$", text, flags=re.IGNORECASE)
        if compact_match:
            location = self._clean_agenda_inline_text(compact_match.group(1))
            without_location = self._clean_text_line((text[:compact_match.start()] + " " + compact_match.group(2)).strip(" -–,:;"))
            return location, without_location

        return "", text

    def _extract_agenda_extra_info_from_description(self, description: str) -> tuple[str, str]:
        text = self._clean_agenda_inline_text(description)
        if not text:
            return "", ""

        matches = [self._clean_text_line(match.group(1)) for match in AGENDA_EXTRA_INFO_RE.finditer(text)]
        if not matches:
            return text, ""

        seen = set()
        unique = []
        for item in matches:
            normalized = self._normalize_token(item)
            if normalized in seen:
                continue
            seen.add(normalized)
            unique.append(item)

        cleaned = AGENDA_EXTRA_INFO_RE.sub("", text)
        cleaned = self._clean_text_line(cleaned)
        if self._normalize_token(cleaned) == "cal":
            cleaned = ""
        return cleaned, " · ".join(unique)

    def _clean_agenda_inline_text(self, value: str) -> str:
        text = self._clean_text_line(value)
        if not text:
            return ""
        text = text.replace("**", "").replace("__", " ").replace("_", " ")
        text = re.sub(r"([a-zà-ÿ])([A-ZÀ-Ý])", r"\1 \2", text)
        text = re.sub(r"([”\"'])([A-ZÀ-Ý])", r"\1 \2", text)
        text = re.sub(r"\s+", " ", text)
        return text.strip(" -–,:;")

    def _trim_agenda_title(self, value: str) -> str:
        title = self._clean_agenda_inline_text(value)
        title = re.sub(r"\s+(?:a\s+la|a\s+l'|al|a)$", "", title, flags=re.IGNORECASE)
        title = title.strip(" -–,:;")
        return title

    def _build_source_agenda_items_with_day_context(self, events: Any) -> List[Dict[str, Any]]:
        if not isinstance(events, list):
            return []

        items: List[Dict[str, Any]] = []
        for event in events:
            if not isinstance(event, dict):
                continue

            day = self._clean_text_line(event.get("day", ""))
            datetime_label = self._clean_text_line(event.get("datetime_label", ""))
            combined_datetime = datetime_label
            if day:
                normalized_day = self._normalize_token(day)
                normalized_datetime = self._normalize_token(datetime_label)
                if not datetime_label:
                    combined_datetime = day
                elif normalized_day and normalized_day not in normalized_datetime:
                    combined_datetime = f"{day} {datetime_label}".strip()

            title = self._trim_agenda_title(event.get("title", ""))
            description = self._clean_agenda_inline_text(event.get("description", ""))
            location = self._clean_agenda_inline_text(event.get("location", "") or event.get("space", ""))
            extra_info = self._clean_agenda_inline_text(event.get("extra_info", ""))

            if description:
                extracted_location, description = self._extract_agenda_location_from_description(description)
                if extracted_location and not location:
                    location = extracted_location
                description, extracted_extra = self._extract_agenda_extra_info_from_description(description)
                if extracted_extra and not extra_info:
                    extra_info = extracted_extra

            if not title and not description:
                continue

            items.append({
                "title": title,
                "datetime_label": combined_datetime,
                "location": location,
                "description": description,
                "extra_info": extra_info,
                "image_ref": "",
            })

        return items

    def _sanitize_agenda_items(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not items:
            return []

        sanitized: List[Dict[str, Any]] = []
        seen_signatures = set()

        for item in items:
            title = re.sub(r"^[\-–—•:;]+\s*", "", self._trim_agenda_title(item.get("title", "")))
            datetime_label = self._clean_agenda_inline_text(item.get("datetime_label", ""))
            location = self._clean_agenda_inline_text(item.get("location", ""))
            description = re.sub(r"^[\-–—•:;]+\s*", "", self._clean_agenda_inline_text(item.get("description", "")))
            extra_info = self._clean_agenda_inline_text(item.get("extra_info", ""))
            image_ref = self._clean_text_line(item.get("image_ref", ""))

            if description:
                extracted_location, description = self._extract_agenda_location_from_description(description)
                if extracted_location and not location:
                    location = extracted_location
                description, extracted_extra = self._extract_agenda_extra_info_from_description(description)
                if extracted_extra and not extra_info:
                    extra_info = extracted_extra

            if self._is_low_quality_activity_title(title):
                if description and not self._is_low_quality_activity_title(description):
                    title = self._limit_text(description, 140)
                    description = ""
                elif location and not self._is_low_quality_activity_title(location):
                    title = self._limit_text(location, 140)

            if self._is_calendar_heading_title(title) and description and not self._is_low_quality_activity_title(description):
                title = self._limit_text(description, 140)
                description = ""

            if not title and description:
                title = self._limit_text(description, 140)
                description = ""

            if len(title) > 140 and not description:
                split_match = re.search(r"\s+(?:Amb|Recital|Presentaci[oó]|Comentem|Dinamitzat|Organitza)\b", title)
                if split_match:
                    tail = self._clean_text_line(title[split_match.start():])
                    title = self._clean_text_line(title[:split_match.start()])
                    if tail:
                        description = tail

            if not title and not datetime_label and not location and not description:
                continue

            if self._is_low_quality_activity_title(title) and not (datetime_label or location or description):
                continue

            signature = self._normalize_token("|".join([title, datetime_label, location, description, extra_info]))
            if signature and signature in seen_signatures:
                continue
            if signature:
                seen_signatures.add(signature)

            sanitized.append({
                "title": title,
                "datetime_label": datetime_label,
                "location": location,
                "description": description,
                "extra_info": extra_info,
                "image_ref": image_ref,
            })

        return sanitized

    def _agenda_items_quality_score(self, items: List[Dict[str, Any]]) -> tuple[int, int, int, int, int, int, int, int]:
        valid_titles = 0
        datetime_count = 0
        location_count = 0
        description_count = 0
        low_quality_titles = 0
        duplicates = 0
        malformed_titles = 0
        seen_titles: Dict[str, int] = {}

        for item in items:
            title = self._clean_text_line(item.get("title", ""))
            if self._is_low_quality_activity_title(title):
                low_quality_titles += 1
            else:
                valid_titles += 1
            if len(title) > 120 or re.search(r"\*|_", title):
                malformed_titles += 1

            if self._clean_text_line(item.get("datetime_label", "")):
                datetime_count += 1
            if self._clean_text_line(item.get("location", "")):
                location_count += 1
            if self._clean_text_line(item.get("description", "")):
                description_count += 1

            normalized_title = self._normalize_token(title)
            if normalized_title:
                seen_titles[normalized_title] = seen_titles.get(normalized_title, 0) + 1

        for count in seen_titles.values():
            if count > 1:
                duplicates += count - 1

        quality = (
            valid_titles * 6
            + datetime_count * 3
            + location_count * 2
            + description_count
            - low_quality_titles * 5
            - duplicates * 2
            - malformed_titles * 3
        )

        return (
            quality,
            valid_titles,
            datetime_count,
            location_count,
            description_count,
            -low_quality_titles,
            -duplicates,
            len(items),
        )

    def _is_low_quality_activity_title(self, value: str) -> bool:
        normalized = self._normalize_token(value).replace("-", " ")
        if not normalized:
            return True
        if normalized in AGENDA_LOW_QUALITY_TITLES:
            return True
        compact = normalized.replace(" ", "")
        return len(compact) <= 2

    def _is_calendar_heading_title(self, value: str) -> bool:
        normalized = self._normalize_token(value).replace("-", " ")
        if not normalized:
            return False

        tokens = [token for token in re.split(r"\s+", normalized) if token]
        if not tokens:
            return False

        month_tokens = set(MONTH_NAME_TO_NUMBER.keys())

        def is_month_token(token: str) -> bool:
            if token in month_tokens:
                return True
            if token.startswith("de") and token[2:] in month_tokens:
                return True
            if token.startswith("d") and token[1:] in month_tokens:
                return True
            return False

        has_day = any(token in AGENDA_DAY_TOKENS for token in tokens)
        has_month = any(is_month_token(token) for token in tokens)
        if not has_day and not has_month:
            return False

        for token in tokens:
            if token in AGENDA_DAY_TOKENS:
                continue
            if token in {"d", "de", "del", "i"}:
                continue
            if token.isdigit():
                continue
            if is_month_token(token):
                continue
            return False

        return True

    def _build_agenda_date_fields(
        self,
        fields: Dict[str, Any],
        items: List[Dict[str, Any]],
        extracted_text: str,
    ) -> Dict[str, Any]:
        reference_year = self._infer_reference_year(extracted_text)

        event_date = self._to_iso_date(fields.get("event_date"), reference_year)
        start_date = self._to_iso_date(fields.get("start_date"), reference_year)
        end_date = self._to_iso_date(fields.get("end_date"), reference_year)

        search_dates = self._normalize_iso_date_list(fields.get("search_dates"), reference_year)
        if not search_dates:
            search_dates = self._normalize_iso_date_list(fields.get("search_dates_string"), reference_year)

        item_dates: List[str] = []
        for item in items:
            item_dates.extend(self._extract_iso_dates_from_text(item.get("datetime_label", ""), reference_year))

        text_dates = self._extract_iso_dates_from_text(extracted_text, reference_year)
        prominent_text_dates = self._extract_prominent_agenda_dates(extracted_text, reference_year)

        if not item_dates:
            fallback_dates = prominent_text_dates or text_dates
            if fallback_dates:
                return self._build_agenda_date_fields_without_items(fields, fallback_dates)

        all_dates = self._deduplicate_iso_dates(search_dates + item_dates)
        if not all_dates and text_dates:
            all_dates = self._deduplicate_iso_dates(text_dates)

        if event_date:
            all_dates = self._deduplicate_iso_dates([event_date] + all_dates)
        if start_date:
            all_dates = self._deduplicate_iso_dates([start_date] + all_dates)
        if end_date:
            all_dates = self._deduplicate_iso_dates(all_dates + [end_date])

        if start_date and end_date:
            range_dates = self._expand_date_range(start_date, end_date)
            if range_dates:
                all_dates = self._deduplicate_iso_dates(range_dates + all_dates)

        if not all_dates:
            return {
                "event_date": event_date,
                "start_date": start_date,
                "end_date": end_date,
                "search_dates": [],
            }

        if len(all_dates) == 1:
            return {
                "event_date": all_dates[0],
                "start_date": "",
                "end_date": "",
                "search_dates": all_dates,
            }

        resolved_start = start_date or all_dates[0]
        resolved_end = end_date or all_dates[-1]

        if start_date and end_date:
            expanded_search_dates = self._expand_date_range(resolved_start, resolved_end) or all_dates
        else:
            candidate_range = self._expand_date_range(resolved_start, resolved_end)
            if candidate_range and len(candidate_range) <= len(all_dates) + 1:
                expanded_search_dates = candidate_range
            else:
                expanded_search_dates = all_dates

        if resolved_start == resolved_end:
            return {
                "event_date": resolved_start,
                "start_date": "",
                "end_date": "",
                "search_dates": [resolved_start],
            }

        return {
            "event_date": "",
            "start_date": resolved_start,
            "end_date": resolved_end,
            "search_dates": expanded_search_dates,
        }

    def _build_agenda_date_fields_without_items(self, fields: Dict[str, Any], text_dates: List[str]) -> Dict[str, Any]:
        event_date = fields.get("event_date", "")
        start_date = fields.get("start_date", "")
        end_date = fields.get("end_date", "")

        configured_dates = self._normalize_iso_date_list(fields.get("search_dates") or fields.get("search_dates_string"))
        all_dates = self._deduplicate_iso_dates(configured_dates + text_dates)
        if not all_dates:
            return {
                "event_date": event_date,
                "start_date": start_date,
                "end_date": end_date,
                "search_dates": [],
            }

        if len(all_dates) == 1:
            return {
                "event_date": all_dates[0],
                "start_date": "",
                "end_date": "",
                "search_dates": [all_dates[0]],
            }

        max_span_days = 7
        if (datetime.strptime(all_dates[-1], "%Y-%m-%d") - datetime.strptime(all_dates[0], "%Y-%m-%d")).days > max_span_days:
            return {
                "event_date": "",
                "start_date": all_dates[0],
                "end_date": all_dates[-1],
                "search_dates": all_dates,
            }

        expanded = self._expand_date_range(all_dates[0], all_dates[-1])
        return {
            "event_date": "",
            "start_date": all_dates[0],
            "end_date": all_dates[-1],
            "search_dates": expanded or all_dates,
        }

    def _extract_prominent_agenda_dates(self, text: str, reference_year: Optional[int] = None) -> List[str]:
        lines = [self._clean_text_line(line) for line in str(text or "").splitlines() if self._clean_text_line(line)]
        if not lines:
            return []

        prominent: List[str] = []
        for line in lines[:20]:
            if len(line) > 80:
                continue
            normalized = self._normalize_token(line)
            if normalized in {"programa", "programacio"}:
                continue
            if not (self._looks_like_agenda_day_heading(line) or re.search(r"\b\d{1,2}\b", line)):
                continue
            prominent.extend(self._extract_iso_dates_from_text(line, reference_year))

        return self._deduplicate_iso_dates(prominent)

    def _build_agenda_activity_export_fields(
        self,
        items: List[Dict[str, Any]],
        fallback_iso_date: str,
    ) -> Dict[str, str]:
        items = self._sanitize_agenda_items(items)
        if not items:
            return {
                "activity_titles": "",
                "activity_dates": "",
                "activity_locations": "",
                "activity_descriptions": "",
                "activity_extra_info": "",
                "activity_images": "",
                "activities_backend": "",
            }

        activity_titles: List[str] = []
        activity_dates: List[str] = []
        activity_locations: List[str] = []
        activity_descriptions: List[str] = []
        activity_extra_info: List[str] = []
        activity_images: List[str] = []
        activities_backend: List[str] = []

        fallback_activity_date = self._to_wp_activity_date(fallback_iso_date, fallback_iso_date)

        for item in items:
            title = self._clean_text_line(item.get("title", ""))
            if not title:
                title = self._clean_text_line(item.get("description", ""))
            if not title:
                title = "Activitat"

            datetime_source = " ".join(
                part for part in [
                    item.get("datetime_label", ""),
                    item.get("title", ""),
                    item.get("description", ""),
                    item.get("extra_info", ""),
                ]
                if str(part or "").strip()
            )
            datetime_value = self._to_wp_activity_date(datetime_source, fallback_iso_date)
            if not datetime_value:
                datetime_value = fallback_activity_date

            activity_titles.append(title)
            activities_backend.append(title)
            activity_dates.append(datetime_value)
            activity_locations.append(self._clean_text_line(item.get("location", "")))
            activity_descriptions.append(self._to_activity_html(item.get("description", "")))
            activity_extra_info.append(self._to_activity_html(item.get("extra_info", "")))
            activity_images.append(self._clean_text_line(item.get("image_ref", "")))

        return {
            "activity_titles": "|".join(activity_titles),
            "activity_dates": "|".join(activity_dates),
            "activity_locations": "|".join(activity_locations),
            "activity_descriptions": "|".join(activity_descriptions),
            "activity_extra_info": "|".join(activity_extra_info),
            "activity_images": "|".join(activity_images),
            "activities_backend": "|".join(activities_backend),
        }

    def _to_activity_html(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "<p></p>"

        if re.match(r"(?is)^<p(?:\\s[^>]*)?>.*</p>$", raw):
            return raw

        clean = self._clean_text_line(self._strip_html(raw))
        return f"<p>{html.escape(clean)}</p>" if clean else "<p></p>"

    def _to_wp_activity_date(self, text: str, fallback_iso_date: str) -> str:
        reference_year = self._infer_reference_year(text or fallback_iso_date)
        iso_dates = self._extract_iso_dates_from_text(text, reference_year)
        if len(iso_dates) > 1:
            prioritized = self._extract_prominent_agenda_dates(text, reference_year)
            if prioritized:
                iso_dates = prioritized + [date for date in iso_dates if date not in prioritized]
        iso_date = iso_dates[0] if iso_dates else self._to_iso_date(fallback_iso_date, reference_year)
        if not iso_date:
            return ""

        parsed_time = self._extract_time_from_text(text)
        if parsed_time:
            return f"{datetime.strptime(iso_date, '%Y-%m-%d').strftime('%m/%d/%Y')} {parsed_time}"

        try:
            return datetime.strptime(iso_date, "%Y-%m-%d").strftime("%m/%d/%Y")
        except Exception:
            return ""

    def _extract_time_from_text(self, text: str) -> str:
        source = self._clean_text_line(text)
        if not source:
            return ""

        range_match = re.search(
            r"\b(?:a\s+partir\s+de\s+les|de\s+les|de\s+|a\s+les|les)?\s*(\d{1,2})(?::|\.)(\d{2})\s*h?\b",
            source,
            flags=re.IGNORECASE,
        )
        if range_match:
            hour = int(range_match.group(1))
            minute = int(range_match.group(2))
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"

        hour_only_match = re.search(
            r"\b(?:a\s+partir\s+de\s+les|de\s+les|de\s+|a\s+les|les)?\s*(\d{1,2})\s*h\b",
            source,
            flags=re.IGNORECASE,
        )
        if hour_only_match:
            hour = int(hour_only_match.group(1))
            if 0 <= hour <= 23:
                return f"{hour:02d}:00"

        return ""

    def _normalize_iso_date_list(self, value: Any, reference_year: Optional[int] = None) -> List[str]:
        raw_values: List[str] = []
        if isinstance(value, list):
            raw_values = [str(item) for item in value if str(item or "").strip()]
        elif isinstance(value, str):
            separators = ["|", ",", ";", "\n"]
            chunks = [value]
            for separator in separators:
                next_chunks = []
                for chunk in chunks:
                    next_chunks.extend(chunk.split(separator))
                chunks = next_chunks
            raw_values = [chunk.strip() for chunk in chunks if chunk.strip()]

        normalized: List[str] = []
        for raw in raw_values:
            normalized.extend(self._extract_iso_dates_from_text(raw, reference_year))
            direct = self._to_iso_date(raw, reference_year)
            if direct:
                normalized.append(direct)
        return self._deduplicate_iso_dates(normalized)

    def _extract_iso_dates_from_text(self, text: str, reference_year: Optional[int] = None) -> List[str]:
        source = str(text or "")
        default_year = reference_year or datetime.now().year
        dates: List[str] = []

        range_month_pattern = re.compile(
            r"\b(?:[A-Za-zÀ-ÿ]+\s+)?(\d{1,2})\s*(?:i|y)\s*(?:[A-Za-zÀ-ÿ]+\s+)?(\d{1,2})\s*(?:(?:de|d['’])\s*)?([A-Za-zÀ-ÿ]+)(?:\s*(?:(?:de|d['’])\s*)?(\d{2,4})(?!\s*[:h]))?\b",
            re.IGNORECASE,
        )
        for match in range_month_pattern.finditer(source):
            left_day = int(match.group(1))
            right_day = int(match.group(2))
            month = self._month_from_name(match.group(3))
            if not month:
                continue
            year_raw = match.group(4)
            year = int(year_raw) if year_raw else default_year
            if year < 100:
                year += 2000
            left_iso = self._build_iso_date(year, month, left_day)
            right_iso = self._build_iso_date(year, month, right_day)
            if left_iso:
                dates.append(left_iso)
            if right_iso:
                dates.append(right_iso)

        for match in re.finditer(r"\b(\d{4})[/-](\d{1,2})[/-](\d{1,2})\b", source):
            iso = self._build_iso_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
            if iso:
                dates.append(iso)

        for match in re.finditer(r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{2,4})\b", source):
            left = int(match.group(1))
            right = int(match.group(2))
            year = int(match.group(3))
            if year < 100:
                year += 2000

            day = left
            month = right
            if left <= 12 and right > 12:
                month = left
                day = right

            iso = self._build_iso_date(year, month, day)
            if iso:
                dates.append(iso)

        month_pattern = re.compile(
            r"\b(\d{1,2})\s*(?:(?:de|d['’])\s*)?([A-Za-zÀ-ÿ]+)(?:\s*(?:(?:de|d['’])\s*)?(\d{2,4})(?!\s*[:h]))?\b",
            re.IGNORECASE,
        )
        for match in month_pattern.finditer(source):
            day = int(match.group(1))
            month = self._month_from_name(match.group(2))
            if not month:
                continue
            year_raw = match.group(3)
            year = int(year_raw) if year_raw else default_year
            if year < 100:
                year += 2000
            iso = self._build_iso_date(year, month, day)
            if iso:
                dates.append(iso)

        month_first_pattern = re.compile(r"\b([A-Za-zÀ-ÿ]+)\s+(\d{1,2})(?!\d)(?!\s*[:h])(?:,?\s+(\d{2,4}))?\b")
        for match in month_first_pattern.finditer(source):
            prefix_window = source[max(0, match.start() - 20):match.start()].lower()
            if re.search(r"\b(?:dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\s*$", prefix_window):
                continue
            month = self._month_from_name(match.group(1))
            if not month:
                continue
            day = int(match.group(2))
            year_raw = match.group(3)
            year = int(year_raw) if year_raw else default_year
            if year < 100:
                year += 2000
            iso = self._build_iso_date(year, month, day)
            if iso:
                dates.append(iso)

        valid_month_values = set(MONTH_NAME_TO_NUMBER.values())

        day_name_pattern = re.compile(r"\b(?:dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|miércoles|jueves|viernes|sabado|sábado|domingo)\b", re.IGNORECASE)

        filtered_dates: List[str] = []
        for iso in self._deduplicate_iso_dates(dates):
            if not day_name_pattern.search(source):
                filtered_dates.append(iso)
                continue

            month_value = int(iso[5:7])
            if month_value in valid_month_values:
                filtered_dates.append(iso)

        return self._deduplicate_iso_dates(filtered_dates)

    def _month_from_name(self, value: str) -> int:
        normalized = self._normalize_token(value).replace(" ", "")
        if normalized.startswith("de") and normalized[2:] in MONTH_NAME_TO_NUMBER:
            return MONTH_NAME_TO_NUMBER[normalized[2:]]
        if normalized.startswith("d") and normalized[1:] in MONTH_NAME_TO_NUMBER:
            return MONTH_NAME_TO_NUMBER[normalized[1:]]
        return MONTH_NAME_TO_NUMBER.get(normalized, 0)

    def _build_iso_date(self, year: int, month: int, day: int) -> str:
        try:
            parsed = datetime(year, month, day)
            return parsed.strftime("%Y-%m-%d")
        except Exception:
            return ""

    def _to_iso_date(self, value: Any, reference_year: Optional[int] = None) -> str:
        if not value:
            return ""
        extracted = self._extract_iso_dates_from_text(str(value), reference_year)
        return extracted[0] if extracted else ""

    def _deduplicate_iso_dates(self, dates: List[str]) -> List[str]:
        unique = sorted({date for date in dates if re.match(r"^\d{4}-\d{2}-\d{2}$", date)})
        return unique

    def _expand_date_range(self, start_date: str, end_date: str) -> List[str]:
        if not start_date or not end_date:
            return []
        try:
            start = datetime.strptime(start_date, "%Y-%m-%d")
            end = datetime.strptime(end_date, "%Y-%m-%d")
        except Exception:
            return []

        if end < start:
            start, end = end, start
        total_days = (end - start).days
        if total_days > 366:
            return [start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")]

        return [
            (start + timedelta(days=offset)).strftime("%Y-%m-%d")
            for offset in range(total_days + 1)
        ]

    def _infer_reference_year(self, text: str) -> int:
        for match in re.finditer(r"\b(20\d{2})\b", str(text or "")):
            year = int(match.group(1))
            if 2000 <= year <= 2100:
                return year
        return datetime.now().year

    def _normalize_agenda_category(self, value: str) -> str:
        if not value:
            return ""

        chunks = [chunk.strip() for chunk in re.split(r"[|,;/]", value) if chunk.strip()]
        if not chunks:
            chunks = [self._clean_text_line(value)]

        normalized_options = {
            self._normalize_token(option): option
            for option in AGENDA_CATEGORY_OPTIONS
        }

        for chunk in chunks:
            normalized_chunk = self._normalize_token(chunk)
            if normalized_chunk in normalized_options:
                return normalized_options[normalized_chunk]
            for token, option in normalized_options.items():
                if normalized_chunk == token or normalized_chunk in token or token in normalized_chunk:
                    return option
        return ""

    def _infer_agenda_category(self, text: str, items: List[Dict[str, Any]]) -> str:
        composed = [str(text or "")]
        for item in items:
            composed.extend([
                item.get("title", ""),
                item.get("datetime_label", ""),
                item.get("location", ""),
                item.get("description", ""),
                item.get("extra_info", ""),
            ])

        normalized = self._normalize_token("\n".join(composed))
        if not normalized:
            return ""

        best_category = ""
        best_score = 0
        tied = False

        for category, keywords in AGENDA_CATEGORY_KEYWORDS.items():
            score = sum(1 for keyword in keywords if self._normalize_token(keyword) in normalized)
            if score > best_score:
                best_category = category
                best_score = score
                tied = False
            elif score and score == best_score:
                tied = True

        if best_score < 2 or tied:
            return ""
        return best_category

    def _extract_content_items_from_source(self, body_text: str, category: str) -> List[Dict[str, Any]]:
        if category == "AGENDA":
            markdown_items = self._sanitize_agenda_items(self._extract_markdown_agenda_items(body_text))
            parser_items = self._sanitize_agenda_items(
                self._build_source_agenda_items_with_day_context(parse_agenda(body_text).get("events", []))
            )
            candidates = [items for items in [markdown_items, parser_items] if items]
            if not candidates:
                return []
            return max(candidates, key=self._agenda_items_quality_score)

        chunks = self._source_chunks(body_text)
        if len(chunks) < 4:
            return []

        sections = []
        current_section = None
        for chunk in chunks:
            if self._is_source_section_heading(chunk, category):
                if current_section:
                    sections.append(current_section)
                current_section = {"title": chunk, "lines": []}
            elif current_section is not None:
                current_section["lines"].append(chunk)

        if current_section:
            sections.append(current_section)

        if len(sections) < 2:
            return []

        items = []
        for section in sections:
            lines = [self._clean_text_line(line) for line in section.get("lines", []) if self._clean_text_line(line)]
            datetime_label = self._extract_datetime_label(lines)
            location = self._extract_location_label(lines)
            content_lines = [line for line in lines if line and line != datetime_label and line != location]
            heading_label = self._format_source_heading(section.get("title", ""))
            item_title = heading_label
            description_lines = content_lines
            extra_info = ""

            if content_lines:
                item_title = content_lines[0]
                description_lines = content_lines[1:]
                if heading_label and self._normalize_token(heading_label) != self._normalize_token(item_title):
                    extra_info = heading_label

            items.append({
                "title": item_title,
                "datetime_label": datetime_label,
                "location": location,
                "description": " ".join(description_lines),
                "extra_info": extra_info,
                "image_ref": "",
            })
        return items

    def _assign_activity_image_refs(
        self,
        activities: List[Dict[str, Any]],
        editorial_images: List[ImageProcessingResult],
        selection_images: List[ImageProcessingResult],
        title: str,
        summary: str,
        body_text: str,
    ) -> List[Dict[str, Any]]:
        if not activities or not editorial_images:
            return activities

        source_image_map = {image.source_file_id: image for image in editorial_images}
        assigned_source_ids = set()

        for activity in activities:
            if activity.get("image_ref"):
                matching = self._find_editorial_image_by_path(activity.get("image_ref", ""), editorial_images)
                if matching:
                    assigned_source_ids.add(matching.source_file_id)

        for activity in activities:
            if activity.get("image_ref"):
                continue
            matched = self._match_image_to_activity_by_filename(activity, editorial_images, assigned_source_ids)
            if matched:
                activity["image_ref"] = matched.optimized_path or ""
                assigned_source_ids.add(matched.source_file_id)

        remaining_activities = [activity for activity in activities if not activity.get("image_ref")]
        remaining_selection_images = [image for image in selection_images if image.source_file_id not in assigned_source_ids]
        if remaining_activities and remaining_selection_images:
            ai_matches = self._match_activity_images_with_ai(title, summary, body_text, remaining_activities, remaining_selection_images)
            for activity_index, source_file_id in ai_matches.items():
                if activity_index < 0 or activity_index >= len(remaining_activities):
                    continue
                editorial_image = source_image_map.get(source_file_id)
                if not editorial_image or not editorial_image.optimized_path:
                    continue
                remaining_activities[activity_index]["image_ref"] = editorial_image.optimized_path
                assigned_source_ids.add(source_file_id)

        return activities

    def _find_editorial_image_by_path(
        self,
        image_ref: str,
        editorial_images: List[ImageProcessingResult],
    ) -> Optional[ImageProcessingResult]:
        image_name = self._normalize_image_stem(image_ref)
        for image in editorial_images:
            if self._normalize_image_stem(image.optimized_path or "") == image_name:
                return image
        return None

    def _match_image_to_activity_by_filename(
        self,
        activity: Dict[str, Any],
        editorial_images: List[ImageProcessingResult],
        assigned_source_ids: set,
    ) -> Optional[ImageProcessingResult]:
        activity_tokens = self._extract_activity_tokens(activity)
        if not activity_tokens:
            return None

        best_image = None
        best_score = 0
        for image in editorial_images:
            if image.source_file_id in assigned_source_ids:
                continue
            image_tokens = self._extract_image_name_tokens(image.optimized_path or "")
            score = len(activity_tokens.intersection(image_tokens))
            if score > best_score:
                best_score = score
                best_image = image

        return best_image if best_score >= 1 else None

    def _match_activity_images_with_ai(
        self,
        title: str,
        summary: str,
        body_text: str,
        activities: List[Dict[str, Any]],
        images: List[ImageProcessingResult],
    ) -> Dict[int, Any]:
        if not activities or not images:
            return {}

        try:
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client(use_ocr_vision=True)
            if not client:
                return {}
        except Exception:
            return {}

        prepared_images = []
        for idx, image in enumerate(images[:8], start=1):
            payload = self._build_llm_image_payload(image.optimized_path or image.thumbnail_path or "")
            if not payload:
                continue
            prepared_images.append({"index": idx, "source_file_id": image.source_file_id, "payload": payload})

        if not prepared_images:
            return {}

        activities_text = []
        for idx, activity in enumerate(activities, start=1):
            activities_text.append(
                f"{idx}. title={activity.get('title', '')} | datetime_label={activity.get('datetime_label', '')} | location={activity.get('location', '')} | description={activity.get('description', '')}"
            )

        prompt = (
            f"Article principal: {title}\n"
            f"Resum: {summary}\n"
            f"Context: {self._limit_text(body_text, 1200)}\n\n"
            "A continuacio tens una llista d'elements del contingut. Les imatges adjuntes estan en el mateix ordre indicat. "
            "Relaciona cada imatge amb l'element mes probable si representa clarament aquell element concret. "
            "No assignis una imatge si no hi ha correspondencia clara.\n\n"
            f"Elements:\n{chr(10).join(activities_text)}\n\n"
            "Respon nomes amb JSON valid: {\"matches\": [{\"image_index\": 1, \"item_index\": 2}]}"
        )

        try:
            response = client.chat(prompt, images=[item["payload"] for item in prepared_images], max_tokens=300)
            parsed = json.loads(self._extract_json_object(response or "{}"))
        except Exception:
            return {}

        matches = parsed.get("matches", []) if isinstance(parsed, dict) else []
        if not isinstance(matches, list):
            return {}

        resolved: Dict[int, Any] = {}
        used_images = set()
        for match in matches:
            if not isinstance(match, dict):
                continue
            image_index = int(match.get("image_index", 0) or 0)
            item_index = int(match.get("item_index", 0) or 0)
            if image_index < 1 or item_index < 1:
                continue
            if image_index in used_images or (item_index - 1) in resolved:
                continue
            prepared = next((item for item in prepared_images if item["index"] == image_index), None)
            if not prepared:
                continue
            resolved[item_index - 1] = prepared["source_file_id"]
            used_images.add(image_index)
        return resolved

    def _extract_activity_tokens(self, activity: Dict[str, Any]) -> set:
        text = " ".join([
            activity.get("title", ""),
            activity.get("location", ""),
            activity.get("description", ""),
            activity.get("extra_info", ""),
        ])
        return self._tokenize_for_matching(text)

    def _extract_image_name_tokens(self, image_path: str) -> set:
        stem = self._normalize_image_stem(image_path)
        return self._tokenize_for_matching(stem)

    def _normalize_image_stem(self, image_path: str) -> str:
        file_name = self._extract_file_name(image_path)
        stem = os.path.splitext(file_name)[0]
        stem = re.sub(r"(?:_opt|_thumb)$", "", stem, flags=re.IGNORECASE)
        return stem

    def _tokenize_for_matching(self, text: str) -> set:
        normalized = self._normalize_token(text)
        tokens = {token for token in re.split(r"[^a-z0-9]+", normalized) if len(token) >= 3}
        return tokens.difference({"img", "foto", "image", "images", "jpeg", "jpg", "png", "webp"})

    def _extract_json_object(self, text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned or "{}"

    def _insert_inline_images(
        self,
        body_html: str,
        images: List[ImageProcessingResult],
        featured_image_ref: Optional[Any],
        title: str,
        listing_items: Optional[List[Dict[str, Any]]] = None,
    ) -> tuple[str, List[str]]:
        listing_items = listing_items or []
        inserted_images: List[str] = []
        inline_images = [
            image for image in images
            if image.source_file_id != featured_image_ref and self._can_embed_image(image.optimized_path or "")
        ]
        if not inline_images and not any(item.get("image_ref") for item in listing_items):
            return body_html, []

        blocks = self._split_html_blocks(body_html)
        if not blocks:
            blocks = [body_html] if body_html.strip() else []

        blocks = self._insert_listing_images_into_blocks(blocks, listing_items, inserted_images)
        used_image_refs = set(inserted_images)
        inline_images = [image for image in inline_images if (image.optimized_path or "") not in used_image_refs]

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

    def _insert_listing_images_into_blocks(
        self,
        blocks: List[str],
        listing_items: List[Dict[str, Any]],
        inserted_images: List[str],
    ) -> List[str]:
        if not blocks or not listing_items:
            return blocks

        used_refs = set()
        for item in listing_items:
            image_ref = item.get("image_ref", "") or ""
            if not self._can_embed_image(image_ref) or image_ref in used_refs:
                continue
            block_index = self._find_best_block_index_for_item(item, blocks)
            if block_index is None:
                continue
            insert_at = min(len(blocks), block_index + 1)
            blocks.insert(insert_at, self._render_inline_image_block(image_ref, item.get("title", "")))
            inserted_images.append(image_ref)
            used_refs.add(image_ref)
        return blocks

    def _ensure_source_text_is_preserved(
        self,
        body_html: str,
        body_text: str,
        summary: str,
        category: str,
        listing_items: List[Dict[str, Any]],
    ) -> str:
        source_chunks = self._source_chunks(body_text)
        generated_plain = self._clean_text_line(self._strip_html(body_html))
        source_plain = self._clean_text_line(body_text)

        if not source_plain:
            return body_html

        needs_preservation = False
        if category == "AGENDA" and len(listing_items) >= 2:
            needs_preservation = True
        elif len(source_plain) > max(1, len(generated_plain)) * 1.35 and len(source_chunks) >= 8:
            needs_preservation = True

        if not needs_preservation:
            return body_html

        preserved_html = self._build_source_preserving_body_html(body_text, summary, category, listing_items, body_html)
        return preserved_html or body_html

    def _build_source_preserving_body_html(self, body_text: str, summary: str, category: str, listing_items: List[Dict[str, Any]], draft_body_html: str) -> str:
        if category == "AGENDA":
            parsed = parse_agenda(body_text)
            html_parts = []
            events = parsed.get("events", [])
            intro_blocks = self._extract_agenda_intro_blocks(draft_body_html, events)
            intro_section_parts = []
            for block in intro_blocks:
                intro_section_parts.append(self._style_agenda_intro_block(block))
            if not intro_section_parts:
                fallback_summary = self._clean_agenda_summary(summary)
                if fallback_summary:
                    intro_section_parts.append(f'<p>{html.escape(fallback_summary)}</p>')
            if intro_section_parts:
                html_parts.append('<section class="agenda-intro">')
                html_parts.extend(intro_section_parts)
                html_parts.append('</section>')
            for highlight in parsed.get("highlights", []):
                html_parts.append(render_highlight_box(highlight))
            include_program_markup = not bool(listing_items)
            if include_program_markup and events:
                html_parts.append('<h2 class="agenda-program-title">Programa</h2>')
                html_parts.append(render_agenda_html(events))
            return "\n".join(part for part in html_parts if part)

        chunks = self._source_chunks(body_text)
        if not chunks:
            return ""

        html_parts = []
        summary_text = self._clean_text_line(summary)
        if summary_text:
            html_parts.append(f"<p>{html.escape(summary_text)}</p>")

        if category == "AGENDA" and listing_items:
            intro_chunks = self._extract_intro_chunks_from_source(chunks, category)
            for chunk in intro_chunks:
                html_parts.append(f"<p>{html.escape(chunk)}</p>")
            for item in listing_items:
                html_parts.append(self._render_agenda_item_block(item))
            trailing_chunks = self._extract_trailing_chunks_from_source(chunks, category)
            for chunk in trailing_chunks:
                html_parts.append(f"<p>{html.escape(chunk)}</p>")
            return "\n".join(part for part in html_parts if part)

        current_section = None
        for chunk in chunks:
            if self._is_source_section_heading(chunk, category):
                if current_section:
                    html_parts.extend(current_section)
                heading_level = self._get_source_heading_level(chunk)
                tag = "h2" if heading_level <= 2 else "h3"
                current_section = [f"<{tag}>{html.escape(self._format_source_heading(chunk))}</{tag}>"]
                continue

            paragraph_html = f"<p>{html.escape(chunk)}</p>"
            if current_section is None:
                html_parts.append(paragraph_html)
            else:
                current_section.append(paragraph_html)

        if current_section:
            html_parts.extend(current_section)

        return "\n".join(html_parts)

    def _extract_agenda_intro_blocks(self, draft_body_html: str, events: Optional[List[Dict[str, Any]]] = None) -> List[str]:
        if not draft_body_html:
            return []
        blocks = self._split_html_blocks(draft_body_html)
        intro_blocks = []
        seen_intro_tokens: List[str] = []
        events = events or []
        reached_program_section = False
        for block in blocks:
            if 'class="agenda-' in block or 'class="panxing-inline-image"' in block or 'class="highlight-box"' in block:
                continue
            plain = self._clean_text_line(self._strip_html(block))
            if not plain:
                continue
            if self._looks_like_agenda_program_chunk(plain, events):
                reached_program_section = True
                continue
            if reached_program_section:
                continue
            if re.search(r"\b\d{1,2}(?::\d{2})?\s*h\b", plain.lower()):
                continue
            normalized_plain = self._normalize_token(plain)
            if normalized_plain and any(
                normalized_plain in existing or existing in normalized_plain
                for existing in seen_intro_tokens
            ):
                continue
            if normalized_plain:
                seen_intro_tokens.append(normalized_plain)
            intro_blocks.append(block)
            if len(intro_blocks) >= 4:
                break
        return intro_blocks

    def _clean_agenda_summary(self, summary: str) -> str:
        clean = self._clean_text_line(self._strip_html(summary))
        if not clean:
            return ""

        day_tokens = r"dilluns|dimarts|dimecres|dijous|divendres|dissabte|diumenge|lunes|martes|miercoles|jueves|viernes|sabado|domingo"
        clean = re.split(rf"(?i)\bprograma(?:ci[oó])?\b\s+(?=(?:{day_tokens})\b)", clean, maxsplit=1)[0].strip(" -,:;")
        clean = re.sub(rf"(?i)\b(?:{day_tokens})\b,?\s+\d{{1,2}}(?:\s*(?:de|d['’]))?\s+[a-zà-ÿ]+.*$", "", clean).strip(" -,:;")

        sentence_parts = [
            self._clean_text_line(part)
            for part in re.split(r"(?<=[.!?])\s+", clean)
            if self._clean_text_line(part)
        ]
        if sentence_parts:
            first_sentence = sentence_parts[0]
            if len(first_sentence) >= 45:
                clean = first_sentence
            elif len(sentence_parts) >= 2:
                clean = f"{first_sentence} {sentence_parts[1]}"

        return self._limit_text(clean, 220)

    def _looks_like_agenda_program_chunk(self, text: str, events: Optional[List[Dict[str, Any]]] = None) -> bool:
        clean = self._clean_text_line(self._strip_html(text))
        if not clean:
            return False

        normalized = self._normalize_token(clean).replace("-", " ")
        if normalized in {"programa", "programacio"}:
            return True
        if normalized.startswith("programa ") or normalized.startswith("programacio "):
            return True
        if self._looks_like_agenda_day_heading(clean):
            return True

        events = events or []
        normalized_clean = self._normalize_token(clean)
        for event in events:
            title = self._clean_text_line(event.get("title", ""))
            if not title:
                continue
            normalized_title = self._normalize_token(title)
            if not normalized_title:
                continue
            if len(normalized_title) >= 15 and (
                normalized_clean == normalized_title
                or normalized_clean in normalized_title
                or normalized_title in normalized_clean
            ):
                return True

        return False

    def _style_agenda_intro_block(self, block: str) -> str:
        if block.startswith("<h"):
            return block
        if block.startswith("<p"):
            plain = self._clean_text_line(self._strip_html(block))
            heading_level = self._get_source_heading_level(plain)
            if heading_level:
                tag = "h2" if heading_level <= 2 else "h3"
                return f'<{tag}>{html.escape(self._format_source_heading(plain))}</{tag}>'
            if self._looks_like_visual_heading(plain):
                return f'<h2>{html.escape(plain)}</h2>'
            return self._emphasize_leading_label(block)
        return block

    def _enhance_html_structure(self, body_html: str, category: str) -> str:
        blocks = self._split_html_blocks(body_html)
        if not blocks:
            return body_html

        enhanced = []
        heading_count = 0
        index = 0
        while index < len(blocks):
            block = blocks[index]
            list_item = self._extract_markdown_list_item(block)
            if list_item:
                items = [list_item]
                index += 1
                while index < len(blocks):
                    next_item = self._extract_markdown_list_item(blocks[index])
                    if not next_item:
                        break
                    items.append(next_item)
                    index += 1
                enhanced.append(self._render_html_list(items))
                continue

            if block.startswith("<p"):
                plain = self._clean_text_line(self._strip_html(block))
                heading_level = self._get_source_heading_level(plain)
                if heading_level:
                    tag = "h2" if heading_level <= 2 else "h3"
                    enhanced.append(f'<{tag}>{html.escape(self._format_source_heading(plain))}</{tag}>')
                    heading_count += 1
                    index += 1
                    continue
                if self._looks_like_visual_heading(plain):
                    tag = "h2" if heading_count == 0 else "h3"
                    enhanced.append(f'<{tag}>{html.escape(plain)}</{tag}>')
                    heading_count += 1
                    index += 1
                    continue
                block = self._emphasize_leading_label(block)
            enhanced.append(block)
            index += 1
        return "\n".join(enhanced)

    def _looks_like_visual_heading(self, text: str) -> bool:
        clean = self._clean_text_line(text)
        if not clean or len(clean) > 95:
            return False
        if self._get_source_heading_level(clean):
            return True
        if re.search(r"\b\d{1,2}(?::\d{2})?\s*h\b", clean.lower()):
            return False
        if clean.endswith(('.', '!', '?')):
            return False
        alpha_chars = [char for char in clean if char.isalpha()]
        if not alpha_chars:
            return False
        upper_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
        if upper_ratio >= 0.25:
            return True
        if len(clean.split()) <= 6 and not clean.endswith(('.', '!', '?')):
            return True
        return len(clean.split()) <= 8 and ":" in clean

    def _emphasize_leading_label(self, block: str) -> str:
        def replace(match: re.Match) -> str:
            label = self._clean_text_line(match.group(1))
            rest = match.group(2)
            return f"<p><strong>{html.escape(label)}:</strong>{rest}</p>"

        return re.sub(r"(?is)^<p>\s*([^:<]{2,45}):\s*(.+)</p>$", replace, block)

    def _extract_markdown_list_item(self, block: str) -> str:
        if not block.startswith("<p"):
            return ""
        plain = self._clean_text_line(self._strip_html(block))
        match = MARKDOWN_LIST_RE.match(plain)
        return self._clean_text_line(match.group(1)) if match else ""

    def _render_html_list(self, items: List[str]) -> str:
        rendered_items = "".join(f"<li>{html.escape(item)}</li>" for item in items if item)
        return f"<ul>{rendered_items}</ul>"

    def _get_source_heading_level(self, text: str) -> int:
        match = MARKDOWN_HEADING_RE.match(self._clean_text_line(text))
        return int(match.group(1)) if match else 0

    def _render_agenda_trailing_blocks(self, trailing_chunks: List[str]) -> List[str]:
        if not trailing_chunks:
            return []

        parts: List[str] = []
        for chunk in trailing_chunks:
            if chunk.isupper() or chunk.endswith(":"):
                parts.append(f'<h3 class="agenda-section">{html.escape(self._format_source_heading(chunk.rstrip(":")))}</h3>')
            elif chunk:
                if self._looks_like_support_subheading(chunk):
                    parts.append(f'<h4>{html.escape(chunk)}</h4>')
                else:
                    parts.append(f'<p>{html.escape(chunk)}</p>')
        return parts

    def _looks_like_support_subheading(self, text: str) -> bool:
        clean = self._clean_text_line(text)
        if not clean:
            return False
        if len(clean) > 50:
            return False
        if re.search(r"\bwww\.|\bhttps?://", clean.lower()):
            return False
        alpha_chars = [char for char in clean if char.isalpha()]
        if not alpha_chars:
            return False
        upper_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
        return upper_ratio >= 0.35 or len(clean.split()) <= 4

    def _render_agenda_item_block(self, item: Dict[str, Any]) -> str:
        parts = ['<section class="panxing-agenda-item" style="margin:0 0 26px 0; padding:18px 18px 16px; border:1px solid #eadfca; background:#fffdf8; border-radius:12px;">']
        if item.get("extra_info"):
            parts.append(f'<p style="margin:0 0 8px 0; font-size:12px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#92400e;">{html.escape(item.get("extra_info", ""))}</p>')
        if item.get("title"):
            parts.append(f'<h3 style="margin:0 0 10px 0; font-size:22px; line-height:1.25; color:#1f2937;">{html.escape(item.get("title", ""))}</h3>')
        if item.get("datetime_label"):
            parts.append(f'<p class="agenda-datetime" style="margin:0 0 6px 0; font-size:13px; font-weight:700; text-transform:uppercase; letter-spacing:0.03em; color:#b45309;">{html.escape(item.get("datetime_label", ""))}</p>')
        if item.get("location"):
            parts.append(f'<p class="agenda-location" style="margin:0 0 10px 0; font-size:14px; font-weight:600; color:#0f766e;">{html.escape(item.get("location", ""))}</p>')
        if item.get("description"):
            parts.append(f'<p style="margin:0; color:#374151;">{html.escape(item.get("description", ""))}</p>')
        if item.get("extra_info"):
            parts.append(f'<p style="margin:10px 0 0 0; font-size:13px; color:#6b7280;">{html.escape(item.get("extra_info", ""))}</p>')
        parts.append('</section>')
        return "".join(parts)

    def _extract_intro_chunks_from_source(self, chunks: List[str], category: str) -> List[str]:
        intro = []
        for chunk in chunks:
            if self._is_source_section_heading(chunk, category):
                break
            intro.append(chunk)
        return intro[:2]

    def _extract_trailing_chunks_from_source(self, chunks: List[str], category: str) -> List[str]:
        trailing = []
        seen_heading = False
        for chunk in chunks:
            if self._is_source_section_heading(chunk, category):
                seen_heading = True
                continue
            if not seen_heading:
                continue
            if chunk.lower().startswith("a mes") or chunk.lower().startswith("a més"):
                trailing.append(chunk)
        return trailing

    def _source_chunks(self, body_text: str) -> List[str]:
        raw_chunks = re.split(r"\n\s*\n+", body_text or "")
        return [self._clean_text_line(chunk) for chunk in raw_chunks if self._clean_text_line(chunk)]

    def _is_source_section_heading(self, chunk: str, category: str) -> bool:
        text = self._clean_text_line(chunk)
        if not text or len(text) > 90:
            return False
        if self._contains_datetime_hint(text):
            return False

        alpha_chars = [char for char in text if char.isalpha()]
        if not alpha_chars:
            return False
        upper_ratio = sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars)
        if upper_ratio >= 0.7:
            return True
        return False

    def _format_source_heading(self, text: str) -> str:
        clean = self._clean_text_line(text)
        marker_match = MARKDOWN_HEADING_RE.match(clean)
        if marker_match:
            clean = self._clean_text_line(marker_match.group(2))
        alpha_chars = [char for char in clean if char.isalpha()]
        if alpha_chars and sum(1 for char in alpha_chars if char.isupper()) / len(alpha_chars) >= 0.7:
            return clean.lower().capitalize()
        return clean

    def _extract_datetime_label(self, lines: List[str]) -> str:
        for line in lines:
            if self._contains_datetime_hint(line):
                return line
        return ""

    def _extract_location_label(self, lines: List[str]) -> str:
        venue_keywords = ["placa", "plaça", "biblioteca", "riera", "tmc", "odèon", "odeon", "teatre", "esglesia", "església", "parc", "passeig", "centre", "pavello", "pavelló"]
        for line in lines:
            if self._contains_datetime_hint(line):
                continue
            normalized = self._normalize_token(line)
            if any(keyword in normalized for keyword in venue_keywords):
                return line
            if line.isupper() and len(line.split()) <= 8:
                return line
        return ""

    def _contains_datetime_hint(self, text: str) -> bool:
        normalized = self._normalize_token(text)
        if re.search(r"\b\d{1,2}[./-]\d{1,2}(?:[./-]\d{2,4})?\b", text):
            return True
        if re.search(r"\b\d{1,2}(?:[:.]\d{2})?\s*h\b", normalized):
            return True
        return any(token in normalized for token in ["gener", "febrer", "marc", "abril", "maig", "juny", "juliol", "agost", "setembre", "octubre", "novembre", "desembre", "divendres", "dissabte", "diumenge", "dilluns", "dimarts", "dimecres", "dijous"])

    def _find_best_block_index_for_item(self, item: Dict[str, Any], blocks: List[str]) -> Optional[int]:
        item_tokens = self._extract_activity_tokens(item)
        if not item_tokens:
            return None

        best_index = None
        best_score = 0
        for index, block in enumerate(blocks):
            block_text = self._clean_text_line(self._strip_html(block))
            if not block_text:
                continue
            block_tokens = self._tokenize_for_matching(block_text)
            score = len(item_tokens.intersection(block_tokens))
            if re.search(r"(?is)^<h[2-4][^>]*>", block.strip()):
                score += 2
            if score > best_score:
                best_score = score
                best_index = index

        return best_index if best_score >= 1 else None

    def _prepare_listing_items(self, structured_fields: Dict[str, Any]) -> List[Dict[str, Any]]:
        if isinstance(structured_fields.get("content_items"), list):
            return self._normalize_activity_items(structured_fields.get("content_items"))
        if isinstance(structured_fields.get("activities"), list):
            return self._normalize_activity_items(structured_fields.get("activities"))
        return []

    def _looks_like_listing_category(self, category: str) -> bool:
        return category in {"AGENDA", "CULTURA", "ESPORTS", "TURISME_ACTIU", "NENS_I_JOVES", "GASTRONOMIA", "NOTICIES", "ENTREVISTES"}

    def _split_html_blocks(self, body_html: str) -> List[str]:
        block_pattern = re.compile(
            r"(?is)<(h[1-6]|p|ul|ol|blockquote|figure|div)(?:\s[^>]*)?>.*?</\1>"
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

    def _remove_summary_duplication_from_body(self, body_html: str, summary: str) -> str:
        clean_summary = self._normalize_token(self._strip_html(summary))
        if not clean_summary:
            return body_html

        blocks = self._split_html_blocks(body_html)
        if not blocks:
            return body_html

        filtered_blocks = []
        summary_tokens = self._tokenize_for_matching(clean_summary)
        leading_text_blocks = 0
        for block in blocks:
            block_text = self._normalize_token(self._strip_html(block))
            if not block_text:
                continue

            if not re.match(r"(?is)^<h[1-6][^>]*>", block.strip()):
                leading_text_blocks += 1

            if leading_text_blocks <= 4 and self._is_summary_duplicate_block(block_text, clean_summary, summary_tokens):
                continue

            filtered_blocks.append(block)

        if filtered_blocks:
            return "\n".join(filtered_blocks)

        shortened_first_block = self._trim_summary_from_first_block(blocks[0], clean_summary)
        if shortened_first_block:
            remainder = [shortened_first_block] + blocks[1:]
            return "\n".join(remainder)

        return body_html

    def _ensure_summary_not_duplicate_with_body(self, summary: str, body_html: str) -> str:
        clean_summary = self._clean_text_line(self._strip_html(summary))
        if not clean_summary:
            return summary

        blocks = self._split_html_blocks(body_html)
        if not blocks:
            return clean_summary

        first_text_block = ""
        for block in blocks[:4]:
            if re.match(r"(?is)^<h[1-6][^>]*>", block.strip()):
                continue
            first_text_block = self._clean_text_line(self._strip_html(block))
            if first_text_block:
                break

        if not first_text_block:
            return clean_summary

        normalized_summary = self._normalize_token(clean_summary)
        normalized_first_block = self._normalize_token(first_text_block)
        if not normalized_summary or not normalized_first_block:
            return clean_summary

        summary_tokens = self._tokenize_for_matching(normalized_summary)
        if not self._is_summary_duplicate_block(normalized_first_block, normalized_summary, summary_tokens):
            return clean_summary

        teaser = self._build_short_subheadline(clean_summary)
        if teaser and self._normalize_token(teaser) != normalized_first_block:
            return teaser

        return clean_summary

    def _build_short_subheadline(self, text: str) -> str:
        clean_text = self._clean_text_line(text)
        if not clean_text:
            return ""

        clauses = [segment.strip(" ,;:-") for segment in re.split(r"[,;:]", clean_text) if segment.strip()]
        if clauses:
            first_clause = self._limit_text(clauses[0], 160)
            if len(first_clause) >= 40:
                return first_clause

        words = clean_text.split()
        if len(words) <= 12:
            return self._limit_text(clean_text, 120)

        shortened = " ".join(words[:12]).rstrip(" ,;:-")
        return f"{shortened}..."

    def _trim_summary_from_first_block(self, first_block: str, clean_summary: str) -> str:
        stripped = first_block.strip()
        if not re.match(r"(?is)^<p[^>]*>.*</p>$", stripped):
            return ""

        plain = self._normalize_token(self._strip_html(stripped))
        if not plain:
            return ""

        plain_sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", plain) if segment.strip()]
        if not plain_sentences:
            return ""

        summary_sentences = [segment.strip() for segment in re.split(r"(?<=[.!?])\s+", clean_summary) if segment.strip()]
        summary_head = summary_sentences[0] if summary_sentences else clean_summary

        if not (plain.startswith(clean_summary) or plain.startswith(summary_head)):
            return ""

        remaining_sentences = plain_sentences[:]
        while remaining_sentences:
            head = self._normalize_token(remaining_sentences[0])
            if head and (head in clean_summary or clean_summary.startswith(head)):
                remaining_sentences.pop(0)
                continue
            break

        if not remaining_sentences:
            return ""

        remaining_text = self._clean_text_line(" ".join(remaining_sentences))
        if len(remaining_text) < 30:
            return ""

        return f"<p>{html.escape(remaining_text)}</p>"

    def _is_summary_duplicate_block(self, block_text: str, clean_summary: str, summary_tokens: set) -> bool:
        if clean_summary == block_text or clean_summary in block_text:
            return True

        if block_text in clean_summary and len(block_text) >= max(40, int(len(clean_summary) * 0.2)):
            return True

        block_tokens = self._tokenize_for_matching(block_text)
        if block_tokens and summary_tokens:
            overlap_ratio = len(block_tokens.intersection(summary_tokens)) / max(1, len(block_tokens))
            if overlap_ratio >= 0.85 and len(block_tokens) >= 6:
                return True

            first_words = " ".join(block_text.split()[:12])
            if (
                len(first_words) >= 35
                and len(block_text) <= int(len(clean_summary) * 1.15)
                and self._normalize_token(first_words) in clean_summary
            ):
                return True

        return False

    def _sanitize_body_html(self, body_html: str, body_text: str, title: str, source_context: Dict[str, Any]) -> str:
        normalized_body = (body_html or "").strip()
        if not normalized_body:
            normalized_body = self._body_html_from_text(body_text, title)

        normalized_body = re.sub(r"(?is)<p>\s*(?:amic|redacci[oó]|redaccio)\s*</p>\s*$", "", normalized_body).strip()
        normalized_body = self._apply_highlighted_block_format(normalized_body)

        author_note = self._build_author_note_html(source_context.get("author_source", ""))
        if author_note and self._normalize_token(self._strip_html(author_note)) not in self._normalize_token(self._strip_html(normalized_body)):
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
