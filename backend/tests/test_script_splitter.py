from typing import List

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
) -> ParsedShot:
    return ParsedShot(
        scene_number=1,
        scene_title="测试场景",
        scene_type="interior",
        scene_profile_id="scene_test",
        scene_profile_version=1,
        location="客厅",
        time_label="白天",
        atmosphere="平静",
        shot_number=shot_number,
        duration=end_time - start_time,
        description=f"shot-{shot_number}",
        character_profile_ids=character_profile_ids,
        start_time=start_time,
        end_time=end_time,
    )


@pytest.fixture
def splitter(monkeypatch: pytest.MonkeyPatch) -> ScriptSplitter:
    monkeypatch.setattr(script_splitter_module, "DoubaoLLM", _DummyDoubaoLLM)
    return ScriptSplitter(
        SplitConfig(
            max_segment_duration=10.0,
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
