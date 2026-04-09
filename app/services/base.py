from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

from app.db.models import SourceBatch, SourceFile, ContentCandidate, CanonicalContent
from app.schemas.all_schemas import (
    GroupingResult, ExtractionResult, ClassificationDecision,
    ImageProcessingResult, EditorialBuildResult, ValidationResult
)

class BaseGroupingService(ABC):
    @abstractmethod
    def group_files(self, batch: SourceBatch, files: List[SourceFile]) -> List[GroupingResult]:
        pass

class BaseExtractionService(ABC):
    @abstractmethod
    def extract_candidate(self, candidate: ContentCandidate, assigned_files: List[SourceFile]) -> List[ExtractionResult]:
        pass

class BaseClassificationService(ABC):
    @abstractmethod
    def classify(self, candidate: ContentCandidate, extracted_docs: List[ExtractionResult], batch_hints: Dict[str, str]) -> ClassificationDecision:
        pass

class BaseImageProcessingService(ABC):
    @abstractmethod
    def process_images(self, candidate: ContentCandidate, image_files: List[SourceFile]) -> List[ImageProcessingResult]:
        pass

class BaseEditorialBuilder(ABC):
    @abstractmethod
    def build_editorial_content(self, classification: ClassificationDecision, extracted_text: str, images: List[ImageProcessingResult], metadata: Dict[str, Any]) -> EditorialBuildResult:
        pass

class BaseValidationService(ABC):
    @abstractmethod
    def validate(self, canonical_content: CanonicalContent) -> ValidationResult:
        pass

class BaseNotifier(ABC):
    @abstractmethod
    def send_notification(self, message: str, level: str = "INFO", context: Optional[Dict[str, Any]] = None) -> None:
        pass
