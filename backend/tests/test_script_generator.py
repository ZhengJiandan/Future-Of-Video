import json
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


class _CapturingDoubaoLLM:
    def __init__(self, content: str) -> None:
        self._content = content
        self.calls = []

    async def chat_completion(self, messages, **kwargs):
        self.calls.append({"messages": messages, "kwargs": kwargs})
        return _StaticResponse(self._content)


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


def test_build_script_input_policy_uses_strict_mode_for_detailed_input(generator: ScriptGenerator) -> None:
    policy = generator._build_script_input_policy(
        """
        1. 角色关系：姐妹二人已经失联三年，重逢时不要立刻和解。
        2. 时间地点：凌晨两点，老城区废弃照相馆，外面下雨。
        3. 剧情顺序必须保留：姐姐先试探，妹妹再拿出底片，最后停在没有说破真相。
        4. 不要新增旁白，不要增加第三个人，不要改成大团圆结局。
        """.strip()
    )

    assert policy["fidelity_mode"] == "strict"
    assert policy["is_user_input_detailed"] is True
    assert policy["temperature"] == pytest.approx(0.1)
    assert any("剧情顺序必须保留" in item for item in policy["preserve_points"])


def test_build_script_input_policy_keeps_standard_mode_for_brief_input(generator: ScriptGenerator) -> None:
    policy = generator._build_script_input_policy("一只猫在窗边看雨，气质安静。")

    assert policy["fidelity_mode"] == "standard"
    assert policy["is_user_input_detailed"] is False
    assert policy["temperature"] == pytest.approx(0.2)


@pytest.mark.asyncio
async def test_call_llm_for_script_passes_input_fidelity_policy(
    generator: ScriptGenerator,
) -> None:
    llm = _CapturingDoubaoLLM(
        json.dumps(
            {
                "title": "照相馆重逢",
                "synopsis": "姐妹在雨夜照相馆重逢。",
                "tone": "克制",
                "themes": ["重逢"],
                "characters": [],
                "scenes": [
                    {
                        "scene_number": 1,
                        "scene_profile_id": "",
                        "scene_profile_version": 1,
                        "scene_type": "对峙",
                        "title": "雨夜照相馆",
                        "description": "两姐妹在废弃照相馆对峙。",
                        "story_function": "重逢",
                        "location": "老城区废弃照相馆",
                        "location_detail": "",
                        "time": "凌晨",
                        "weather": "雨夜",
                        "lighting": "冷色霓虹",
                        "atmosphere": "压抑",
                        "mood": "克制",
                        "shots": [
                            {
                                "shot_number": 1,
                                "duration": 4.0,
                                "scene_profile_id": "",
                                "scene_profile_version": 1,
                                "character_profile_ids": [],
                                "character_profile_versions": {},
                                "prompt_focus": "保持原始重逢关系",
                                "shot_type": "中景",
                                "camera_angle": "平视",
                                "camera_movement": "轻推",
                                "description": "姐姐先试探，妹妹沉默回应。",
                                "environment": "旧照相馆内",
                                "lighting": "冷色霓虹",
                                "characters_in_shot": [],
                                "actions": [],
                                "dialogues": [],
                                "sound_effects": ["雨声"],
                                "music": "",
                            }
                        ],
                    }
                ],
            },
            ensure_ascii=False,
        )
    )
    generator.llm = llm

    await generator._call_llm_for_script(
        user_input=(
            "角色关系：姐妹二人已经失联三年，重逢时不要立刻和解。\n"
            "时间地点：凌晨两点，老城区废弃照相馆，外面下雨。\n"
            "剧情顺序必须保留：姐姐先试探，妹妹再拿出底片，最后停在没有说破真相。\n"
            "不要新增旁白，不要增加第三个人，不要改成大团圆结局。"
        ),
        style="写实",
        target_total_duration=12.0,
        reference_image_count=0,
        intent={},
        matched_characters=[],
        matched_scenes=[],
        correction_note="请修正时长，但保持原意。",
    )

    assert len(llm.calls) == 1
    payload = json.loads(llm.calls[0]["messages"][1].content)

    assert payload["input_policy"]["fidelity_mode"] == "strict"
    assert payload["input_policy"]["is_user_input_detailed"] is True
    assert any("姐姐先试探" in item for item in payload["input_policy"]["preserve_points"])
    assert "不要改写用户输入中已明确给出的剧情事实" in payload["correction_note"]
    assert llm.calls[0]["kwargs"]["temperature"] == pytest.approx(0.1)


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


