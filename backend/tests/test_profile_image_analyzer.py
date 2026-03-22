from pathlib import Path

import pytest

from app.services.profile_image_analyzer import ProfileImageAnalyzerService


def test_normalize_character_result_coerces_text_and_lists() -> None:
    service = ProfileImageAnalyzerService()

    result = service._normalize_character_result(
        {
            "name": "三花猫队长",
            "appearance": "短毛，圆脸",
            "tags": "猫, 队长，暖色",
            "must_keep": ["圆脸", "暖棕白配色", "圆脸"],
            "forbidden_traits": None,
            "aliases": "咪队长、三花",
        }
    )

    assert result["name"] == "三花猫队长"
    assert result["appearance"] == "短毛，圆脸"
    assert result["tags"] == ["猫", "队长", "暖色"]
    assert result["must_keep"] == ["圆脸", "暖棕白配色"]
    assert result["forbidden_traits"] == []
    assert result["aliases"] == ["咪队长", "三花"]


def test_normalize_scene_result_coerces_text_and_lists() -> None:
    service = ProfileImageAnalyzerService()

    result = service._normalize_scene_result(
        {
            "location": "木质客厅",
            "lighting": "午后侧逆光",
            "tags": ["温馨", "室内", "温馨"],
            "props_must_have": "木窗, 地毯，猫爬架",
            "camera_preferences": None,
        }
    )

    assert result["location"] == "木质客厅"
    assert result["lighting"] == "午后侧逆光"
    assert result["tags"] == ["温馨", "室内"]
    assert result["props_must_have"] == ["木窗", "地毯", "猫爬架"]
    assert result["camera_preferences"] == []


@pytest.mark.asyncio
async def test_analyze_with_image_uses_doubao_multimodal_payload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image_path = tmp_path / "cat.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    service = ProfileImageAnalyzerService()
    monkeypatch.setattr(service, "api_key", "doubao-key")
    monkeypatch.setattr(service, "base_url", "https://ark.cn-beijing.volces.com/api/v3")
    monkeypatch.setattr(service, "model", "doubao-seed-2-0-lite-260215")

    captured: dict[str, object] = {}

    async def fake_request_completion(request_body):
        captured["request_body"] = request_body
        return {
            "choices": [
                {
                    "message": {
                        "content": '{"name":"三花猫队长","tags":["猫","队长"]}'
                    }
                }
            ]
        }

    monkeypatch.setattr(service, "_request_completion", fake_request_completion)

    result = await service._analyze_with_image(
        image_path=image_path,
        system_prompt="system prompt",
        user_prompt="user prompt",
    )

    request_body = captured["request_body"]
    assert request_body["model"] == "doubao-seed-2-0-lite-260215"
    assert request_body["messages"][0]["role"] == "system"
    assert request_body["messages"][1]["content"][0]["type"] == "text"
    assert request_body["messages"][1]["content"][1]["type"] == "image_url"
    assert request_body["messages"][1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert result == {"name": "三花猫队长", "tags": ["猫", "队长"]}


def test_parse_json_payload_accepts_code_fence() -> None:
    service = ProfileImageAnalyzerService()

    result = service._parse_json_payload(
        """```json
{"location":"客厅","tags":["室内"]}
```"""
    )

    assert result == {"location": "客厅", "tags": ["室内"]}
