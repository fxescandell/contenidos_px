import re
import os
import logging
from typing import List, Dict, Any, Optional
from abc import ABC, abstractmethod
from uuid import UUID

from app.schemas.all_schemas import ExtractionResult
from app.core.enums import ExtractionMethod
from app.services.extraction.cleaning import TextCleaningPipeline
from app.services.settings.service import SettingsResolver

OCR_ENGINE = None
logger = logging.getLogger(__name__)


class BaseExtractor(ABC):
    def __init__(self):
        self.cleaner = TextCleaningPipeline()

    @abstractmethod
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        pass

    def _uuid(self, file_id: str) -> UUID:
        if isinstance(file_id, UUID):
            return file_id
        return UUID(file_id)


class RealPdfExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        try:
            import pymupdf
            doc = pymupdf.open(file_path)
            pages_text = []
            for page in doc:
                text = page.get_text("text")
                if text.strip():
                    pages_text.append(text)
            doc.close()
            raw_text = "\n\n".join(pages_text) if pages_text else "[PDF sin texto extraible]"
        except Exception as e:
            raw_text = f"[Error extrayendo PDF: {e}]"

        cleaned_info = self.cleaner.clean(raw_text)

        return ExtractionResult(
            source_file_id=self._uuid(file_id),
            method=ExtractionMethod.NATIVE_PDF,
            confidence=0.95 + cleaned_info["adjustment"],
            raw_text=raw_text,
            cleaned_text=cleaned_info["cleaned_text"]
        )


class RealDocxExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        try:
            import docx
            doc = docx.Document(file_path)
            paragraphs = []
            for para in doc.paragraphs:
                text = para.text.strip()
                if text:
                    paragraphs.append(text)

            tables_text = []
            for table in doc.tables:
                for row in table.rows:
                    cells = [cell.text.strip() for cell in row.cells]
                    tables_text.append(" | ".join(cells))

            raw_text = "\n\n".join(paragraphs)
            if tables_text:
                raw_text += "\n\n[ TABLAS ]\n" + "\n".join(tables_text)
            if not raw_text.strip():
                raw_text = "[DOCX sin contenido de texto]"
        except Exception as e:
            raw_text = f"[Error extrayendo DOCX: {e}]"

        cleaned_info = self.cleaner.clean(raw_text)

        return ExtractionResult(
            source_file_id=self._uuid(file_id),
            method=ExtractionMethod.DOCX_PARSER,
            confidence=0.98 + cleaned_info["adjustment"],
            raw_text=raw_text,
            cleaned_text=cleaned_info["cleaned_text"]
        )


