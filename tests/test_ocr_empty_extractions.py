from uuid import uuid4

from app.core.enums import ExtractionMethod
from app.schemas.all_schemas import ExtractionResult
from app.services.classification.scoring import get_average_extraction_confidence
from app.services.extraction.orchestrator import ImageOcrExtractor


def test_mock_ocr_extract_returns_empty_cleaned_text(tmp_path):
    image_path = tmp_path / "foto.jpg"
    image_path.write_bytes(b"fake")

    extractor = ImageOcrExtractor()
    result = extractor._mock_extract(str(image_path), str(uuid4()))

    assert result.method == ExtractionMethod.OCR_IMAGE
    assert result.cleaned_text == ""
    assert "OCR deshabilitado" in result.raw_text


def test_average_extraction_confidence_ignores_empty_ocr_results():
    doc_extraction = ExtractionResult(
        source_file_id=uuid4(),
        method=ExtractionMethod.DOCX_PARSER,
        confidence=0.98,
        raw_text="Texto documento",
        cleaned_text="Texto documento",
    )
    empty_image_extraction = ExtractionResult(
        source_file_id=uuid4(),
        method=ExtractionMethod.OCR_IMAGE,
        confidence=0.0,
        raw_text="[OCR deshabilitado para foto.jpg. Texto no extraido.]",
        cleaned_text="",
    )

    avg_conf = get_average_extraction_confidence([doc_extraction, empty_image_extraction])

    assert avg_conf == 0.98
