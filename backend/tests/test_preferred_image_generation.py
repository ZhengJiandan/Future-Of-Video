from __future__ import annotations

import pytest

from app.core.provider_keys import MissingProviderConfigError
from app.services.preferred_image_generation import PreferredImageGenerationClient


class _DummyNanoBanana:
    def __init__(self, *, api_key: str | None = None) -> None:
        self.api_key = api_key


class _DummyDoubao:
    def __init__(self, *, configured: bool = False) -> None:
        self.configured = configured


def test_preferred_image_generation_raises_missing_provider_config_when_no_provider_available() -> None:
    client = PreferredImageGenerationClient(
        nanobanana=_DummyNanoBanana(api_key=None),
        doubao=_DummyDoubao(configured=False),
    )

    with pytest.raises(MissingProviderConfigError) as exc_info:
        client.generate_text_to_image("一只太空猫")

    assert exc_info.value.code == "missing_doubao_api_key"
    assert "DOUBAO_API_KEY" in str(exc_info.value)
