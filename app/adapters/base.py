from abc import ABC, abstractmethod
from typing import Dict, Any, List

from app.db.models import CanonicalContent
from app.schemas.all_schemas import WordPressExportPayload, AdapterBuildResult, ValidationResult
from app.services.validation.service import CanonicalValidationService
from app.rules.municipalities import MunicipalityRuleset
from app.core.enums import Municipality

class BaseWordPressAdapter(ABC):
    def __init__(self):
        self.validator = CanonicalValidationService()

    def validate(self, canonical_content: CanonicalContent) -> ValidationResult:
        return self.validator.validate(canonical_content)

    def build_payload(self, canonical_content: CanonicalContent) -> AdapterBuildResult:
        validation_result = self.validate(canonical_content)
        raw_payload = None
        if canonical_content.structured_fields_json:
            raw_payload = canonical_content.structured_fields_json.get("_strict_export_payload")
        
        payload = WordPressExportPayload(
            post_title=canonical_content.final_title or "Untitled",
            post_content=self.build_post_content(canonical_content),
            post_excerpt=canonical_content.final_summary,
            post_status=self.get_post_status(canonical_content, validation_result),
            post_date=None,
            featured_image_path=self.map_featured_image(canonical_content),
            taxonomies=self.build_taxonomies(canonical_content),
            meta_input=self.build_meta_fields(canonical_content)
        )
        
        return AdapterBuildResult(
            canonical_id=canonical_content.id,
            adapter_name=self.__class__.__name__,
            payload=payload,
            raw_payload=raw_payload,
            is_ready_for_export=validation_result.is_valid,
            validation_issues=validation_result.issues
        )

    def map_municipality(self, canonical_content: CanonicalContent) -> Dict[str, List[str]]:
        mun = MunicipalityRuleset.map_standard_municipality(canonical_content.municipality)
        if mun:
            # Depending on CPT, the key might be different. 
            # Subclasses can override if needed. Default generic implementation:
            key = f"municipi-{mun.lower().replace('à', 'a')}"
            return {key: [mun]}
        return {}

    def map_featured_image(self, canonical_content: CanonicalContent) -> str | None:
        if canonical_content.structured_fields_json:
            featured = canonical_content.structured_fields_json.get("_featured_image_path")
            if featured:
                return str(featured)
        if canonical_content.candidate and canonical_content.candidate.featured_source_file_id:
            return str(canonical_content.candidate.featured_source_file_id)
        return None

    def build_post_content(self, canonical_content: CanonicalContent) -> str:
        return canonical_content.final_body_html or ""

    @abstractmethod
    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        pass

    def build_taxonomies(self, canonical_content: CanonicalContent) -> Dict[str, List[str]]:
        return self.map_municipality(canonical_content)

    def get_post_status(self, canonical_content: CanonicalContent, validation_result: ValidationResult) -> str:
        if validation_result.requires_review or canonical_content.requires_review:
            return "pending"
        return "publish"

    def get_export_key(self) -> str:
        return self.__class__.__name__.replace("WordPressAdapter", "").lower()
