import json
import logging
import re
from typing import Any, Dict


logger = logging.getLogger(__name__)


class FinalReviewService:
    def review_content(
        self,
        municipality: str,
        category: str,
        subtype: str,
        original_text: str,
        vision_context_text: str,
        draft_title: str,
        draft_summary: str,
        draft_body_html: str,
    ) -> Dict[str, Any]:
        try:
            from app.services.ai.client import get_active_llm_client

            client = get_active_llm_client()
            if not client:
                return self._fallback(draft_title, draft_summary, draft_body_html)
        except Exception:
            return self._fallback(draft_title, draft_summary, draft_body_html)

        system = (
            "Ets un revisor editorial final per a publicacions locals en catala. "
            "La redaccio final ha de ser obligatoriament en catala. "
            "Has de revisar un article ja estructurat per comprovar fidelitat al text original, SEO, ortografia, gramatica i coherencia editorial. "
            "No pots inventar dades ni reduir informacio rellevant del text base. "
            "Has de mantenir i preservar figures, blocs destacats, activitats, llistats i estructures HTML importants quan ja existeixin. "
            "Si el body_html esta massa pla, has de millorar la jerarquia visual amb h2, h3, <strong> i <em> quan sigui pertinent, sense fer-lo artificial."
        )
        prompt = (
            f"Municipi: {municipality}\n"
            f"Categoria: {category}\n"
            f"Subtipus: {subtype}\n\n"
            "Text original de referencia:\n"
            f"{original_text[:12000]}\n\n"
            "Text complementari extret d'imatges o cartells (nomes com a suport, mai com a bloc afegit independent):\n"
            f"{vision_context_text[:3000]}\n\n"
            "Esborrany actual:\n"
            f"title: {draft_title}\n"
            f"summary: {draft_summary}\n"
            f"body_html:\n{draft_body_html[:14000]}\n\n"
            "Tasques obligatories:\n"
            "1. Verifica que no s'ha perdut informacio rellevant del text original.\n"
            "2. Millora SEO, ortografia i gramatica si cal.\n"
            "3. Mantingues la redaccio 100% en catala.\n"
            "4. No eliminis figures ni estructures HTML utiles ja presents.\n"
            "5. No resumeixis reduint contingut important.\n"
            "6. Si corregeixes res, integra-ho de manera natural dins del text.\n\n"
            "Respon nomes amb JSON valid: {\"title\": \"...\", \"summary\": \"...\", \"body_html\": \"...\", \"notes\": [\"...\"]}"
        )

        try:
            response = client.chat(prompt, system=system, max_tokens=4000)
            parsed = json.loads(self._extract_json_object(response or "{}"))
            if not isinstance(parsed, dict):
                return self._fallback(draft_title, draft_summary, draft_body_html)
            return {
                "title": str(parsed.get("title") or draft_title),
                "summary": str(parsed.get("summary") or draft_summary),
                "body_html": str(parsed.get("body_html") or draft_body_html),
                "notes": parsed.get("notes") if isinstance(parsed.get("notes"), list) else [],
            }
        except Exception as e:
            logger.warning("Revision final no disponible: %s", e)
            return self._fallback(draft_title, draft_summary, draft_body_html)

    def _extract_json_object(self, text: str) -> str:
        cleaned = (text or "").strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            return cleaned[start:end + 1]
        return cleaned or "{}"

    def _fallback(self, title: str, summary: str, body_html: str) -> Dict[str, Any]:
        return {
            "title": title,
            "summary": summary,
            "body_html": body_html,
            "notes": [],
        }


final_review_service = FinalReviewService()
