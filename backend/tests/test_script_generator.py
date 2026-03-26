import logging

import pytest

from app.core.provider_keys import MissingProviderConfigError
from app.services import script_generator as script_generator_module
from app.services.script_generator import FullScript, SceneInfo, ScriptGenerator, ShotInfo


class _DummyDoubaoLLM:
    def __init__(self, *args, **kwargs) -> None:
        pass


class _MissingKeyDoubaoLLM:
    async def chat_completion(self, *args, **kwargs):
        raise MissingProviderConfigError(
            code="missing_doubao_api_key",
            message="未配置 DOUBAO_API_KEY，无法调用豆包能力。",
        )


class _BrokenDoubaoLLM:
    async def chat_completion(self, *args, **kwargs):
        raise RuntimeError("boom")


class _StaticResponse:
    def __init__(self, content: str) -> None:
        self._content = content

    def get_content(self) -> str:
        return self._content


@pytest.fixture
def generator(monkeypatch: pytest.MonkeyPatch) -> ScriptGenerator:
    monkeypatch.setattr(script_generator_module, "DoubaoLLM", _DummyDoubaoLLM)
    return ScriptGenerator()


def test_validate_full_script_warns_on_late_character_entry_risk(
    generator: ScriptGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    script = FullScript(
        title="测试剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="客厅里两只猫对视，第三只猫突然出现并跳上沙发。",
                        character_profile_ids=["cat_a", "cat_b", "cat_c"],
                    )
                ],
            )
        ],
    )

    with caplog.at_level(logging.WARNING):
        generator._validate_full_script(script)

    assert "镜头内新角色中途入场风险" in caplog.text
    assert "场景1-镜头1" in caplog.text
    assert "突然出现" in caplog.text


def test_collect_shot_late_entry_risks_ignores_normal_shot(generator: ScriptGenerator) -> None:
    script = FullScript(
        title="测试剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="三只猫已经坐在窗边，一起安静看雨。",
                        character_profile_ids=["cat_a", "cat_b", "cat_c"],
                    )
                ],
            )
        ],
    )

    assert generator._collect_shot_late_entry_risks(script) == []


@pytest.mark.asyncio
async def test_repair_shot_late_entry_risks_uses_improved_script(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_script = FullScript(
        title="原剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="两只猫望向门口，第三只猫突然出现。",
                        character_profile_ids=["cat_a", "cat_b", "cat_c"],
                    )
                ],
            )
        ],
    )
    improved_script = FullScript(
        title="修正剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=2.0,
                        description="两只猫望向门口。",
                        character_profile_ids=["cat_a", "cat_b"],
                    ),
                    ShotInfo(
                        shot_number=2,
                        duration=2.0,
                        description="新镜头切到第三只猫站在门边。",
                        character_profile_ids=["cat_c"],
                    ),
                ],
            )
        ],
    )
    captured_note = {}

    async def fake_call_llm_for_script(*args, **kwargs):
        captured_note["correction_note"] = kwargs.get("correction_note", "")
        return {"ok": True}

    def fake_parse_script_data(*args, **kwargs):
        return improved_script

    monkeypatch.setattr(generator, "_call_llm_for_script", fake_call_llm_for_script)
    monkeypatch.setattr(generator, "_parse_script_data", fake_parse_script_data)

    result = await generator._repair_shot_late_entry_risks(
        original_script,
        user_input="三只猫在客厅里互动",
        style="温馨",
        target_total_duration=None,
        reference_image_count=0,
        intent={},
        matched_characters=[],
        matched_scenes=[],
    )

    assert result is improved_script
    assert "场景1-镜头1" in captured_note["correction_note"]
    assert "新镜头开始" in captured_note["correction_note"]


@pytest.mark.asyncio
async def test_repair_shot_late_entry_risks_keeps_original_when_not_improved(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_script = FullScript(
        title="原剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="第三只猫突然出现。",
                        character_profile_ids=["cat_a", "cat_b", "cat_c"],
                    )
                ],
            )
        ],
    )
    still_risky_script = FullScript(
        title="仍有风险",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="第三只猫进入画面，另外两只猫看向它。",
                        character_profile_ids=["cat_a", "cat_b", "cat_c"],
                    )
                ],
            )
        ],
    )

    async def fake_call_llm_for_script(*args, **kwargs):
        return {"ok": True}

    def fake_parse_script_data(*args, **kwargs):
        return still_risky_script

    monkeypatch.setattr(generator, "_call_llm_for_script", fake_call_llm_for_script)
    monkeypatch.setattr(generator, "_parse_script_data", fake_parse_script_data)

    result = await generator._repair_shot_late_entry_risks(
        original_script,
        user_input="三只猫在客厅里互动",
        style="温馨",
        target_total_duration=None,
        reference_image_count=0,
        intent={},
        matched_characters=[],
        matched_scenes=[],
    )

    assert result is original_script


