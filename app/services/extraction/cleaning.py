import re

class TextCleaningPipeline:
    def __init__(self):
        pass

    def clean(self, raw_text: str) -> dict:
        notes = []
        confidence_adjustment = 0.0
        
        if not raw_text:
            return {"cleaned_text": "", "notes": ["Empty input text"], "adjustment": -0.5}
            
        text = raw_text
        
        # 1. Normalize spaces (replace multiple spaces/tabs with single space)
        text = re.sub(r'[ \t]+', ' ', text)
        
        # 2. Collapse useless line breaks (but preserve paragraphs)
        # We assume paragraphs are separated by 2 or more newlines
        paragraphs = re.split(r'\n{2,}', text)
        cleaned_paragraphs = []
        
        for p in paragraphs:
            # Replace single newlines within a paragraph with a space
            p = re.sub(r'\n', ' ', p)
            # Remove leading/trailing spaces
            p = p.strip()
            
            # Simple hyphenation fix (word broken by newline in OCR)
            p = re.sub(r'(\w+)-\s+(\w+)', r'\1\2', p)
            
            if p:
                cleaned_paragraphs.append(p)
                
        cleaned_text = "\n\n".join(cleaned_paragraphs)
        
        if len(cleaned_paragraphs) < len(paragraphs):
            notes.append("Removed empty paragraphs.")
            
        if cleaned_text != raw_text:
            notes.append("Applied whitespace and line break normalization.")
            confidence_adjustment += 0.05
            
        return {
            "cleaned_text": cleaned_text,
            "notes": notes,
            "adjustment": min(confidence_adjustment, 0.2)
        }
