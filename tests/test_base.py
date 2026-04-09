import pytest
from uuid import uuid4
from app.core.enums import Municipality, ContentCategory, ContentSubtype
from app.rules.municipalities import MunicipalityRuleset
from app.db.models import CanonicalContent, ContentCandidate
from app.services.validation.service import CanonicalValidationService
from app.adapters.agenda import AgendaWordPressAdapter

def test_map_standard_municipality():
    assert MunicipalityRuleset.map_standard_municipality(Municipality.MARESME) == "Maresme"
    assert MunicipalityRuleset.map_standard_municipality(Municipality.CERDANYA) == "Cerdanya"
    assert MunicipalityRuleset.map_standard_municipality(Municipality.UNKNOWN) is None

def test_map_consells_municipality():
    assert MunicipalityRuleset.map_consells_municipality(Municipality.BERGUEDA) == "General,Berguedà"
    assert MunicipalityRuleset.map_consells_municipality(Municipality.UNKNOWN) == "General"

def test_canonical_validation_agenda_missing_date():
    candidate = ContentCandidate(id=uuid4(), candidate_key="test-1")
    content = CanonicalContent(
        candidate=candidate,
        municipality=Municipality.MARESME,
        category=ContentCategory.AGENDA,
        subtype=ContentSubtype.AGENDA_GENERAL,
        final_title="Test Agenda",
        final_body_html="<p>Test</p>",
        structured_fields_json={}  # Missing date
    )
    
    validator = CanonicalValidationService()
    result = validator.validate(content)
    
    assert not result.is_valid
    assert result.requires_review
    assert any(i.code == "AGENDA_MISSING_DATE" for i in result.issues)

def test_agenda_adapter_build_meta_fields():
    candidate = ContentCandidate(id=uuid4(), candidate_key="test-2")
    content = CanonicalContent(
        candidate=candidate,
        municipality=Municipality.MARESME,
        category=ContentCategory.AGENDA,
        subtype=ContentSubtype.AGENDA_GENERAL,
        final_title="Test Agenda 2",
        final_body_html="<p>Test</p>",
        structured_fields_json={
            "event_date": "2026-04-03",
            "search_dates": ["2026-04-03"],
            "article_type": "Esdeveniment"
        }
    )
    
    adapter = AgendaWordPressAdapter()
    meta = adapter.build_meta_fields(content)
    
    assert meta["data-esdeveniment"] == "2026-04-03"
    assert meta["tipus-d-article"] == "Esdeveniment"
    assert meta["dates-que-es-realitza-buscador"] == ["2026-04-03"]
