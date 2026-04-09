from typing import Optional
from app.core.enums import Municipality

class MunicipalityRuleset:
    @staticmethod
    def map_standard_municipality(municipality: Municipality) -> Optional[str]:
        mapping = {
            Municipality.MARESME: "Maresme",
            Municipality.CERDANYA: "Cerdanya",
            Municipality.BERGUEDA: "Berguedà",
            Municipality.GENERAL: "General"
        }
        return mapping.get(municipality)
        
    @staticmethod
    def map_consells_municipality(municipality: Municipality) -> str:
        if municipality == Municipality.BERGUEDA:
            return "General,Berguedà"
        elif municipality == Municipality.MARESME:
            return "General,Maresme"
        elif municipality == Municipality.CERDANYA:
            return "General,Cerdanya"
        return "General"
