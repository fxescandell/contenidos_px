import pytest
from uuid import uuid4

from app.core.enums import Municipality, ContentCategory, ContentSubtype, CandidateGroupingStrategy
from app.schemas.all_schemas import ExtractionResult, GroupingResult
from app.services.extraction.cleaning import TextCleaningPipeline
from app.services.classification.signals.detectors import (
    AgendaPatternDetector, RecipePatternDetector, MunicipalityKeywordDetector
)
from app.services.classification.orchestrator import ClassificationOrchestrator

def test_text_cleaning_pipeline():
    cleaner = TextCleaningPipeline()
    raw = "Este   es un\ntexto\n\ncon   párrafos\n\nrotos y un gu-\nión."
    result = cleaner.clean(raw)
    
    assert "Este es un texto" in result["cleaned_text"]
    assert "con párrafos" in result["cleaned_text"]
    assert "guión" in result["cleaned_text"]

def test_agenda_pattern_detector():
    detector = AgendaPatternDetector()
    text = "Gran Festa. Data: 12 d'Octubre. Lloc: Plaça Major. Hora: 18:30."
    signal = detector.detect(text)
    
    assert signal is not None
    assert signal.signal_type == "agenda_structure_found"
    assert signal.weight > 0.5
    
def test_municipality_keyword_detector():
    detector = MunicipalityKeywordDetector()
    text = "Notícies des de Puigcerdà, a la comarca de la Cerdanya."
    signal = detector.detect(text)
    
    assert signal is not None
    assert signal.value == "CERDANYA"

def test_classification_orchestrator():
    orchestrator = ClassificationOrchestrator()
    
    grouping = GroupingResult(
        candidate_key="test_batch_folder1",
        strategy=CandidateGroupingStrategy.DIRECTORY_BASED,
        confidence=0.9,
        assigned_files=[]
    )
    
    extractions = [
        ExtractionResult(
            source_file_id=uuid4(),
            method="DOCX_PARSER",
            confidence=0.95,
            raw_text="Recepta de l'àvia.\nIngredients: 2 ous.\nElaboració: Batre fort.",
            cleaned_text="Recepta de l'àvia. Ingredients: 2 ous. Elaboració: Batre fort."
        )
    ]
    
    batch_hints = {
        "municipality_hint": "MARESME",
        "category_hint": "GASTRONOMIA"
    }
    
    result = orchestrator.classify_candidate(grouping, extractions, batch_hints)
    
    assert result.municipality == Municipality.MARESME
    assert result.category == ContentCategory.GASTRONOMIA
    assert result.subtype == ContentSubtype.GASTRONOMIA_RECIPE
    assert not result.requires_review
    assert result.confidence_band in ["HIGH", "VERY_HIGH"]

def test_classification_orchestrator_conflict():
    orchestrator = ClassificationOrchestrator()
    
    grouping = GroupingResult(
        candidate_key="test_batch_folder2",
        strategy=CandidateGroupingStrategy.DIRECTORY_BASED,
        confidence=0.9,
        assigned_files=[]
    )
    
    extractions = [
        ExtractionResult(
            source_file_id=uuid4(),
            method="DOCX_PARSER",
            confidence=0.95,
            raw_text="Notícies des de Puigcerdà, a la Cerdanya.",
            cleaned_text="Notícies des de Puigcerdà, a la Cerdanya."
        )
    ]
    
    batch_hints = {
        "municipality_hint": "MARESME", # Folder says Maresme, but text says Cerdanya
        "category_hint": "NOTICIES"
    }
    
    result = orchestrator.classify_candidate(grouping, extractions, batch_hints)
    
    # Text usually wins but flags conflict
    assert result.requires_review
    assert "CONFLICTING_SIGNALS" in result.review_reasons
