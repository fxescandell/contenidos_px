import json
import os
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


def get_default_category_export_configs() -> List[Dict[str, Any]]:
    return [
        {
            "category": category.value,
            "label": CATEGORY_LABELS.get(category.value, category.value.title()),
            "json_example": _load_example_json(category.value),
            "instructions": "",
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
        merged[category]["instructions"] = item.get("instructions", "") or ""

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
        "{{municipi_maresme}}": values.get("municipality", "") if municipality == "MARESME" else "",
        "{{municipi_cerdanya}}": values.get("municipality", "") if municipality == "CERDANYA" else "",
        "{{municipi_bergueda}}": values.get("municipality", "") if municipality == "BERGUEDA" else "",
    }

    stripped = example_value.strip()
    if stripped in placeholders:
        return placeholders[stripped]

    if resolving_key:
        return example_value

    if any(token in current_key for token in ["title", "titulo", "titol"]):
        return values.get("title", "")
    if any(token in current_key for token in ["summary", "excerpt", "resumen", "resum"]):
        return values.get("summary", "")
    if any(token in current_key for token in ["body", "content", "html"]):
        return values.get("body_html", "")
    if any(token in current_key for token in ["text", "texto", "descrip", "descripcion"]):
        return values.get("body_text", "")
    if any(token in current_key for token in ["municipality", "municipio", "municipi"]):
        return values.get("municipality", "")
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
