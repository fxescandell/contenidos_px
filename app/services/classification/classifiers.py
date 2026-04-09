from typing import List, Dict, Any, Optional
from app.core.enums import Municipality, ContentCategory, ContentSubtype
from app.schemas.classification import (
    MunicipalityClassification, CategoryClassification, SubtypeClassification, DetectedSignal
)

class MunicipalityClassifier:
    def classify(self, batch_hints: Dict[str, str], signals: List[DetectedSignal]) -> MunicipalityClassification:
        folder_hint = batch_hints.get("municipality_hint", "").upper()
        detected_mun = next((s for s in signals if s.signal_type == "municipality_keyword_found"), None)
        
        mun = Municipality.UNKNOWN
        confidence = 0.0
        reasoning = []
        conflict = False
        
        # 1. Check folder hint
        if folder_hint in [m.value for m in Municipality]:
            mun = Municipality(folder_hint)
            confidence = 0.8
            reasoning.append(f"Folder indicates {folder_hint}")
            
        # 2. Check text signals
        if detected_mun:
            text_mun_str = detected_mun.value
            if mun == Municipality.UNKNOWN:
                mun = Municipality(text_mun_str)
                confidence = 0.6
                reasoning.append(f"Text keywords indicate {text_mun_str}")
            elif mun.value != text_mun_str:
                conflict = True
                confidence = 0.4
                reasoning.append(f"Conflict: Folder says {mun.value} but text says {text_mun_str}")
                # En caso de conflicto, la confianza baja y requerirá revisión
                
        if mun == Municipality.UNKNOWN:
            mun = Municipality.GENERAL
            reasoning.append("No clear municipality found, fallback to GENERAL")
            confidence = 0.3
            
        return MunicipalityClassification(
            municipality=mun,
            confidence=confidence,
            signals_used=[detected_mun] if detected_mun else [],
            reasoning_summary="; ".join(reasoning),
            conflict_detected=conflict
        )

class CategoryClassifier:
    def classify(self, batch_hints: Dict[str, str], signals: List[DetectedSignal]) -> CategoryClassification:
        folder_hint = batch_hints.get("category_hint", "").upper()
        
        agenda_sig = next((s for s in signals if s.signal_type == "agenda_structure_found"), None)
        recipe_sig = next((s for s in signals if s.signal_type == "recipe_structure_found"), None)
        book_sig = next((s for s in signals if s.signal_type == "book_structure_found"), None)
        
        cat = ContentCategory.UNKNOWN
        confidence = 0.0
        reasoning = []
        conflict = False
        
        if agenda_sig and agenda_sig.weight > 0.5:
            cat = ContentCategory.AGENDA
            confidence = 0.8
            reasoning.append("Strong agenda signals found in text")
        elif recipe_sig and recipe_sig.weight > 0.5:
            cat = ContentCategory.GASTRONOMIA
            confidence = 0.8
            reasoning.append("Strong recipe signals found in text")
        elif book_sig and book_sig.weight > 0.5:
            cat = ContentCategory.CULTURA
            confidence = 0.8
            reasoning.append("Strong book signals found in text")
        elif folder_hint in [c.value for c in ContentCategory]:
            cat = ContentCategory(folder_hint)
            confidence = 0.7
            reasoning.append(f"Fallback to folder hint: {folder_hint}")
        else:
            reasoning.append("No clear category found")
            
        # Check conflicts
        if folder_hint and folder_hint in [c.value for c in ContentCategory] and cat != ContentCategory.UNKNOWN and cat.value != folder_hint:
            conflict = True
            confidence -= 0.3
            reasoning.append(f"Conflict: Folder says {folder_hint} but text suggests {cat.value}")
            
        used_signals = [s for s in [agenda_sig, recipe_sig, book_sig] if s]
        
        return CategoryClassification(
            category=cat,
            confidence=max(confidence, 0.0),
            signals_used=used_signals,
            reasoning_summary="; ".join(reasoning),
            conflict_detected=conflict,
            top_alternatives=[]
        )

class SubtypeClassifier:
    def classify(self, category: ContentCategory, signals: List[DetectedSignal]) -> SubtypeClassification:
        subtype = ContentSubtype.NONE
        confidence = 0.0
        reasoning = []
        
        if category == ContentCategory.CULTURA:
            book_sig = next((s for s in signals if s.signal_type == "book_structure_found"), None)
            if book_sig:
                subtype = ContentSubtype.CULTURA_BOOK
                confidence = 0.9
                reasoning.append("Book structure found for Cultura")
            else:
                subtype = ContentSubtype.CULTURA_GENERAL
                confidence = 0.8
                reasoning.append("Defaulting to Cultura General")
                
        elif category == ContentCategory.GASTRONOMIA:
            recipe_sig = next((s for s in signals if s.signal_type == "recipe_structure_found"), None)
            if recipe_sig:
                subtype = ContentSubtype.GASTRONOMIA_RECIPE
                confidence = 0.9
                reasoning.append("Recipe structure found for Gastronomia")
            else:
                subtype = ContentSubtype.GASTRONOMIA_GENERAL
                confidence = 0.8
                reasoning.append("Defaulting to Gastronomia General")
                
        elif category == ContentCategory.AGENDA:
            subtype = ContentSubtype.AGENDA_GENERAL
            confidence = 0.8
            reasoning.append("Defaulting to Agenda General")
            
        return SubtypeClassification(
            subtype=subtype,
            confidence=confidence,
            signals_used=[],
            reasoning_summary="; ".join(reasoning),
            conflict_detected=False
        )
