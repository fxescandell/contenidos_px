import json
import os
import unicodedata
from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.core.enums import ContentCategory
from app.services.settings.service import SettingsResolver


CATEGORY_LABELS: Dict[str, str] = {
    ContentCategory.AGENDA.value: "Agenda",
    ContentCategory.NOTICIES.value: "Noticies",
    ContentCategory.ESPORTS.value: "Esports",
    ContentCategory.TURISME_ACTIU.value: "Turisme actiu",
    ContentCategory.NENS_I_JOVES.value: "Nens i joves",
    ContentCategory.CULTURA.value: "Cultura",
    ContentCategory.GASTRONOMIA.value: "Gastronomia",
    ContentCategory.CONSELLS.value: "Consells",
    ContentCategory.ENTREVISTES.value: "Entrevistes",
}

EXAMPLE_FILES: Dict[str, str] = {
    ContentCategory.AGENDA.value: "agenda.json",
    ContentCategory.NOTICIES.value: "noticies.json",
    ContentCategory.ESPORTS.value: "esports.json",
    ContentCategory.TURISME_ACTIU.value: "Turisme-actiu.json",
    ContentCategory.NENS_I_JOVES.value: "nens-i-joves.json",
    ContentCategory.CULTURA.value: "cultura.json",
    ContentCategory.GASTRONOMIA.value: "gastronomia.json",
    ContentCategory.CONSELLS.value: "consells.json",
    ContentCategory.ENTREVISTES.value: "entrevistes.json",
}

MUNICIPALITY_SLOT_MAP: Dict[str, str] = {
    "maresme": "MARESME",
    "cerdanya": "CERDANYA",
    "bergueda": "BERGUEDA",
}

CONSELLS_ALLOWED_TYPES: Dict[str, str] = {
    "bellesa": "Bellesa",
    "eco": "Eco",
    "immobiliaries": "Immobiliàries",
    "mascotes": "Mascotes",
    "motor": "Motor",
    "professionals": "Professionals",
    "salut": "Salut",
}

CONSELLS_KEYWORDS: Dict[str, List[str]] = {
    "Bellesa": ["bellesa", "estetica", "cosmetica", "perruquer", "perruqueria", "maquillatge", "centre estetic", "saló de bellesa"],
    "Eco": ["eco", "ecologic", "ecologia", "recicla", "medi ambient", "residus", "compost"],
    "Immobiliàries": ["immobili", "habitatge", "lloguer", "hipoteca", "promocio immobiliaria", "agent immobiliari"],
    "Mascotes": ["mascota", "mascotes", "gos", "gossos", "gat", "gats", "veterin", "animal de companyia"],
    "Motor": ["motor", "cotxe", "cotxes", "moto", "motos", "vehicle", "vehicles", "conduccio", "taller", "pneumatic"],
    "Salut": ["salut", "metge", "metges", "medic", "medics", "clinica", "farmacia", "nutric", "fisioter"],
}

STRICT_JSON_INSTRUCTION = (
    "La estructura del JSON de esta categoria es estrictamente obligatoria. "
    "Debes respetar exactamente la raiz, el orden de claves, los nombres de campo, los tipos y la forma general del ejemplo JSON configurado para esta categoria. "
    "No anadas claves nuevas, no elimines claves existentes, no reordenes campos y no cambies arrays por objetos ni objetos por arrays. "
    "Solo puedes sustituir los valores para rellenarlos con el contenido extraido."
)

SEO_EDITORIAL_INSTRUCTION = (
    "El contingut editorial ha d'estar optimitzat per SEO sense inventar dades. "
    "Cal generar un title, summary i body_html naturals, clars i orientats a posicionament a partir del contingut original. "
    "També s'han d'omplir correctament els camps SEO principals de Rank Math: focus keyword, SEO title, SEO description, Facebook title/description/image i Twitter title/description/card type. "
    "rank_math_pillar_content ha d'anar sempre buit."
)

AUTHORSHIP_AND_HIGHLIGHT_INSTRUCTION = (
    "Si el text original inclou un apartat Destacat o Destacado, s'ha d'integrar dins del body_html en el punt adequat com un bloc diferenciat, pero sense mostrar literalment la paraula Destacat o Destacado al lector. "
    "Si al final del text apareix Amic o Redacció/Redaccio, no s'ha de deixar com una linia solta dins del cos: s'ha de convertir en una nota final d'autoria coherent amb l'article."
)

