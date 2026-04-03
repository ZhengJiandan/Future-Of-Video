import httpx
import pytest

from app.core.config import settings
from app.services.kling_video import (
    DEFAULT_KLING_BASE_URL,
    VIDEO_TASK_OMNI_GENERATION,
    KlingAPIClient,
    KlingVideoGenerationResponse,
)
from app.services.pipeline_workflow import PipelineWorkflowService


@pytest.mark.asyncio
async def test_kling_omni_video_uses_beijing_base_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient()
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "task-1", "task_status": "submitted"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        response = await client.create_omni_video_task(prompt="a cat running")
    finally:
        await client.close()

    assert response.task_id == "task-1"
    assert calls == [
        (
            "POST",
            f"{DEFAULT_KLING_BASE_URL}/v1/videos/omni-video",
            {
                "model_name": "kling-v3-omni",
                "mode": "std",
                "multi_shot": False,
                "sound": "off",
                "prompt": "a cat running",
                "duration": "5",
                "aspect_ratio": "16:9",
            },
        )
    ]


@pytest.mark.asyncio
async def test_kling_delete_custom_voice_falls_back_to_singular_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient()
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        if json == {"voice_ids": ["voice-1"]}:
            return httpx.Response(404, request=httpx.Request(method, url))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"deleted": True, "voice_id": "voice-1"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        payload = await client.delete_custom_voice("voice-1")
    finally:
        await client.close()

    assert payload["deleted"] is True
    assert calls == [
        ("POST", f"{DEFAULT_KLING_BASE_URL}/v1/general/delete-voices", {"voice_ids": ["voice-1"]}),
        ("POST", f"{DEFAULT_KLING_BASE_URL}/v1/general/delete-voices", {"voice_id": "voice-1"}),
    ]


