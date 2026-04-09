from typing import Dict, Type
from app.adapters.base import BaseWordPressAdapter
from app.adapters.agenda import AgendaWordPressAdapter
from app.adapters.cultura import CulturaWordPressAdapter
from app.adapters.gastronomia import GastronomiaWordPressAdapter
from app.adapters.consells import ConsellsWordPressAdapter
from app.adapters.common import (
    NoticiesWordPressAdapter, EsportsWordPressAdapter, 
    TurismeActiuWordPressAdapter, NensIJovesWordPressAdapter, 
    EntrevistesWordPressAdapter
)
from app.core.enums import ContentCategory

class AdapterFactory:
    @staticmethod
    def get_adapter(category: ContentCategory) -> BaseWordPressAdapter:
        mapping: Dict[ContentCategory, Type[BaseWordPressAdapter]] = {
            ContentCategory.AGENDA: AgendaWordPressAdapter,
            ContentCategory.CULTURA: CulturaWordPressAdapter,
            ContentCategory.GASTRONOMIA: GastronomiaWordPressAdapter,
            ContentCategory.CONSELLS: ConsellsWordPressAdapter,
            ContentCategory.NOTICIES: NoticiesWordPressAdapter,
            ContentCategory.ESPORTS: EsportsWordPressAdapter,
            ContentCategory.TURISME_ACTIU: TurismeActiuWordPressAdapter,
            ContentCategory.NENS_I_JOVES: NensIJovesWordPressAdapter,
            ContentCategory.ENTREVISTES: EntrevistesWordPressAdapter
        }
        
        adapter_class = mapping.get(category, NoticiesWordPressAdapter)
        return adapter_class()