from typing import Dict, Any, List
from app.adapters.base import BaseWordPressAdapter
from app.db.models import CanonicalContent
from app.rules.municipalities import MunicipalityRuleset

class ConsellsWordPressAdapter(BaseWordPressAdapter):
    def map_municipality(self, canonical_content: CanonicalContent) -> Dict[str, List[str]]:
        # Consells uses a different mapping strategy
        mapped = MunicipalityRuleset.map_consells_municipality(canonical_content.municipality)
        return {"municipi-consells": [mapped]}

    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        sf = canonical_content.structured_fields_json
        return {
            "consell": sf.get("consell_type", "Professionals")
        }
