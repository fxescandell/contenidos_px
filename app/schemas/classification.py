from typing import Any, Dict, List, Optional
from uuid import UUID
from pydantic import BaseModel, Field

from app.core.enums import Municipality, ContentCategory, ContentSubtype

class DetectedSignal(BaseModel):
    signal_type: str
    value: Any
    weight: float
    evidence: List[str] = Field(default_factory=list)
    source: str = "cleaned_text"

class ClassificationBaseResult(BaseModel):
    confidence: float
    signals_used: List[DetectedSignal] = Field(default_factory=list)
    reasoning_summary: str
    conflict_detected: bool = False

class MunicipalityClassification(ClassificationBaseResult):
    municipality: Municipality

class CategoryClassification(ClassificationBaseResult):
    category: ContentCategory
    top_alternatives: List[Dict[str, Any]] = Field(default_factory=list)

class SubtypeClassification(ClassificationBaseResult):
    subtype: ContentSubtype

class FinalClassificationResult(BaseModel):
    municipality: Municipality
    category: ContentCategory
    subtype: ContentSubtype
    
    grouping_confidence: float
    extraction_confidence: float
    classification_confidence: float
    
    confidence_band: str
    requires_review: bool
    review_reasons: List[str] = Field(default_factory=list)
    
    signals: List[DetectedSignal] = Field(default_factory=list)
    reasoning_summary: str
    
    llm_used: bool = False
    llm_summary: Optional[str] = None
