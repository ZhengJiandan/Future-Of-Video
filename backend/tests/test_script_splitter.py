from typing import List, Optional
import json

import pytest

from app.services import script_splitter as script_splitter_module
from app.services.script_splitter import ParsedShot, ScriptSplitter, SplitConfig, VideoSegment


class _DummyDoubaoLLM:
    def __init__(self, *args, **kwargs) -> None:
        pass


def _build_shot(
    *,
    shot_number: int,
    start_time: float,
    end_time: float,
    character_profile_ids: List[str],
    description: str = "",
    characters_in_shot: Optional[List[str]] = None,
    actions: Optional[List[str]] = None,
    dialogues: Optional[List[str]] = None,
    shot_type: str = "",
    camera_angle: str = "",
    camera_movement: str = "",
    lighting: str = "",
    atmosphere: str = "",
) -> ParsedShot:
    return ParsedShot(
        scene_number=1,
        scene_title="测试场景",
        scene_type="interior",
        scene_profile_id="scene_test",
        scene_profile_version=1,
        location="客厅",
        time_label="白天",
        atmosphere=atmosphere or "平静",
        shot_number=shot_number,
        duration=end_time - start_time,
        description=description or f"shot-{shot_number}",
        characters_in_shot=characters_in_shot or [],
        character_profile_ids=character_profile_ids,
        actions=actions or [],
        dialogues=dialogues or [],
        shot_type=shot_type,
        camera_angle=camera_angle,
        camera_movement=camera_movement,
        lighting=lighting,
        start_time=start_time,
        end_time=end_time,
    )


@pytest.fixture
def splitter(monkeypatch: pytest.MonkeyPatch) -> ScriptSplitter:
    monkeypatch.setattr(script_splitter_module, "DoubaoLLM", _DummyDoubaoLLM)
    return ScriptSplitter(
        SplitConfig(
            max_segment_duration=15.0,
            min_segment_duration=3.0,
            prefer_scene_boundary=True,
            preserve_dialogue=True,
            smooth_transition=True,
        )
    )


def test_first_frame_character_stability_adds_split_for_late_entry(splitter: ScriptSplitter) -> None:
    parsed_shots = [
        _build_shot(shot_number=1, start_time=0.0, end_time=3.0, character_profile_ids=["cat_a"]),
        _build_shot(shot_number=2, start_time=3.0, end_time=6.0, character_profile_ids=["cat_a"]),
        _build_shot(shot_number=3, start_time=6.0, end_time=9.0, character_profile_ids=["cat_a", "cat_b"]),
        _build_shot(shot_number=4, start_time=9.0, end_time=12.0, character_profile_ids=["cat_a", "cat_b"]),
    ]
    split_points = [
        {
            "segment_number": 1,
            "start_time": 0.0,
            "end_time": 12.0,
            "duration": 12.0,
            "shots": parsed_shots,
        }
    ]

    optimized = splitter._optimize_split_points_for_first_frame_character_stability(
        split_points=split_points,
        parsed_shots=parsed_shots,
        target_duration=12.0,
    )

    assert [round(float(point["end_time"]), 2) for point in optimized] == [6.0, 12.0]
    assert optimized[0]["split_reason"] == "character_first_frame_stability_split"
    assert optimized[1]["start_time"] == 6.0


def test_segment_annotation_marks_late_entry_when_split_is_not_possible(splitter: ScriptSplitter) -> None:
    parsed_shots = [
        _build_shot(shot_number=1, start_time=0.0, end_time=2.0, character_profile_ids=["cat_a"]),
        _build_shot(shot_number=2, start_time=2.0, end_time=4.0, character_profile_ids=["cat_a", "cat_b"]),
        _build_shot(shot_number=3, start_time=4.0, end_time=6.0, character_profile_ids=["cat_a", "cat_b"]),
    ]
    segment = VideoSegment(
        segment_number=1,
        title="片段 1",
        start_time=0.0,
        end_time=6.0,
        duration=6.0,
    )

    annotated_segments = splitter._annotate_segments_for_video_generation(
        segments=[segment],
        parsed_shots=parsed_shots,
    )

    assert annotated_segments[0].late_entry_character_profile_ids == ["cat_b"]


