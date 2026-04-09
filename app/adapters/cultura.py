from typing import Dict, Any
from app.adapters.base import BaseWordPressAdapter
from app.db.models import CanonicalContent
from app.core.enums import ContentSubtype

class CulturaWordPressAdapter(BaseWordPressAdapter):
    def build_meta_fields(self, canonical_content: CanonicalContent) -> Dict[str, Any]:
        meta = {}
        if canonical_content.subtype == ContentSubtype.CULTURA_BOOK:
            meta["tipus-d-article"] = "Llibre secció Cultura"
            book_data = canonical_content.structured_fields_json.get("book", {})
            meta.update({
                "titol-del-llibre": book_data.get("book_title", ""),
                "autor-a-del-llibre": book_data.get("book_author", ""),
                "any-edicio": book_data.get("edition_year", ""),
                "editorial": book_data.get("publisher", ""),
                "patrocinat-per": book_data.get("sponsor_name", ""),
                "pagina-del-patrocinador": book_data.get("sponsor_page", ""),
                "disposem-de-pdf-de-lectura-previa": book_data.get("sample_pdf_available", False),
                "pdf-llegir-un-fragment": book_data.get("sample_pdf_path", "")
            })
        else:
            meta["tipus-d-article"] = "Cultura general"
            
        return meta
