from typing import Dict, Any
from app.adapters.base import BaseWordPressAdapter
from app.db.models import CanonicalContent

class CommonWordPressAdapter(BaseWordPressAdapter):
    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        return {}

class NoticiesWordPressAdapter(CommonWordPressAdapter): pass
class EsportsWordPressAdapter(CommonWordPressAdapter): pass
class TurismeActiuWordPressAdapter(CommonWordPressAdapter): pass
class NensIJovesWordPressAdapter(CommonWordPressAdapter): pass
class EntrevistesWordPressAdapter(CommonWordPressAdapter): pass
