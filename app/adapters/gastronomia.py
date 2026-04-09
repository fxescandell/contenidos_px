from typing import Dict, Any
from app.adapters.base import BaseWordPressAdapter
from app.db.models import CanonicalContent
from app.core.enums import ContentSubtype

class GastronomiaWordPressAdapter(BaseWordPressAdapter):
    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        meta = {}
        if canonical_content.subtype == ContentSubtype.GASTRONOMIA_RECIPE:
            meta["tipus-article-gastronomia"] = "Recepta"
        else:
            meta["tipus-article-gastronomia"] = "Géneric"
            
        return meta
