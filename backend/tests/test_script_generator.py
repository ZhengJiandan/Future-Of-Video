import logging

import pytest

from app.services import script_generator as script_generator_module
from app.services.script_generator import FullScript, SceneInfo, ScriptGenerator, ShotInfo


class _DummyDoubaoLLM:
    def __init__(self, *args, **kwargs) -> None:
        pass


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
