from app.services.ai.client import LlmClient
from app.api.routes.settings import _format_llm_test_error


class _DummyResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)

    def json(self):
        return self._payload


class _DummyHttpError(Exception):
    def __init__(self, response):
        self.response = response
        super().__init__(response.text)


def test_gemini_contents_from_messages_supports_text_and_data_url_images():
    client = LlmClient(provider="gemini", api_key="x", model="gemini-2.0-flash")

    contents = client._gemini_contents_from_messages([
        {"role": "system", "content": "Sistema"},
        {"role": "user", "content": [
            {"type": "text", "text": "Extrae el texto"},
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
        ]},
    ])

    assert len(contents) == 1
    assert contents[0]["role"] == "user"
    assert contents[0]["parts"][0] == {"text": "Extrae el texto"}
    assert contents[0]["parts"][1] == {
        "inline_data": {"mime_type": "image/png", "data": "ZmFrZQ=="}
    }


def test_format_llm_test_error_for_gemini_429_is_actionable():
    error = _DummyHttpError(_DummyResponse(429, {
        "error": {
            "message": "Quota exceeded for quota metric.",
            "status": "RESOURCE_EXHAUSTED",
        }
    }))

    message = _format_llm_test_error("gemini", "gemini-3-pro-preview", error)

    assert "HTTP 429" in message
    assert "gemini-2.0-flash" in message
    assert "Quota exceeded" in message


def test_format_llm_test_error_for_gemini_404_mentions_model_unavailable():
    error = _DummyHttpError(_DummyResponse(404, {
        "error": {
            "message": "Model not found",
            "status": "NOT_FOUND",
        }
    }))

    message = _format_llm_test_error("gemini", "gemini-foo", error)

    assert "no encuentra el modelo 'gemini-foo'" in message
    assert "Model not found" in message