@pytest.mark.asyncio
async def test_prepare_character_resolution_raises_when_doubao_key_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script_generator_module, "DoubaoLLM", _MissingKeyDoubaoLLM)
    generator = ScriptGenerator()

    with pytest.raises(MissingProviderConfigError):
        await generator.prepare_character_resolution(
            user_input="帮我生成一个未来都市里的女特工角色",
            style="电影感",
            character_profiles=[
                {
                    "id": "library-1",
                    "name": "无关角色",
                    "role": "配角",
                    "category": "测试",
                    "archetype": "",
                    "llm_summary": "一个和当前需求无关的角色。",
                }
            ],
        )


@pytest.mark.asyncio
async def test_prepare_character_resolution_raises_when_intent_extraction_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(script_generator_module, "DoubaoLLM", _BrokenDoubaoLLM)
    generator = ScriptGenerator()

    with pytest.raises(RuntimeError, match="角色分析调用豆包失败"):
        await generator.prepare_character_resolution(
            user_input="帮我生成一个未来都市里的女特工角色",
            style="电影感",
            character_profiles=[],
        )


@pytest.mark.asyncio
async def test_select_profiles_returns_empty_when_no_profile_scores_match(
    generator: ScriptGenerator,
) -> None:
    result = await generator._select_profiles(
        profile_type="character",
        user_input="完全不相关的需求描述",
        intent_queries=[{"keywords": ["不存在的关键词"], "role": "", "archetype": "", "category": "", "name_hint": ""}],
        profiles=[
            {
                "id": "char-1",
                "name": "橘丸",
                "role": "盗贼",
                "category": "动物",
                "archetype": "",
                "description": "虎斑猫盗贼",
                "llm_summary": "擅长潜入的猫。",
            },
            {
                "id": "char-2",
                "name": "蓝尾",
                "role": "黑客",
                "category": "动物",
                "archetype": "",
                "description": "技术支援猫",
                "llm_summary": "负责监控接入。",
            },
        ],
        desired_count=3,
    )

    assert result == []


def test_estimate_desired_character_count_is_not_limited_to_three(generator: ScriptGenerator) -> None:
    intent = {
        "character_queries": [
            {"name_hint": "角色1"},
            {"name_hint": "角色2"},
            {"name_hint": "角色3"},
            {"name_hint": "角色4"},
            {"name_hint": "角色5"},
        ]
    }

    assert generator._estimate_desired_character_count(intent) == 5


@pytest.mark.asyncio
async def test_select_character_profiles_uses_dynamic_desired_count(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, int] = {}

    async def fake_select_profiles(**kwargs):
        captured["desired_count"] = kwargs["desired_count"]
        return []

    monkeypatch.setattr(generator, "_select_profiles", fake_select_profiles)

    await generator._select_character_profiles(
        user_input="五人群像戏",
        intent={
            "character_queries": [
                {"name_hint": "角色1"},
                {"name_hint": "角色2"},
                {"name_hint": "角色3"},
                {"name_hint": "角色4"},
                {"name_hint": "角色5"},
            ]
        },
        profiles=[],
    )

    assert captured["desired_count"] == 5


@pytest.mark.asyncio
async def test_call_llm_for_script_retries_when_first_response_is_invalid_json(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    responses = iter(
        [
            _StaticResponse('{"title":"坏掉的JSON"'),
            _StaticResponse('{"title":"有效结果","synopsis":"","tone":"","themes":[],"characters":[],"scenes":[]}'),
        ]
    )
    labels: list[str] = []

    async def fake_chat_completion(messages, **kwargs):
        labels.append(kwargs.get("request_label", ""))
        return next(responses)

    monkeypatch.setattr(generator.llm, "chat_completion", fake_chat_completion, raising=False)

    result = await generator._call_llm_for_script(
        user_input="测试",
        style="",
        target_total_duration=None,
        reference_image_count=0,
        intent={},
        matched_characters=[],
        matched_scenes=[],
    )

    assert result["title"] == "有效结果"
    assert labels == ["generate_full_script", "generate_full_script_repair_json"]
