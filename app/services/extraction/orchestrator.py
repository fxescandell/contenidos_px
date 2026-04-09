import re
from typing import List, Dict, Any
from abc import ABC, abstractmethod

from app.schemas.all_schemas import ExtractionResult
from app.core.enums import ExtractionMethod
from app.services.extraction.cleaning import TextCleaningPipeline

class BaseExtractor(ABC):
    def __init__(self):
        self.cleaner = TextCleaningPipeline()

    @abstractmethod
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        pass

class MockPdfExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        # En una implementación real, usaríamos PyMuPDF o pdfplumber
        raw_text = f"Contenido simulado para {file_path}. Generalitat de Catalunya. Agenda: 12 de Octubre."
        cleaned_info = self.cleaner.clean(raw_text)
        
        return ExtractionResult(
            source_file_id=file_id,
            method=ExtractionMethod.NATIVE_PDF,
            confidence=0.95 + cleaned_info["adjustment"],
            raw_text=raw_text,
            cleaned_text=cleaned_info["cleaned_text"]
        )

class MockDocxExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        raw_text = (
            "Noticia: Ajuntament de Bergueda anuncia noves activitats culturals.\n\n"
            "L'ajuntament de Bergueda ha presentat la programacio d'activitats per a la propera setmana. "
            "Entre els actes destacats hi ha un concert al Teatre Municipal de Berga, una exposicio "
            "d'art contemporani al Casal Cultural, i una jornada esportiva al poliesportiu municipal. "
            "També s'han programat activitats per als mes joves al Centre Civic, amb tallers de cuina "
            "i manualitats. Totes les activitats son gratuïtes i obertes al public general.\n\n"
            "Per mes informacio: ajuntament@bergueda.cat\n"
            "La programacio completa esta disponible a la web municipal."
        )
        cleaned_info = self.cleaner.clean(raw_text)
        
        return ExtractionResult(
            source_file_id=file_id,
            method=ExtractionMethod.DOCX_PARSER,
            confidence=0.98 + cleaned_info["adjustment"],
            raw_text=raw_text,
            cleaned_text=cleaned_info["cleaned_text"]
        )

class MockImageOcrExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        # En una implementación real, usaríamos Tesseract o PaddleOCR
        raw_text = f"CARTEL. FIRA DE LA CERDANYA. Lloc: Puigcerdà. Autor: Joan Petit."
        cleaned_info = self.cleaner.clean(raw_text)
        
        return ExtractionResult(
            source_file_id=file_id,
            method=ExtractionMethod.OCR_IMAGE,
            confidence=0.75 + cleaned_info["adjustment"],
            raw_text=raw_text,
            cleaned_text=cleaned_info["cleaned_text"]
        )

class ExtractionOrchestrator:
    def __init__(self):
        self.pdf_extractor = MockPdfExtractor()
        self.docx_extractor = MockDocxExtractor()
        self.image_extractor = MockImageOcrExtractor()

    def process_files(self, files_info: List[Dict[str, Any]]) -> List[ExtractionResult]:
        results = []
        for file_info in files_info:
            path = file_info["path"].lower()
            file_id = file_info["id"]
            
            if path.endswith(".pdf"):
                results.append(self.pdf_extractor.extract(path, file_id))
            elif path.endswith(".docx"):
                results.append(self.docx_extractor.extract(path, file_id))
            elif path.endswith((".jpg", ".jpeg", ".png")):
                results.append(self.image_extractor.extract(path, file_id))
                
        return results