@pytest.mark.asyncio
async def test_pipeline_kling_render_prefers_omni_with_anchor_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_kling_enabled", lambda: True)
    monkeypatch.setattr("app.services.pipeline_workflow.require_kling_credentials", lambda **kwargs: ("ak-test", "sk-test"))
    monkeypatch.setattr(service, "_build_kling_image_input", lambda **kwargs: "https://example.com/start.png")
    monkeypatch.setattr(service, "_build_segment_video_prompt", lambda **kwargs: "prompt")
    monkeypatch.setattr(service, "_build_segment_negative_prompt", lambda **kwargs: "")
    monkeypatch.setattr(service, "_normalize_kling_duration", lambda value: 5)
    monkeypatch.setattr(service, "_normalize_kling_aspect_ratio", lambda value: "16:9")

    calls: list[str] = []

    class FakeGenerator:
        def __init__(self, **kwargs) -> None:
            assert kwargs["base_url"] == settings.KLING_BASE_URL

        async def create_omni_video_task(self, **kwargs):
            calls.append("omni")
            assert kwargs["image"] == "https://example.com/start.png"
            return KlingVideoGenerationResponse(task_id="task-2", status="submitted")

        async def wait_for_completion(self, task_id: str, *, task_type: str, poll_interval: int, max_wait_time: int):
            calls.append(task_type)
            return KlingVideoGenerationResponse(
                task_id=task_id,
                status="completed",
                video_url="https://example.com/video.mp4",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.kling_video.KlingVideoGenerator", FakeGenerator)

    result = await service._try_render_kling_video(
        task_dir=service.output_root,
        segment={"segment_number": 1, "duration": 5.0, "title": "片段 1"},
        keyframe_bundle={"start_frame": {"asset_url": "https://example.com/start.png"}},
        character_profiles=[],
        scene_profiles=[],
        render_config={"aspect_ratio": "16:9"},
    )

    assert result == {
        "asset_url": "https://example.com/video.mp4",
        "asset_type": "video/mp4",
        "asset_filename": "clip_01.mp4",
        "provider": "kling-official-omni_generation",
        "last_frame_url": "",
    }
    assert calls == ["omni", VIDEO_TASK_OMNI_GENERATION]


@pytest.mark.asyncio
async def test_pipeline_kling_render_uses_omni_without_anchor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_kling_enabled", lambda: True)
    monkeypatch.setattr("app.services.pipeline_workflow.require_kling_credentials", lambda **kwargs: ("ak-test", "sk-test"))
    monkeypatch.setattr(service, "_build_kling_image_input", lambda **kwargs: None)
    monkeypatch.setattr(service, "_build_segment_video_prompt", lambda **kwargs: "prompt")
    monkeypatch.setattr(service, "_build_segment_negative_prompt", lambda **kwargs: "")
    monkeypatch.setattr(service, "_normalize_kling_duration", lambda value: 5)
    monkeypatch.setattr(service, "_normalize_kling_aspect_ratio", lambda value: "16:9")

    calls: list[str] = []

    class FakeGenerator:
        def __init__(self, **kwargs) -> None:
            return None

        async def create_omni_video_task(self, **kwargs):
            calls.append("omni")
            assert kwargs["image"] == ""
            return KlingVideoGenerationResponse(task_id="task-2", status="submitted")

        async def wait_for_completion(self, task_id: str, *, task_type: str, poll_interval: int, max_wait_time: int):
            calls.append(task_type)
            return KlingVideoGenerationResponse(
                task_id=task_id,
                status="completed",
                video_url="https://example.com/video.mp4",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.kling_video.KlingVideoGenerator", FakeGenerator)

    result = await service._try_render_kling_video(
        task_dir=service.output_root,
        segment={"segment_number": 2, "duration": 5.0, "title": "片段 2"},
        keyframe_bundle=None,
        character_profiles=[],
        scene_profiles=[],
        render_config={"aspect_ratio": "16:9"},
    )

    assert result["provider"] == "kling-official-omni_generation"
    assert calls == ["omni", VIDEO_TASK_OMNI_GENERATION]


@pytest.mark.asyncio
async def test_render_video_or_preview_does_not_fallback_to_doubao_when_kling_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_choose_render_provider", lambda render_config: "kling-official")

    async def fake_kling(**kwargs):
        raise RuntimeError("kling failed")

    async def fake_doubao(**kwargs):
        raise AssertionError("should not fallback to doubao")

    monkeypatch.setattr(service, "_try_render_kling_video", fake_kling)
    monkeypatch.setattr(service, "_try_render_doubao_video", fake_doubao)

    with pytest.raises(RuntimeError) as exc_info:
        await service._render_video_or_preview(
            task_dir=service.output_root,
            segment={"segment_number": 1, "duration": 5.0, "title": "片段 1"},
            keyframe_bundle=None,
            character_profiles=[],
            scene_profiles=[],
            render_config={"provider": "auto"},
        )

    assert "kling failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kling_omni_video_uses_structured_multi_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient()
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "task-1", "task_status": "submitted"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        await client.create_omni_video_task(
            prompt="full prompt should be omitted",
            extra_body={
                "shot_type": "customize",
                "multi_prompt": ["shot 1 prompt", "shot 2 prompt"],
            },
        )
    finally:
        await client.close()

    payload = calls[0][2]
    assert payload["model_name"] == "kling-v3-omni"
    assert payload["multi_shot"] is True
    assert payload["shot_type"] == "customize"
    assert "prompt" not in payload
    assert payload["multi_prompt"] == [
        {"index": 1, "prompt": "shot 1 prompt", "duration": "3"},
        {"index": 2, "prompt": "shot 2 prompt", "duration": "2"},
    ]


@pytest.mark.asyncio
async def test_kling_omni_video_http_error_includes_response_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient()

    async def fake_request(method: str, url: str, json=None, params=None):
        return httpx.Response(
            400,
            json={"code": 40017, "message": "invalid image payload"},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        with pytest.raises(httpx.HTTPStatusError) as exc_info:
            await client.create_omni_video_task(image="bad-image", prompt="prompt")
    finally:
        await client.close()

    assert "invalid image payload" in str(exc_info.value)


@pytest.mark.asyncio
async def test_kling_omni_video_uses_image_list_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient()
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "task-1", "task_status": "submitted"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        await client.create_omni_video_task(image="base64-image", prompt="prompt")
    finally:
        await client.close()

    assert calls == [
        (
            "POST",
            f"{DEFAULT_KLING_BASE_URL}/v1/videos/omni-video",
            {
                "model_name": "kling-v3-omni",
                "mode": "std",
                "multi_shot": False,
                "sound": "off",
                "prompt": "prompt",
                "duration": "5",
                "aspect_ratio": "16:9",
                "image_list": [
                    {
                        "image_url": "base64-image",
                        "type": "first_frame",
                    }
                ],
            },
        )
    ]


@pytest.mark.asyncio
async def test_pipeline_kling_image_render_raises_without_fallback_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = PipelineWorkflowService()
    monkeypatch.setattr(service, "_kling_enabled", lambda: True)
    monkeypatch.setattr("app.services.pipeline_workflow.require_kling_credentials", lambda **kwargs: ("ak-test", "sk-test"))
    monkeypatch.setattr(service, "_build_kling_image_input", lambda **kwargs: "https://example.com/start.png")
    monkeypatch.setattr(service, "_build_segment_video_prompt", lambda **kwargs: "prompt")
    monkeypatch.setattr(service, "_build_segment_negative_prompt", lambda **kwargs: "")
    monkeypatch.setattr(service, "_normalize_kling_duration", lambda value: 5)
    monkeypatch.setattr(service, "_normalize_kling_aspect_ratio", lambda value: "16:9")
    monkeypatch.setattr(service, "_resolve_kling_model", lambda value: "kling-v3-omni")
    monkeypatch.setattr(
        service,
        "_resolve_kling_multi_shot_config",
        lambda **kwargs: {
            "enabled": True,
            "shot_type": "customize",
            "multi_prompt": ["shot 1 prompt", "shot 2 prompt"],
        },
    )
    monkeypatch.setattr(service, "_build_kling_subject_elements", lambda **kwargs: [])
    monkeypatch.setattr(service, "_build_kling_subject_element_list", lambda subjects: [])

    calls: list[dict] = []

    class FakeGenerator:
        def __init__(self, **kwargs) -> None:
            return None

        async def create_omni_video_task(self, **kwargs):
            calls.append({"type": "omni", "extra_body": dict(kwargs.get("extra_body") or {})})
            raise httpx.HTTPStatusError(
                "400 Client Error",
                request=httpx.Request("POST", "https://api-beijing.klingai.com/v1/videos/omni-video"),
                response=httpx.Response(
                    400,
                    json={"message": "invalid omni payload"},
                    request=httpx.Request("POST", "https://api-beijing.klingai.com/v1/videos/omni-video"),
                ),
            )

        async def wait_for_completion(self, task_id: str, *, task_type: str, poll_interval: int, max_wait_time: int):
            return KlingVideoGenerationResponse(
                task_id=task_id,
                status="completed",
                video_url="https://example.com/video.mp4",
            )

        async def close(self) -> None:
            return None

    monkeypatch.setattr("app.services.kling_video.KlingVideoGenerator", FakeGenerator)

    with pytest.raises(RuntimeError) as exc_info:
        await service._try_render_kling_video(
            task_dir=service.output_root,
            segment={"segment_number": 1, "duration": 5.0, "title": "片段 1"},
            keyframe_bundle={"start_frame": {"asset_url": "https://example.com/start.png"}},
            character_profiles=[],
            scene_profiles=[],
            render_config={"aspect_ratio": "16:9"},
        )

    assert "invalid omni payload" in str(exc_info.value)
    assert calls == [
        {
            "type": "omni",
            "extra_body": {
                "multi_shot": True,
                "shot_type": "customize",
                "multi_prompt": ["shot 1 prompt", "shot 2 prompt"],
                "generate_audio": True,
            },
        }
    ]


@pytest.mark.asyncio
async def test_kling_create_omni_video_task_supports_official_payload_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient(model="kling-video-o1")
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "task-omni", "task_status": "submitted"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        await client.create_omni_video_task(
            prompt="ignored when customize",
            duration=10,
            aspect_ratio="16:9",
            extra_body={
                "multi_shot": True,
                "shot_type": "customize",
                "multi_prompt": [
                    {"index": 1, "prompt": "shot 1", "duration": "5"},
                    {"index": 2, "prompt": "shot 2", "duration": "5"},
                ],
                "image_list": [{"image_url": "https://example.com/ref.png"}],
                "element_list": [{"element_id": 123}],
                "watermark_info": {"enabled": True},
                "sound": "off",
                "mode": "pro",
            },
        )
    finally:
        await client.close()

    assert calls == [
        (
            "POST",
            f"{DEFAULT_KLING_BASE_URL}/v1/videos/omni-video",
            {
                "model_name": "kling-video-o1",
                "mode": "pro",
                "multi_shot": True,
                "shot_type": "customize",
                "multi_prompt": [
                    {"index": 1, "prompt": "shot 1", "duration": "5"},
                    {"index": 2, "prompt": "shot 2", "duration": "5"},
                ],
                "image_list": [{"image_url": "https://example.com/ref.png"}],
                "element_list": [{"element_id": 123}],
                "watermark_info": {"enabled": True},
                "sound": "off",
                "duration": "10",
                "aspect_ratio": "16:9",
            },
        )
    ]


@pytest.mark.asyncio
async def test_kling_omni_video_strips_image_type_when_multi_shot_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "KLING_ACCESS_KEY", "ak-test")
    monkeypatch.setattr(settings, "KLING_SECRET_KEY", "sk-test")

    client = KlingAPIClient(model="kling-v3-omni")
    calls: list[tuple[str, str, dict]] = []

    async def fake_request(method: str, url: str, json=None, params=None):
        calls.append((method, url, json or {}))
        return httpx.Response(
            200,
            json={"code": 0, "data": {"task_id": "task-1", "task_status": "submitted"}},
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(client.client, "request", fake_request)
    try:
        await client.create_omni_video_task(
            prompt="ignored",
            duration=5,
            aspect_ratio="16:9",
            extra_body={
                "multi_shot": True,
                "shot_type": "customize",
                "multi_prompt": ["shot 1", "shot 2"],
                "image_list": [{"image_url": "https://example.com/start.png", "type": "first_frame"}],
            },
        )
    finally:
        await client.close()

    assert calls[0][2]["image_list"] == [{"image_url": "https://example.com/start.png"}]
