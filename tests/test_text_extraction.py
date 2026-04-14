from uuid import uuid4

from app.core.enums import ExtractionMethod
from app.schemas.inbox import InboxConnectionSettings
from app.services.extraction.orchestrator import ExtractionOrchestrator


def test_extraction_orchestrator_extracts_markdown_files(tmp_path):
    markdown_file = tmp_path / "agenda.md"
    markdown_file.write_text("# Titol\n\nPrograma de prova en **markdown**.", encoding="utf-8")

    results = ExtractionOrchestrator().process_files([
        {"id": str(uuid4()), "path": str(markdown_file)},
    ])

    assert len(results) == 1
    assert results[0].method == ExtractionMethod.TEXT_FILE
    assert "Titol" in results[0].cleaned_text
    assert "Programa de prova" in results[0].cleaned_text
    assert "[[H1]] Titol" in results[0].cleaned_text
    assert "#" not in results[0].cleaned_text
    assert "**" not in results[0].cleaned_text


def test_extraction_orchestrator_strips_common_markdown_syntax(tmp_path):
    markdown_file = tmp_path / "programa.markdown"
    markdown_file.write_text(
        "## Programa\n\n**Concert** a [Berga](https://example.com)\n\n- Entrada gratuïta\n- Inscripció prèvia\n",
        encoding="utf-8",
    )

    results = ExtractionOrchestrator().process_files([
        {"id": str(uuid4()), "path": str(markdown_file)},
    ])

    cleaned = results[0].cleaned_text
    assert "Programa" in cleaned
    assert "Concert a Berga" in cleaned
    assert "Entrada gratuïta" in cleaned
    assert "Inscripció prèvia" in cleaned
    assert "[Berga]" not in cleaned
    assert "https://example.com" not in cleaned
    assert "**Concert**" not in cleaned
    assert "[[LI]] Entrada gratuïta" in cleaned
    assert "[[LI]] Inscripció prèvia" in cleaned


def test_inbox_connection_settings_allow_markdown_by_default():
    settings = InboxConnectionSettings(mode="local")

    assert ".md" in settings.extensions_allowlist
    assert ".markdown" in settings.extensions_allowlist
