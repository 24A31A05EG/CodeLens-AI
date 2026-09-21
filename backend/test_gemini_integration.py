import services.ai_client as ai_client


class FakeInteraction:
    output_text = "AI explanation from Google Gemini"


class FakeInteractions:
    def create(self, **kwargs):
        assert kwargs["model"] == ai_client.GEMINI_MODEL
        assert "Explain this file" in kwargs["input"]
        return FakeInteraction()


class FakeClient:
    def __init__(self, api_key):
        assert api_key == "key"
        self.interactions = FakeInteractions()


class FakeGenAI:
    Client = FakeClient


def test_gemini_disabled_keeps_fallback(monkeypatch):
    monkeypatch.setattr(ai_client, "ENABLE_GEMINI", False)
    monkeypatch.setattr(ai_client, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(ai_client, "genai", FakeGenAI())
    assert ai_client._call_model("hello") is None


def test_gemini_calls_model_when_enabled(monkeypatch):
    monkeypatch.setattr(ai_client, "ENABLE_GEMINI", True)
    monkeypatch.setattr(ai_client, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(ai_client, "genai", FakeGenAI())

    result = ai_client._call_model("Explain this file")

    assert result == "AI explanation from Google Gemini"


def test_gemini_failure_returns_none_for_static_fallback(monkeypatch):
    class BrokenInteractions:
        def create(self, **kwargs):
            raise RuntimeError("provider unavailable")

    class BrokenClient:
        def __init__(self, api_key):
            self.interactions = BrokenInteractions()

    class BrokenGenAI:
        Client = BrokenClient

    monkeypatch.setattr(ai_client, "ENABLE_GEMINI", True)
    monkeypatch.setattr(ai_client, "GEMINI_API_KEY", "key")
    monkeypatch.setattr(ai_client, "genai", BrokenGenAI())

    assert ai_client._call_model("Explain this file") is None
