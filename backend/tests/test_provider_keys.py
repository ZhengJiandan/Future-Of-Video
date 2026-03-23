from app.core.config import settings
from app.core.provider_keys import get_effective_doubao_api_key
from app.core.request_runtime import reset_request_doubao_api_key, set_request_doubao_api_key
from app.services.doubao_llm import DoubaoLLM


def test_doubao_llm_can_initialize_without_api_key(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOUBAO_API_KEY", None)
    llm = DoubaoLLM()
    assert llm.api_key is None


def test_request_scoped_doubao_api_key_overrides_settings(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DOUBAO_API_KEY", "server-default-key")
    token = set_request_doubao_api_key("request-temporary-key")
    try:
        assert get_effective_doubao_api_key() == "request-temporary-key"
    finally:
        reset_request_doubao_api_key(token)

    assert get_effective_doubao_api_key() == "server-default-key"
