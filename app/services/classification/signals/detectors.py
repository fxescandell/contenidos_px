from abc import ABC, abstractmethod
import re
from typing import List, Optional

from app.schemas.classification import DetectedSignal

class BaseSignalDetector(ABC):
    @abstractmethod
    def detect(self, text: str) -> Optional[DetectedSignal]:
        pass

class RecipePatternDetector(BaseSignalDetector):
    def detect(self, text: str) -> Optional[DetectedSignal]:
        lower_text = text.lower()
        evidence = []
        weight = 0.0
        
        if re.search(r'\bingredients?\b|\bingredientes?\b', lower_text):
            evidence.append("Found 'ingredients' keyword")
            weight += 0.4
            
        if re.search(r'\belaboraci[óo]n?\b|\bpreparaci[óo]n?\b', lower_text):
            evidence.append("Found 'elaboració/preparació' keyword")
            weight += 0.4
            
        if weight > 0:
            return DetectedSignal(
                signal_type="recipe_structure_found",
                value=True,
                weight=min(weight, 1.0),
                evidence=evidence
            )
        return None

class AgendaPatternDetector(BaseSignalDetector):
    def detect(self, text: str) -> Optional[DetectedSignal]:
        lower_text = text.lower()
        evidence = []
        weight = 0.0
        
        if re.search(r'\b(data|fecha):\s*\d{1,2}', lower_text):
            evidence.append("Found date pattern")
            weight += 0.3
            
        if re.search(r'\b(hora|horari):\s*\d{1,2}[:.]\d{2}', lower_text):
            evidence.append("Found time pattern")
            weight += 0.3
            
        if re.search(r'\b(lloc|lugar):\s*\w+', lower_text):
            evidence.append("Found location pattern")
            weight += 0.3
            
        if weight > 0:
            return DetectedSignal(
                signal_type="agenda_structure_found",
                value=True,
                weight=min(weight, 1.0),
                evidence=evidence
            )
        return None

class BookPatternDetector(BaseSignalDetector):
    def detect(self, text: str) -> Optional[DetectedSignal]:
        lower_text = text.lower()
        evidence = []
        weight = 0.0
        
        if re.search(r'\b(autor|autora|escritor):\s*\w+', lower_text):
            evidence.append("Found author pattern")
            weight += 0.4
            
        if re.search(r'\b(editorial|publicat per):\s*\w+', lower_text):
            evidence.append("Found publisher pattern")
            weight += 0.4
            
        if re.search(r'\b(t[ií]tol|llibre):\s*\w+', lower_text):
            evidence.append("Found book title pattern")
            weight += 0.3
            
        if weight > 0:
            return DetectedSignal(
                signal_type="book_structure_found",
                value=True,
                weight=min(weight, 1.0),
                evidence=evidence
            )
        return None

class MunicipalityKeywordDetector(BaseSignalDetector):
    def detect(self, text: str) -> Optional[DetectedSignal]:
        lower_text = text.lower()
        evidence = []
        weight = 0.0
        detected_mun = None
        
        if "cerdanya" in lower_text or "puigcerdà" in lower_text:
            evidence.append("Cerdanya keywords found")
            detected_mun = "CERDANYA"
            weight += 0.5
            
        if "maresme" in lower_text or "mataró" in lower_text:
            evidence.append("Maresme keywords found")
            detected_mun = "MARESME"
            weight += 0.5
            
        if "berguedà" in lower_text or "bergueda" in lower_text or "berga" in lower_text:
            evidence.append("Berguedà keywords found")
            detected_mun = "BERGUEDA"
            weight += 0.5
            
        if detected_mun:
            return DetectedSignal(
                signal_type="municipality_keyword_found",
                value=detected_mun,
                weight=min(weight, 1.0),
                evidence=evidence
            )
        return None

class FeatureExtractionOrchestrator:
    def __init__(self):
        self.detectors: List[BaseSignalDetector] = [
            RecipePatternDetector(),
            AgendaPatternDetector(),
            BookPatternDetector(),
            MunicipalityKeywordDetector()
        ]
        
    def detect_all(self, text: str) -> List[DetectedSignal]:
        signals = []
        for detector in self.detectors:
            signal = detector.detect(text)
            if signal:
                signals.append(signal)
        return signals
