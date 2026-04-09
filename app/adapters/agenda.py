from typing import Dict, Any, List
from app.adapters.base import BaseWordPressAdapter
from app.db.models import CanonicalContent

class AgendaWordPressAdapter(BaseWordPressAdapter):
    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        sf = canonical_content.structured_fields_json
        meta = {
            "tipus-d-article": sf.get("article_type", "General"),
            "categoria-d-agenda": sf.get("agenda_category", ""),
            "data-esdeveniment": sf.get("event_date", ""),
            "data-inici": sf.get("start_date", ""),
            "data-final": sf.get("end_date", ""),
            "dates-que-es-realitza-buscador": sf.get("search_dates", []),
        }
        
        activities = sf.get("activities", [])
        if activities:
            meta["activitats"] = activities
            
        return meta