IMAGE_FLOW_INSTRUCTION = (
    "Quan hi hagi diverses imatges associades a un article, el contingut ha d'estar estructurat en seccions o blocs naturals per poder intercalar les imatges entre el text. "
    "No pensis l'article com un bloc unic ni com una galeria inicial: les imatges secundaries s'han de repartir dins del cos del contingut."
)


def _load_example_json(category: str) -> str:
    file_name = EXAMPLE_FILES.get(category)
    if not file_name:
        return ""

    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "ejemplos_exportaciones")
    )
    file_path = os.path.join(base_dir, file_name)
    if not os.path.exists(file_path):
        return ""

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        parsed = json.loads(raw)
        return json.dumps(parsed, ensure_ascii=False, indent=2)
    except Exception:
        return ""


def _get_default_category_instructions(category: str) -> str:
    instructions = [STRICT_JSON_INSTRUCTION, SEO_EDITORIAL_INSTRUCTION, AUTHORSHIP_AND_HIGHLIGHT_INSTRUCTION, IMAGE_FLOW_INSTRUCTION]

    if str(category or "").upper().strip() == ContentCategory.CONSELLS.value:
        instructions.append(
            "El campo consell o consell_type solo puede ser uno de estos valores: Bellesa, Eco, Immobiliàries, Mascotes, Motor, Professionals, Salut. "
            "Nomes has d'usar una categoria especifica si el text tracta clarament aquell sector. Si hi ha dubte, si el contingut es generic de serveis, empresa, llar, jardineria, piscines, reformes o recomanacions professionals, fes servir Professionals."
        )

    return "\n\n".join(instructions)


def _merge_category_instructions(default_instructions: str, stored_instructions: str) -> str:
    stored_clean = str(stored_instructions or "").strip()
    if not stored_clean:
        return default_instructions

    if default_instructions in stored_clean:
        return stored_clean

    return f"{default_instructions}\n\n{stored_clean}"


def get_default_category_export_configs() -> List[Dict[str, Any]]:
    return [
        {
            "category": category.value,
            "label": CATEGORY_LABELS.get(category.value, category.value.title()),
            "json_example": _load_example_json(category.value),
            "instructions": _get_default_category_instructions(category.value),
        }
        for category in ContentCategory
        if category != ContentCategory.UNKNOWN
    ]


def get_category_export_configs() -> List[Dict[str, Any]]:
    raw_value = SettingsResolver.get("category_export_configs", "[]")
    try:
        stored = json.loads(raw_value) if isinstance(raw_value, str) else raw_value
    except Exception:
        stored = []

    if not isinstance(stored, list):
        stored = []

    merged: Dict[str, Dict[str, Any]] = {
        item["category"]: deepcopy(item)
        for item in get_default_category_export_configs()
    }

    for item in stored:
        if not isinstance(item, dict):
            continue
        category = str(item.get("category", "")).upper().strip()
        if not category or category not in merged:
            continue
        merged[category]["json_example"] = item.get("json_example", "") or ""
        merged[category]["instructions"] = _merge_category_instructions(
            merged[category].get("instructions", ""),
            item.get("instructions", "") or "",
        )

    return list(merged.values())


def get_category_export_config(category: str) -> Dict[str, Any]:
    normalized = str(category or "").upper().strip()
    for item in get_category_export_configs():
        if item.get("category") == normalized:
            return item
    return {
        "category": normalized,
        "label": CATEGORY_LABELS.get(normalized, normalized.title()),
        "json_example": "",
        "instructions": "",
    }


def parse_json_example(json_example: str) -> Optional[Any]:
    if not json_example or not str(json_example).strip():
        return None
    try:
        return json.loads(json_example)
    except Exception:
        return None


def normalize_strict_payload_municipality_fields(payload: Any, municipality: str) -> Any:
    normalized_municipality = str(municipality or "").upper().strip()

    if isinstance(payload, dict):
        normalized_payload = {}
        for key, value in payload.items():
            expected_municipality = _get_expected_municipality_for_key(str(key).lower())
            if expected_municipality is not None:
                normalized_payload[key] = municipality if normalized_municipality == expected_municipality else ""
            else:
                normalized_payload[key] = normalize_strict_payload_municipality_fields(value, municipality)
        return normalized_payload

    if isinstance(payload, list):
        return [normalize_strict_payload_municipality_fields(item, municipality) for item in payload]

    return payload


