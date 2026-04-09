from typing import List, Dict, Any

from app.schemas.all_schemas import ExtractionResult, GroupingResult
from app.schemas.classification import FinalClassificationResult

from app.services.classification.signals.detectors import FeatureExtractionOrchestrator
from app.services.classification.classifiers import MunicipalityClassifier, CategoryClassifier, SubtypeClassifier
from app.services.classification.scoring import ConfidenceScorer, ReviewDecisionService

class ClassificationOrchestrator:
    def __init__(self):
        self.feature_orchestrator = FeatureExtractionOrchestrator()
        self.municipality_classifier = MunicipalityClassifier()
        self.category_classifier = CategoryClassifier()
        self.subtype_classifier = SubtypeClassifier()
        self.scorer = ConfidenceScorer()
        self.review_service = ReviewDecisionService()

    def classify_candidate(self, 
                           grouping: GroupingResult, 
                           extractions: List[ExtractionResult], 
                           batch_hints: Dict[str, str]) -> FinalClassificationResult:
        
        # 1. Combine all cleaned text
        combined_text = "\n\n".join(e.cleaned_text for e in extractions)
        
        # 2. Extract signals
        signals = self.feature_orchestrator.detect_all(combined_text)
        
        # 3. Classify components
        mun_class = self.municipality_classifier.classify(batch_hints, signals)
        cat_class = self.category_classifier.classify(batch_hints, signals)
        sub_class = self.subtype_classifier.classify(cat_class.category, signals)
        
        # 4. Calculate Confidence
        overall_score, band = self.scorer.calculate_overall_confidence(
            grouping=grouping,
            extractions=extractions,
            mun_class=mun_class,
            cat_class=cat_class,
            sub_class=sub_class
        )
        
        # 5. Decide if review is required
        requires_review, reasons = self.review_service.decide_review(
            confidence_band=band,
            mun_class=mun_class,
            cat_class=cat_class,
            sub_class=sub_class,
            grouping=grouping,
            extractions=extractions
        )
        
        avg_ext_conf = sum(e.confidence for e in extractions) / len(extractions) if extractions else 0.0
        class_conf = (mun_class.confidence + cat_class.confidence + sub_class.confidence) / 3
        
        reasoning = [
            f"Municipality: {mun_class.reasoning_summary}",
            f"Category: {cat_class.reasoning_summary}",
            f"Subtype: {sub_class.reasoning_summary}"
        ]
        
        return FinalClassificationResult(
            municipality=mun_class.municipality,
            category=cat_class.category,
            subtype=sub_class.subtype,
            
            grouping_confidence=grouping.confidence,
            extraction_confidence=avg_ext_conf,
            classification_confidence=class_conf,
            
            confidence_band=band,
            requires_review=requires_review,
            review_reasons=reasons,
            
            signals=signals,
            reasoning_summary=" | ".join(reasoning),
            
            llm_used=False,
            llm_summary=None
        )