@pytest.mark.asyncio
async def test_generate_full_script_retries_when_first_result_has_no_shots(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_notes: list[str] = []
    responses = iter(
        [
            {"title": "空剧本"},
            {"title": "有效剧本"},
        ]
    )
    parsed_scripts = iter(
        [
            FullScript(
                title="空剧本",
                scenes=[
                    SceneInfo(
                        scene_number=1,
                        shots=[],
                    )
                ],
            ),
            FullScript(
                title="有效剧本",
                scenes=[
                    SceneInfo(
                        scene_number=1,
                        shots=[
                            ShotInfo(
                                shot_number=1,
                                duration=3.0,
                                description="镜头一",
                            )
                        ],
                    )
                ],
            ),
        ]
    )

    async def fake_prepare_character_resolution(**kwargs):
        return {
            "generation_intent": {},
            "library_character_profiles": [],
            "temporary_character_profiles": [],
            "character_resolution": {},
        }

    async def fake_select_scene_profiles(**kwargs):
        return []

    async def fake_call_llm_for_script(**kwargs):
        call_notes.append(kwargs.get("correction_note", ""))
        return next(responses)

    def fake_parse_script_data(**kwargs):
        return next(parsed_scripts)

    async def passthrough_align(full_script, **kwargs):
        return full_script

    async def passthrough_repair(full_script, **kwargs):
        return full_script

    monkeypatch.setattr(generator, "prepare_character_resolution", fake_prepare_character_resolution)
    monkeypatch.setattr(generator, "_select_scene_profiles", fake_select_scene_profiles)
    monkeypatch.setattr(generator, "_call_llm_for_script", fake_call_llm_for_script)
    monkeypatch.setattr(generator, "_parse_script_data", fake_parse_script_data)
    monkeypatch.setattr(generator, "_align_script_duration", passthrough_align)
    monkeypatch.setattr(generator, "_repair_shot_late_entry_risks", passthrough_repair)

    result = await generator.generate_full_script(user_input="测试生成剧本")

    assert result.title == "有效剧本"
    assert len(call_notes) == 2
    assert call_notes[0] == ""
    assert "生成结果缺少分镜" in call_notes[1]


@pytest.mark.asyncio
async def test_generate_full_script_reuses_confirmed_character_resolution(
    generator: ScriptGenerator,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    valid_script = FullScript(
        title="有效剧本",
        scenes=[
            SceneInfo(
                scene_number=1,
                shots=[
                    ShotInfo(
                        shot_number=1,
                        duration=3.0,
                        description="镜头一",
                    )
                ],
            )
        ],
    )

    async def fail_prepare_character_resolution(**kwargs):
        raise AssertionError("should not re-run prepare_character_resolution")

    async def fake_select_scene_profiles(**kwargs):
        captured["intent"] = kwargs["intent"]
        return []

    async def fake_call_llm_for_script(**kwargs):
        captured["matched_characters"] = kwargs["matched_characters"]
        return {"title": "有效剧本"}

    def fake_parse_script_data(**kwargs):
        captured["library_characters"] = kwargs["library_characters"]
        captured["temporary_characters"] = kwargs["temporary_characters"]
        captured["character_resolution"] = kwargs["character_resolution"]
        return valid_script

    async def passthrough_align(full_script, **kwargs):
        return full_script

    async def passthrough_repair(full_script, **kwargs):
        return full_script

    monkeypatch.setattr(generator, "prepare_character_resolution", fail_prepare_character_resolution)
    monkeypatch.setattr(generator, "_select_scene_profiles", fake_select_scene_profiles)
    monkeypatch.setattr(generator, "_call_llm_for_script", fake_call_llm_for_script)
    monkeypatch.setattr(generator, "_parse_script_data", fake_parse_script_data)
    monkeypatch.setattr(generator, "_align_script_duration", passthrough_align)
    monkeypatch.setattr(generator, "_repair_shot_late_entry_risks", passthrough_repair)

    result = await generator.generate_full_script(
        user_input="测试生成剧本",
        character_profiles=[
            {"id": "library-1", "name": "正式角色", "profile_version": 1},
            {"id": "temp-1", "name": "临时角色", "profile_version": 1},
        ],
        generation_intent={"character_queries": [{"name_hint": "正式角色"}]},
        character_resolution={"status": "matched", "message": "已确认"},
        library_character_profiles=[
            {"id": "library-1", "name": "正式角色", "profile_version": 1},
        ],
        temporary_character_profiles=[
            {"id": "temp-1", "name": "临时角色", "profile_version": 1},
        ],
    )

    assert result is valid_script
    assert captured["intent"] == {"character_queries": [{"name_hint": "正式角色"}]}
    assert [item["id"] for item in captured["matched_characters"]] == ["library-1", "temp-1"]
    assert [item["id"] for item in captured["library_characters"]] == ["library-1"]
    assert [item["id"] for item in captured["temporary_characters"]] == ["temp-1"]
    assert captured["character_resolution"] == {"status": "matched", "message": "已确认"}