def normalize_strict_payload_consells_fields(payload: Any, consells_type: str) -> Any:
    normalized_type = normalize_consells_type(consells_type)

    if isinstance(payload, dict):
        normalized_payload = {}
        for key, value in payload.items():
            if str(key).lower() == "consell":
                normalized_payload[key] = normalized_type
            else:
                normalized_payload[key] = normalize_strict_payload_consells_fields(value, normalized_type)
        return normalized_payload

    if isinstance(payload, list):
        return [normalize_strict_payload_consells_fields(item, normalized_type) for item in payload]

    return payload


def normalize_consells_type(value: Any, default: str = "Professionals") -> str:
    normalized_value = _normalize_token(str(value or ""))
    if not normalized_value:
        return default

    if normalized_value in CONSELLS_ALLOWED_TYPES:
        return CONSELLS_ALLOWED_TYPES[normalized_value]

    for token, canonical in CONSELLS_ALLOWED_TYPES.items():
        if token in normalized_value or normalized_value in token:
            return canonical

    return default


def infer_consells_type_from_text(text: str) -> str:
    normalized_text = _normalize_token(text)
    if not normalized_text:
        return "Professionals"

    best_type = "Professionals"
    best_score = 0

    for consells_type, keywords in CONSELLS_KEYWORDS.items():
        score = sum(1 for keyword in keywords if keyword in normalized_text)
        if score > best_score:
            best_type = consells_type
            best_score = score

    if best_score >= 2:
        return best_type

    return "Professionals"


def resolve_consells_type(raw_value: Any, text: str = "") -> str:
    normalized_value = normalize_consells_type(raw_value, default="")
    inferred_value = infer_consells_type_from_text(text)

    if not normalized_value:
        return inferred_value

    if normalized_value == "Professionals":
        return "Professionals"

    if not str(text or "").strip():
        return normalized_value

    if _consells_type_matches_text(normalized_value, text):
        return normalized_value

    return inferred_value


def build_strict_payload_from_example(example_payload: Any, values: Dict[str, Any]) -> Any:
    if isinstance(example_payload, dict):
        return {
            _resolve_string_value(key, {**values, "__current_key": key, "__resolving_key": True}): build_strict_payload_from_example(value, {**values, "__current_key": key})
            for key, value in example_payload.items()
        }

    if isinstance(example_payload, list):
        return [build_strict_payload_from_example(item, values) for item in example_payload]

    if isinstance(example_payload, str):
        return _resolve_string_value(example_payload, values)

    return example_payload


def _resolve_string_value(example_value: str, values: Dict[str, Any]) -> Any:
    current_key = str(values.get("__current_key", "")).lower()
    resolving_key = bool(values.get("__resolving_key"))
    municipality = str(values.get("municipality", "") or "").upper().strip()
    search_dates = values.get("search_dates", [])
    if isinstance(search_dates, list):
        search_dates_string = ",".join(str(item) for item in search_dates if item)
    else:
        search_dates_string = str(search_dates or "")

    placeholders = {
        "{{ID}}": values.get("id", ""),
        "{{id}}": values.get("id", ""),
        "{{title}}": values.get("title", ""),
        "{{summary}}": values.get("summary", ""),
        "{{body_html}}": values.get("body_html", ""),
        "{{body_text}}": values.get("body_text", ""),
        "{{municipality}}": values.get("municipality", ""),
        "{{category}}": values.get("category", ""),
        "{{subtype}}": values.get("subtype", ""),
        "{{featured_image_path}}": values.get("featured_image_path", ""),
        "{{event_date}}": values.get("event_date", ""),
        "{{start_date}}": values.get("start_date", ""),
        "{{end_date}}": values.get("end_date", ""),
        "{{search_dates}}": values.get("search_dates", []),
        "{{search_dates_string}}": search_dates_string,
        "{{publish_date}}": values.get("publish_date", ""),
        "{{slug}}": values.get("slug", ""),
        "{{consell_type}}": values.get("consell_type", "Professionals"),
        "{{municipi_maresme}}": values.get("municipality", "") if municipality == "MARESME" else "",
        "{{municipi_cerdanya}}": values.get("municipality", "") if municipality == "CERDANYA" else "",
        "{{municipi_bergueda}}": values.get("municipality", "") if municipality == "BERGUEDA" else "",
    }

    stripped = example_value.strip()
    if stripped in placeholders:
        return placeholders[stripped]

    if resolving_key:
        return example_value

    exact_field_values = _get_exact_export_field_values(values)
    if current_key in exact_field_values:
        return exact_field_values[current_key]

    expected_municipality = _get_expected_municipality_for_key(current_key)
    if expected_municipality is not None:
        return values.get("municipality", "") if municipality == expected_municipality else ""

    if current_key in ["municipality", "municipio", "municipi"]:
        return values.get("municipality", "")

    if stripped == "":
        return example_value

    if any(token in current_key for token in ["title", "titulo", "titol"]):
        return values.get("title", "")
    if any(token in current_key for token in ["summary", "excerpt", "resumen", "resum"]):
        return values.get("summary", "")
    if any(token in current_key for token in ["body", "content", "html"]):
        return values.get("body_html", "")
    if any(token in current_key for token in ["text", "texto", "descrip", "descripcion"]):
        return values.get("body_text", "")
    if any(token in current_key for token in ["category", "categoria"]):
        return values.get("category", "")
    if any(token in current_key for token in ["subtype", "subtipus", "subtipo"]):
        return values.get("subtype", "")
    if current_key in ["event_date", "start_date", "end_date"]:
        return values.get("event_date", "")
    if current_key == "search_dates":
        return values.get("search_dates", [])
    if "image" in current_key and "featured" in current_key:
        return values.get("featured_image_path", "")

    return example_value