class ImageOcrExtractor(BaseExtractor):
    def extract(self, file_path: str, file_id: str) -> ExtractionResult:
        global OCR_ENGINE
        engine = SettingsResolver.get("ocr_engine", "disabled")
        if not engine or engine == "disabled":
            return self._mock_extract(file_path, file_id)

        if engine == "ai_vision":
            return self._ai_vision_extract(file_path, file_id)
        elif engine == "tesseract":
            return self._tesseract_extract(file_path, file_id)
        elif engine == "paddleocr":
            return self._paddleocr_extract(file_path, file_id)
        else:
            return self._mock_extract(file_path, file_id)

    def _ai_vision_extract(self, file_path: str, file_id: str) -> ExtractionResult:
        try:
            import base64
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client(use_ocr_vision=True)
            if not client:
                return self._mock_extract(file_path, file_id)

            with open(file_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")

            prompt = "Extrae todo el texto visible de esta imagen. Responde SOLO con el texto, sin explicaciones."
            response = client.chat(prompt, images=[{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}])

            raw_text = response if response else "[Sin respuesta del modelo]"
            if not str(raw_text).strip() or str(raw_text).strip() == "[Sin respuesta del modelo]":
                return self._empty_ocr_result(file_path, file_id, "Sin respuesta del modelo")
            cleaned_info = self.cleaner.clean(raw_text)

            return ExtractionResult(
                source_file_id=self._uuid(file_id),
                method=ExtractionMethod.OCR_IMAGE,
                confidence=0.85 + cleaned_info["adjustment"],
                raw_text=raw_text,
                cleaned_text=cleaned_info["cleaned_text"]
            )
        except ModuleNotFoundError as e:
            logger.warning("Dependencia OCR/vision no disponible: %s", e)
            return self._mock_extract(file_path, file_id)
        except Exception as e:
            return self._mock_extract_with_error(file_path, file_id, str(e))

    def _tesseract_extract(self, file_path: str, file_id: str) -> ExtractionResult:
        try:
            import pytesseract
            from PIL import Image as PILImage

            img = PILImage.open(file_path)
            text = pytesseract.image_to_string(img, lang='spa+cat')
            if not text.strip():
                return self._empty_ocr_result(file_path, file_id, "Imagen sin texto reconocible")

            cleaned_info = self.cleaner.clean(text)

            return ExtractionResult(
                source_file_id=self._uuid(file_id),
                method=ExtractionMethod.OCR_IMAGE,
                confidence=0.75 + cleaned_info["adjustment"],
                raw_text=text,
                cleaned_text=cleaned_info["cleaned_text"]
            )
        except ModuleNotFoundError as e:
            logger.warning("Tesseract no disponible: %s", e)
            return self._mock_extract(file_path, file_id)
        except Exception as e:
            return self._mock_extract_with_error(file_path, file_id, str(e))

    def _paddleocr_extract(self, file_path: str, file_id: str) -> ExtractionResult:
        try:
            from paddleocr import PaddleOCR
            ocr = PaddleOCR(use_angle_cls=True, lang='es')
            result = ocr.ocr(file_path, cls=True)
            lines = []
            if result and result[0]:
                for line in result[0]:
                    if line and len(line) >= 2:
                        lines.append(line[1][0])
            if not lines:
                return self._empty_ocr_result(file_path, file_id, "Imagen sin texto reconocible")
            text = "\n".join(lines)
            cleaned_info = self.cleaner.clean(text)
            return ExtractionResult(
                source_file_id=self._uuid(file_id),
                method=ExtractionMethod.OCR_IMAGE,
                confidence=0.75 + cleaned_info["adjustment"],
                raw_text=text,
                cleaned_text=cleaned_info["cleaned_text"]
            )
        except ModuleNotFoundError as e:
            logger.warning("PaddleOCR no disponible: %s", e)
            return self._mock_extract(file_path, file_id)
        except Exception as e:
            return self._mock_extract_with_error(file_path, file_id, str(e))

    def _mock_extract(self, file_path: str, file_id: str) -> ExtractionResult:
        fname = os.path.basename(file_path)
        raw_text = f"[OCR deshabilitado para {fname}. Texto no extraido.]"
        return ExtractionResult(
            source_file_id=self._uuid(file_id),
            method=ExtractionMethod.OCR_IMAGE,
            confidence=0.0,
            raw_text=raw_text,
            cleaned_text=""
        )

    def _mock_extract_with_error(self, file_path: str, file_id: str, error: str) -> ExtractionResult:
        raw_text = f"[Error OCR en {os.path.basename(file_path)}: {error}]"
        return ExtractionResult(
            source_file_id=self._uuid(file_id),
            method=ExtractionMethod.OCR_IMAGE,
            confidence=0.0,
            raw_text=raw_text,
            cleaned_text=""
        )

    def _empty_ocr_result(self, file_path: str, file_id: str, reason: str) -> ExtractionResult:
        raw_text = f"[{reason} en {os.path.basename(file_path)}]"
        return ExtractionResult(
            source_file_id=self._uuid(file_id),
            method=ExtractionMethod.OCR_IMAGE,
            confidence=0.0,
            raw_text=raw_text,
            cleaned_text=""
        )


class ExtractionOrchestrator:
    def __init__(self):
        self.pdf_extractor = RealPdfExtractor()
        self.docx_extractor = RealDocxExtractor()
        self.image_extractor = ImageOcrExtractor()

    def process_files(self, files_info: List[Dict[str, Any]]) -> List[ExtractionResult]:
        results = []
        for file_info in files_info:
            path = file_info["path"].lower()
            file_id = file_info["id"]

            if path.endswith(".pdf"):
                results.append(self.pdf_extractor.extract(path, file_id))
            elif path.endswith(".docx"):
                results.append(self.docx_extractor.extract(path, file_id))
            elif path.endswith((".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp")):
                results.append(self.image_extractor.extract(path, file_id))

        return results
