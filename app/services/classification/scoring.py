from typing import List, Dict, Any, Tuple
from app.schemas.classification import (
    MunicipalityClassification, CategoryClassification, SubtypeClassification
)
from app.schemas.all_schemas import ExtractionResult, GroupingResult
from app.core.enums import ReviewReason

class ConfidenceScorer:
    def calculate_overall_confidence(self, 
                                     grouping: GroupingResult, 
                                     extractions: List[ExtractionResult],
                                     mun_class: MunicipalityClassification,
                                     cat_class: CategoryClassification,
                                     sub_class: SubtypeClassification) -> Tuple[float, str]:
        
        # Calculate base extraction confidence
        ext_conf = sum(e.confidence for e in extractions) / len(extractions) if extractions else 0.0
        
        # Calculate base classification confidence
        class_conf = (mun_class.confidence + cat_class.confidence + sub_class.confidence) / 3
        
        # Penalties
        penalties = 0.0
        if mun_class.conflict_detected or cat_class.conflict_detected:
            penalties += 0.2
            
        overall_score = (grouping.confidence * 0.2) + (ext_conf * 0.3) + (class_conf * 0.5) - penalties
        overall_score = max(0.0, min(overall_score, 1.0))
        
        band = self._get_confidence_band(overall_score)
        return overall_score, band

    def _get_confidence_band(self, score: float) -> str:
        if score >= 0.9:
            return "VERY_HIGH"
        elif score >= 0.8:
            return "HIGH"
        elif score >= 0.6:
            return "MEDIUM"
        elif score >= 0.4:
            return "LOW"
        else:
            return "VERY_LOW"

class ReviewDecisionService:
    def decide_review(self, 
                      confidence_band: str, 
                      mun_class: MunicipalityClassification,
                      cat_class: CategoryClassification,
                      sub_class: SubtypeClassification,
                      grouping: GroupingResult,
                      extractions: List[ExtractionResult]) -> Tuple[bool, List[str]]:
        
        reasons = []
        
        if confidence_band in ["LOW", "VERY_LOW"]:
            reasons.append(ReviewReason.LOW_CLASSIFICATION_CONFIDENCE)
            
        if mun_class.conflict_detected or cat_class.conflict_detected:
            reasons.append(ReviewReason.CONFLICTING_SIGNALS)
            
        if grouping.confidence < 0.6:
            reasons.append(ReviewReason.WEAK_GROUPING)
            
        avg_ext_conf = sum(e.confidence for e in extractions) / len(extractions) if extractions else 0.0
        if avg_ext_conf < 0.6:
            reasons.append(ReviewReason.LOW_EXTRACTION_CONFIDENCE)
            
        if not extractions:
            reasons.append(ReviewReason.INSUFFICIENT_TEXT)
            
        requires_review = len(reasons) > 0 or confidence_band in ["MEDIUM", "LOW", "VERY_LOW"]
        return requires_review, [r.value for r in reasons]