def _get_expected_municipality_for_key(current_key: str) -> Optional[str]:
    if not any(token in current_key for token in ["municipality", "municipio", "municipi"]):
        return None

    for token, municipality in MUNICIPALITY_SLOT_MAP.items():
        if token in current_key:
            return municipality

    return None


def normalize_strict_payload_exact_fields(payload: Any, values: Dict[str, Any]) -> Any:
    exact_field_values = _get_exact_export_field_values(values)

    if isinstance(payload, dict):
        normalized_payload = {}
        for key, value in payload.items():
            lowered_key = str(key).lower()
            if lowered_key in exact_field_values:
                normalized_payload[key] = exact_field_values[lowered_key]
            else:
                normalized_payload[key] = normalize_strict_payload_exact_fields(value, values)
        return normalized_payload

    if isinstance(payload, list):
        return [normalize_strict_payload_exact_fields(item, values) for item in payload]

    return payload


def _get_exact_export_field_values(values: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "post_title": values.get("title", ""),
        "post_content": values.get("body_html", ""),
        "post_excerpt": values.get("summary", ""),
        "post_date": values.get("publish_date", ""),
        "post_name": values.get("slug", ""),
        "featured_image": values.get("featured_image_path", ""),
        "wp_page_template": values.get("wp_page_template", ""),
        "_wp_page_template": values.get("_wp_page_template", ""),
        "_elementor_template_type": values.get("_elementor_template_type", ""),
        "_elementor_version": values.get("_elementor_version", ""),
        "_elementor_pro_version": values.get("_elementor_pro_version", ""),
        "_elementor_edit_mode": values.get("_elementor_edit_mode", ""),
        "elementor_library_type": values.get("elementor_library_type", ""),
        "_elementor_controls_usage": values.get("_elementor_controls_usage", ""),
        "elementor_library_category": values.get("elementor_library_category", ""),
        "_elementor_css": values.get("_elementor_css", ""),
        "_elementor_conditions": values.get("_elementor_conditions", ""),
        "_elementor_page_assets": values.get("_elementor_page_assets", "a:0:{}"),
        "_elementor_page_settings": values.get("_elementor_page_settings", ""),
        "_elementor_data": values.get("_elementor_data", ""),
        "rank_math_focus_keyword": values.get("rank_math_focus_keyword", values.get("focus_keyword", "")),
        "rank_math_pillar_content": values.get("rank_math_pillar_content", ""),
        "index": values.get("index", ""),
        "nofollow": values.get("nofollow", ""),
        "noimageindex": values.get("noimageindex", ""),
        "noindex": values.get("noindex", ""),
        "noarchive": values.get("noarchive", ""),
        "nosnippet": values.get("nosnippet", ""),
        "rank_math_advanced_robots": values.get("rank_math_advanced_robots", ""),
        "rank_math_canonical_url": values.get("rank_math_canonical_url", ""),
        "redirection_type": values.get("redirection_type", ""),
        "destination_url": values.get("destination_url", ""),
        "headline": values.get("headline", ""),
        "schema_description": values.get("schema_description", ""),
        "article_type": values.get("article_type", ""),
        "rank_math_title": values.get("rank_math_title", ""),
        "_wp_old_slug": values.get("_wp_old_slug", ""),
        "rank_math_description": values.get("rank_math_description", ""),
        "rank_math_facebook_title": values.get("rank_math_facebook_title", ""),
        "rank_math_facebook_description": values.get("rank_math_facebook_description", ""),
        "rank_math_facebook_image": values.get("rank_math_facebook_image", ""),
        "rank_math_facebook_enable_image_overlay": values.get("rank_math_facebook_enable_image_overlay", ""),
        "rank_math_facebook_image_overlay": values.get("rank_math_facebook_image_overlay", ""),
        "rank_math_twitter_use_facebook": values.get("rank_math_twitter_use_facebook", ""),
        "rank_math_twitter_title": values.get("rank_math_twitter_title", ""),
        "rank_math_twitter_description": values.get("rank_math_twitter_description", ""),
        "rank_math_twitter_card_type": values.get("rank_math_twitter_card_type", ""),
        "rank_math_twitter_app_description": values.get("rank_math_twitter_app_description", ""),
        "ds_name": values.get("ds_name", ""),
        "ds_description": values.get("ds_description", ""),
        "ds_url": values.get("ds_url", ""),
        "ds_sameas": values.get("ds_same_as", ""),
        "ds_identifier": values.get("ds_identifier", ""),
        "ds_keywords": values.get("ds_keywords", ""),
        "ds_license": values.get("ds_license", ""),
        "ds_cat_name": values.get("ds_cat_name", ""),
        "ds_temp_coverage": values.get("ds_temp_coverage", ""),
        "ds_spatial_coverage": values.get("ds_spatial_coverage", ""),
        "encodingformat": values.get("encoding_format", ""),
        "contenturl": values.get("content_url", ""),
        "creator_type": values.get("creator_type", ""),
        "creator_name": values.get("creator_name", ""),
        "creator_sameas": values.get("creator_same_as", ""),
        "rank_math_twitter_app_iphone_name": values.get("rank_math_twitter_app_iphone_name", ""),
        "rank_math_twitter_app_iphone_id": values.get("rank_math_twitter_app_iphone_id", ""),
        "rank_math_twitter_app_iphone_url": values.get("rank_math_twitter_app_iphone_url", ""),
        "rank_math_twitter_app_ipad_name": values.get("rank_math_twitter_app_ipad_name", ""),
        "rank_math_twitter_app_ipad_id": values.get("rank_math_twitter_app_ipad_id", ""),
        "rank_math_twitter_app_ipad_url": values.get("rank_math_twitter_app_ipad_url", ""),
        "rank_math_twitter_app_googleplay_name": values.get("rank_math_twitter_app_googleplay_name", ""),
        "rank_math_twitter_app_googleplay_id": values.get("rank_math_twitter_app_googleplay_id", ""),
        "rank_math_twitter_app_googleplay_url": values.get("rank_math_twitter_app_googleplay_url", ""),
        "rank_math_twitter_app_country": values.get("rank_math_twitter_app_country", ""),
        "rank_math_twitter_player_url": values.get("rank_math_twitter_player_url", ""),
        "rank_math_twitter_player_size": values.get("rank_math_twitter_player_size", ""),
        "rank_math_twitter_player_stream": values.get("rank_math_twitter_player_stream", ""),
        "rank_math_twitter_player_stream_ctype": values.get("rank_math_twitter_player_stream_ctype", ""),
        "consell": values.get("consell_type", "Professionals"),
        "article-destacat": values.get("article_destacat", "1"),
        "types_caption": values.get("types_caption", ""),
        "types_alt_text": values.get("types_alt_text", ""),
        "types_description": values.get("types_description", ""),
        "types_file_name": values.get("types_file_name", ""),
        "types_title": values.get("types_title", ""),
    }


def _normalize_token(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower().strip()


def _consells_type_matches_text(consells_type: str, text: str) -> bool:
    normalized_text = _normalize_token(text)
    if not normalized_text:
        return consells_type == "Professionals"

    keywords = CONSELLS_KEYWORDS.get(consells_type, [])
    return sum(1 for keyword in keywords if keyword in normalized_text) >= 2
