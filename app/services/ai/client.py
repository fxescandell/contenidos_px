import json
import logging
import mimetypes
from urllib.parse import urlparse
from typing import Optional, List, Dict, Any

from app.services.settings.service import SettingsResolver

logger = logging.getLogger(__name__)


class LlmClient:
    def __init__(self, provider: str = None, api_key: str = None, model: str = None,
                 base_url: str = None, temperature: float = None):
        self.provider = provider or SettingsResolver.get("llm_provider") or "openai"
        self.api_key = api_key or SettingsResolver.get("llm_api_key") or ""
        self.model = model or SettingsResolver.get("llm_model") or "gpt-4o-mini"
        self.base_url = base_url or ""
        self.temperature = temperature or float(SettingsResolver.get("llm_temperature", "0.3") or 0.3)

    def chat(self, prompt: str, system: str = None, images: Optional[List[Dict]] = None,
           max_tokens: int = 4000) -> str:
        if not self.api_key:
            raise ValueError("API key del LLM no configurada. Configurala en la seccion AI de configuracion.")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})

        content = [{"type": "text", "text": prompt}]
        if images:
            content.extend(images)
        messages.append({"role": "user", "content": content})

        try:
            response = self._call_api(messages, max_tokens)
            return response.strip()
        except Exception as e:
            logger.error(f"Error LLM ({self.provider}): {e}")
            raise

    def _call_api(self, messages: List[Dict], max_tokens: int) -> str:
        if "openai" in self.provider.lower() or "anthropic" in self.provider.lower() or "groq" in self.provider.lower():
            return self._call_openai_compatible(messages, max_tokens)
        if "gemini" in self.provider.lower():
            return self._call_gemini(messages, max_tokens)

        raise ValueError(f"Proveedor LLM no soportado: {self.provider}")

    def _call_openai_compatible(self, messages: List[Dict], max_tokens: int) -> str:
        import httpx

        base_url = self.base_url
        if self.provider.lower() == "anthropic":
            base_url = base_url or "https://api.anthropic.com/v1"
            url = f"{base_url.rstrip('/')}/messages"
            headers = {"x-api-key": self.api_key, "content-type": "application/json", "anthropic-version": "2023-06-01"}
            payload = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        elif self.provider.lower() == "groq":
            base_url = base_url or "https://api.groq.com/openai/v1"
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
            payload = {"model": self.model, "max_tokens": max_tokens, "messages": messages}
        else:
            base_url = base_url or "https://api.openai.com/v1"
            url = f"{base_url.rstrip('/')}/chat/completions"
            headers = {"Authorization": f"Bearer {self.api_key}", "content-type": "application/json"}
            payload = {"model": self.model, "max_tokens": max_tokens, "messages": messages,
                     "temperature": self.temperature}

        resp = httpx.post(url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        if self.provider.lower() == "anthropic":
            return data.get("content", [{}])[0].get("text", "")

        choices = data.get("choices", [])
        if choices:
            return choices[0].get("message", {}).get("content", "")
        return ""

    def _call_gemini(self, messages: List[Dict], max_tokens: int) -> str:
        import httpx

        model = self.model or "gemini-2.0-flash"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
        payload = {
            "contents": self._gemini_contents_from_messages(messages),
            "generationConfig": {
                "temperature": self.temperature,
                "maxOutputTokens": max_tokens,
            },
        }

        system_instruction = self._extract_system_message(messages)
        if system_instruction:
            payload["systemInstruction"] = {
                "parts": [{"text": system_instruction}]
            }

        resp = httpx.post(url, json=payload, headers={"content-type": "application/json"}, timeout=60)
        resp.raise_for_status()
        data = resp.json()

        candidates = data.get("candidates", [])
        if not candidates:
            return ""

        parts = candidates[0].get("content", {}).get("parts", [])
        texts = [part.get("text", "") for part in parts if part.get("text")]
        return "\n".join(texts).strip()

    def _gemini_contents_from_messages(self, messages: List[Dict]) -> List[Dict[str, Any]]:
        contents = []
        for message in messages:
            if message.get("role") == "system":
                continue

            role = "model" if message.get("role") == "assistant" else "user"
            content = message.get("content", "")
            parts = []

            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        parts.append({"text": item.get("text", "")})
                    elif item.get("type") == "image_url":
                        inline_part = self._gemini_inline_image_part(item.get("image_url", {}).get("url", ""))
                        if inline_part:
                            parts.append(inline_part)
            elif isinstance(content, str):
                parts.append({"text": content})

            if parts:
                contents.append({"role": role, "parts": parts})

        return contents or [{"role": "user", "parts": [{"text": ""}]}]

    def _extract_system_message(self, messages: List[Dict]) -> str:
        for message in messages:
            if message.get("role") == "system":
                return str(message.get("content", "") or "")
        return ""

    def _gemini_inline_image_part(self, url: str) -> Optional[Dict[str, Any]]:
        if not url:
            return None

        if url.startswith("data:"):
            header, _, data = url.partition(",")
            mime_type = header.split(";")[0].replace("data:", "") or "image/jpeg"
            return {"inline_data": {"mime_type": mime_type, "data": data}}

        parsed = urlparse(url)
        mime_type, _ = mimetypes.guess_type(parsed.path)
        return {"file_data": {"mime_type": mime_type or "image/jpeg", "file_uri": url}}


def get_active_llm_client() -> Optional[LlmClient]:
    enabled = SettingsResolver.get("llm_enabled")
    if not enabled:
        return None
    api_key = SettingsResolver.get("llm_api_key")
    if not api_key:
        return None
    return LlmClient()
