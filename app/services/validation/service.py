from typing import List
from app.db.models import CanonicalContent
from app.schemas.all_schemas import ValidationResult, ValidationIssue
from app.core.enums import ValidationSeverity, ContentCategory, Municipality, ContentSubtype
from app.services.base import BaseValidationService

class CanonicalValidationService(BaseValidationService):
    def validate(self, content: CanonicalContent) -> ValidationResult:
        issues: List[ValidationIssue] = []
        blocking_errors = 0
        requires_review = False
        
        # 1. Base canonical validations
        if not content.final_title:
            issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="MISSING_TITLE", message="final_title cannot be empty"))
            blocking_errors += 1
            
        if not content.final_body_html:
            issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="MISSING_BODY", message="final_body_html cannot be empty"))
            blocking_errors += 1
            
        if content.category == ContentCategory.UNKNOWN:
            issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="UNKNOWN_CATEGORY", message="Category cannot be UNKNOWN"))
            blocking_errors += 1
            
        if content.municipality == Municipality.UNKNOWN:
            issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="UNKNOWN_MUNICIPALITY", message="Municipality cannot be UNKNOWN"))
            blocking_errors += 1
            
        if not content.candidate.featured_source_file_id and not content.candidate.candidate_key.endswith("no-image"):
            # The prompt says "featured_image obligatoria"
            issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="MISSING_FEATURED_IMAGE", message="Featured image is mandatory"))
            blocking_errors += 1
            
        # 2. CPT Specific validations
        if content.category == ContentCategory.AGENDA:
            sf = content.structured_fields_json
            if not sf.get("event_date") and not sf.get("start_date"):
                issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="AGENDA_MISSING_DATE", message="Agenda must have an event_date or start_date"))
                blocking_errors += 1
            if not sf.get("search_dates"):
                issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="AGENDA_MISSING_SEARCH_DATES", message="Agenda must have search_dates"))
                blocking_errors += 1
                
        elif content.category == ContentCategory.CULTURA and content.subtype == ContentSubtype.CULTURA_BOOK:
            sf = content.structured_fields_json.get("book", {})
            if not sf.get("book_title"):
                issues.append(ValidationIssue(severity=ValidationSeverity.WARNING, code="BOOK_MISSING_TITLE", message="Book title is highly recommended"))
                
        elif content.category == ContentCategory.GASTRONOMIA and content.subtype == ContentSubtype.GASTRONOMIA_RECIPE:
            sf = content.structured_fields_json
            if sf.get("gastronomy_type") != "recipe":
                issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="RECIPE_TYPE_MISMATCH", message="Gastronomy type must be 'recipe'"))
                blocking_errors += 1
                
        elif content.category == ContentCategory.CONSELLS:
            sf = content.structured_fields_json
            if not sf.get("consell_type"):
                issues.append(ValidationIssue(severity=ValidationSeverity.ERROR, code="CONSELLS_MISSING_TYPE", message="Consells must have a consell_type"))
                blocking_errors += 1

        is_valid = blocking_errors == 0
        requires_review = not is_valid or any(i.severity in [ValidationSeverity.WARNING, ValidationSeverity.ERROR] for i in issues)
        
        return ValidationResult(
            is_valid=is_valid,
            requires_review=requires_review,
            blocking_errors_count=blocking_errors,
            issues=issues
        )
