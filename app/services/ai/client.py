import json
import logging
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


def get_active_llm_client() -> Optional[LlmClient]:
    enabled = SettingsResolver.get("llm_enabled")
    if not enabled:
        return None
    api_key = SettingsResolver.get("llm_api_key")
    if not api_key:
        return None
    return LlmClient()