def test_build_local_video_prompt_defaults_to_single_shot_without_llm_decision(splitter: ScriptSplitter) -> None:
    segment_shots = [
        _build_shot(
            shot_number=1,
            start_time=0.0,
            end_time=3.0,
            character_profile_ids=["cat_a"],
            description="黑猫站在便利店门口盯着街对面",
            characters_in_shot=["黑猫"],
            actions=["黑猫缓慢抬头看向雨夜街口"],
            shot_type="中景",
            camera_angle="平视",
            camera_movement="缓慢推近",
            lighting="霓虹反光",
            atmosphere="压迫",
        ),
        _build_shot(
            shot_number=2,
            start_time=3.0,
            end_time=6.0,
            character_profile_ids=["cat_a"],
            description="黑猫迈步穿过积水，停在街灯下",
            characters_in_shot=["黑猫"],
            actions=["黑猫穿过积水走向街灯下"],
            dialogues=["黑猫：终于等到你了"],
            shot_type="近景",
            camera_angle="低机位",
            camera_movement="跟拍",
            lighting="冷色街灯",
            atmosphere="紧张",
        ),
        _build_shot(
            shot_number=3,
            start_time=6.0,
            end_time=9.0,
            character_profile_ids=["cat_a"],
            description="黑猫在街灯下突然回头，准备迎接来者",
            characters_in_shot=["黑猫"],
            actions=["黑猫回头并稳住站位准备对峙"],
            shot_type="特写",
            camera_angle="侧后方",
            camera_movement="快速切近",
            lighting="背光轮廓",
            atmosphere="爆发前的压迫感",
        ),
    ]

    prompt_payload = splitter._build_local_video_prompt(
        segment_script="测试片段",
        point={"start_time": 0.0, "end_time": 9.0, "duration": 9.0, "prompt_focus": "黑猫雨夜对峙"},
        segment_shots=segment_shots,
        has_previous=True,
        has_next=True,
    )

    prompt = prompt_payload["prompt"]
    assert "开场画面" in prompt
    assert "动作推进" in prompt
    assert "镜头设计" in prompt
    assert "结尾画面" in prompt
    assert "开头要自然承接上一段" in prompt
    assert "time window" not in prompt
    assert "character profile ids" not in prompt
    assert "spoken lines" not in prompt

    config = prompt_payload["config"]
    assert config["kling_multi_shot_enabled"] is False
    assert "kling_shot_type" not in config
    assert "kling_multi_prompt" not in config
    assert config["kling_multi_shot_reason"] == "默认按单镜头模式处理"
    assert config["kling_multi_shot_source"] == "structured-script-splitter"


@pytest.mark.asyncio
async def test_generate_video_prompt_with_llm_preserves_multi_shot_decision(splitter: ScriptSplitter) -> None:
    segment_shots = [
        _build_shot(
            shot_number=1,
            start_time=0.0,
            end_time=3.0,
            character_profile_ids=["cat_a"],
            description="黑猫在便利店门口停下",
            characters_in_shot=["黑猫"],
            actions=["黑猫停下并看向街对面"],
        ),
        _build_shot(
            shot_number=2,
            start_time=3.0,
            end_time=6.0,
            character_profile_ids=["cat_a"],
            description="黑猫穿过积水走向街灯",
            characters_in_shot=["黑猫"],
            actions=["黑猫穿过积水走向街灯"],
        ),
    ]

    class _FakeResponse:
        def __init__(self, content: str) -> None:
            self._content = content

        def get_content(self) -> str:
            return self._content

    async def fake_chat_completion(*args, **kwargs):
        return _FakeResponse(
            json.dumps(
                {
                    "prompt": "",
                    "negative_prompt": "模糊, 漂移",
                    "config": {
                        "style": "cinematic_realistic",
                        "kling_multi_shot_enabled": True,
                        "kling_shot_type": "customize",
                        "kling_multi_prompt": ["黑猫停在门口观察街对面", "黑猫穿过积水走向街灯"],
                        "kling_multi_shot_reason": "该片段有明显的连续镜头推进",
                    },
                },
                ensure_ascii=False,
            )
        )

    splitter.llm.chat_completion = fake_chat_completion  # type: ignore[attr-defined]

    payload = await splitter._generate_video_prompt_with_llm(
        segment_script="测试片段",
        point={"segment_number": 1, "start_time": 0.0, "end_time": 6.0, "duration": 6.0, "prompt_focus": "黑猫雨夜行动"},
        segment_shots=segment_shots,
        has_previous=False,
        has_next=True,
    )

    assert payload is not None
    config = payload["config"]
    assert config["kling_multi_shot_enabled"] is True
    assert config["kling_shot_type"] == "customize"
    assert config["kling_multi_prompt"] == ["黑猫停在门口观察街对面", "黑猫穿过积水走向街灯"]
    assert config["kling_multi_shot_reason"] == "该片段有明显的连续镜头推进"
    assert config["kling_multi_shot_source"] == "llm-script-splitter"
    assert payload["prompt"] == "黑猫停在门口观察街对面；黑猫穿过积水走向街灯"


def test_rule_based_validation_flags_summary_like_video_prompt(splitter: ScriptSplitter) -> None:
    segment = VideoSegment(
        segment_number=1,
        title="片段 1",
        description="黑猫穿过雨夜街道",
        start_time=0.0,
        end_time=6.0,
        duration=6.0,
        shots_summary="镜头1：黑猫看向街口\n镜头2：黑猫走向街灯",
        key_actions=["看向街口", "走向街灯"],
        video_prompt="time window 0.0s to 6.0s, scene profile scene_test, character profile ids cat_a, spoken lines hello",
    )

    report = splitter._build_rule_based_validation_report(segments=[segment], target_duration=None)
    prompt_check = next(item for item in report["checks"] if item["code"] == "video_prompt_fit")
    segment_review = report["segment_reviews"][0]

    assert prompt_check["status"] == "warning"
    assert segment_review["status"] == "warning"
    assert any("video_prompt" in issue for issue in segment_review["issues"])
