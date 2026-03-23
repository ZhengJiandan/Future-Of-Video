from __future__ import annotations

from pathlib import Path

import pytest

from app.core.config import settings
from app.services.doubao_image_generation import DoubaoImageGenerationClient
from app.services.pipeline_character_library import PipelineCharacterLibraryService
from app.services.pipeline_workflow import PipelineWorkflowService
from app.services.preferred_image_generation import PreferredImageGenerationClient


class _DummyNanoBanana:
    def __init__(self, *, api_key: str | None = "nano-key", payload: bytes = b"nano-image") -> None:
        self.api_key = api_key
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def generate_text_to_image(self, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("text", prompt))
        return {"success": True, "image_data": self.payload}

    def generate_image_to_image(self, input_image_path: str, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("image", prompt))
        return {"success": True, "image_data": self.payload}

    def generate_multi_image_mix(self, input_image_paths, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("multi", prompt))
        return {"success": True, "image_data": self.payload}


class _DummyDoubao:
    def __init__(self, *, configured: bool = True, payload: bytes = b"doubao-image") -> None:
        self.configured = configured
        self.payload = payload
        self.calls: list[tuple[str, str]] = []

    def generate_text_to_image(self, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("text", prompt))
        return {"success": True, "image_data": self.payload}

    def generate_image_to_image(self, input_image_path: str, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("image", prompt))
        return {"success": True, "image_data": self.payload}

    def generate_multi_image_mix(self, input_image_paths, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("multi", prompt))
        return {"success": True, "image_data": self.payload}


class _DummyImageGenerator:
    def __init__(self, *, payload: bytes = b"doubao-frame", source: str = "doubao-seedream-text-to-image") -> None:
        self.payload = payload
        self.source = source
        self.calls: list[tuple[str, str]] = []

    def generate_text_to_image(self, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("text", prompt))
        return {"success": True, "image_data": self.payload, "source": self.source}

    def generate_image_to_image(self, input_image_path: str, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("image", prompt))
        return {"success": True, "image_data": self.payload, "source": self.source}

    def generate_multi_image_mix(self, input_image_paths, prompt: str, aspect_ratio: str = "16:9", image_size: str = "2k"):
        self.calls.append(("multi", prompt))
        return {"success": True, "image_data": self.payload, "source": self.source}


def test_preferred_image_generation_prefers_nanobanana_when_configured() -> None:
    nanobanana = _DummyNanoBanana(api_key="nano-key")
    doubao = _DummyDoubao(configured=True)
    client = PreferredImageGenerationClient(nanobanana=nanobanana, doubao=doubao)

    result = client.generate_text_to_image("三只猫在窗边")

    assert result["success"] is True
    assert result["source"] == "nanobanana-text-to-image"
    assert result["provider"] == "nanobanana"
    assert nanobanana.calls == [("text", "三只猫在窗边")]
    assert doubao.calls == []


def test_preferred_image_generation_falls_back_to_doubao_without_nanobanana_key() -> None:
    nanobanana = _DummyNanoBanana(api_key=None)
    doubao = _DummyDoubao(configured=True)
    client = PreferredImageGenerationClient(nanobanana=nanobanana, doubao=doubao)

    result = client.generate_text_to_image("三只猫在窗边")

    assert result["success"] is True
    assert result["source"] == "doubao-seedream-text-to-image"
    assert result["provider"] == "doubao"
    assert nanobanana.calls == []
    assert doubao.calls == [("text", "三只猫在窗边")]


def test_workflow_keyframe_generation_uses_provider_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = PipelineWorkflowService()
    service.image_generator = _DummyImageGenerator(source="doubao-seedream-text-to-image")

    task_dir = tmp_path / "task"
    task_dir.mkdir(parents=True, exist_ok=True)
    asset = service._generate_keyframe_with_preferred_provider(
        task_dir=task_dir,
        segment={"segment_number": 1, "title": "片段 1", "duration": 5.0},
        frame_kind="start",
        prompt="三只猫一起看向镜头",
        reference_images=[],
        base_asset=None,
    )

    assert asset is not None
    assert asset.source == "doubao-seedream-text-to-image"
    assert (task_dir / "segment_01_start.png").read_bytes() == b"doubao-frame"


@pytest.mark.asyncio
async def test_character_library_uses_fallback_image_provider_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(settings, "UPLOAD_DIR", str(tmp_path))
    service = PipelineCharacterLibraryService()
    service.image_generator = _DummyImageGenerator(source="doubao-seedream-text-to-image")

    result = await service.generate_character_image_asset(
        name="三花猫队长",
        description="一只英气的三花猫",
    )

    assert result["source"] == "doubao-seedream-text-to-image"
    generated_path = tmp_path / "generated" / "pipeline" / "character_library" / "prototypes" / result["asset_filename"]
    assert generated_path.read_bytes() == b"doubao-frame"


def test_doubao_image_client_falls_back_to_ark_when_las_returns_unauthorized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "DOUBAO_API_KEY", "ark-temp-key")
    monkeypatch.setattr(settings, "DOUBAO_IMAGE_BASE_URL", "https://operator.las.cn-beijing.volces.com/api/v1")
    monkeypatch.setattr(settings, "DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3")

    calls: list[tuple[str, str]] = []

    class _Response:
        def __init__(self, status_code: int, payload: dict | None = None, text: str = "") -> None:
            self.status_code = status_code
            self._payload = payload or {}
            self.text = text

        def json(self):
            return self._payload

    def fake_post(url: str, headers=None, json=None, timeout=None):
        calls.append((url, str((json or {}).get("model") or "")))
        if url.startswith("https://operator.las.cn-beijing.volces.com"):
            return _Response(401, text='{"error":"Unauthorized"}')
        return _Response(
            200,
            payload={
                "data": [
                    {
                        "b64_json": "aGVsbG8=",
                    }
                ]
            },
        )

    monkeypatch.setattr("app.services.doubao_image_generation.requests.post", fake_post)

    client = DoubaoImageGenerationClient()
    result = client.generate_text_to_image("一只太空猫", aspect_ratio="16:9", image_size="2k")

    assert result["success"] is True
    assert result["image_data"] == b"hello"
    assert calls[0][0] == "https://operator.las.cn-beijing.volces.com/api/v1/online/images/generations"
    assert calls[-1][0] == "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    assert calls[-1][1] == "doubao-seedream-4-0-250828"
