from app.api.endpoints.script_pipeline import _build_split_response_from_state, _split_request_matches_state


def test_split_request_matches_state_when_script_and_params_match() -> None:
    state = {
        "scriptDraft": "镜头 1\n镜头 2",
        "maxSegmentDuration": 10,
        "targetTotalDuration": 42,
    }

    assert _split_request_matches_state(
        state,
        script_text="镜头 1\n镜头 2",
        max_segment_duration=10.0,
        target_total_duration=42.0,
    )


def test_split_request_matches_state_returns_false_when_params_differ() -> None:
    state = {
        "scriptDraft": "镜头 1\n镜头 2",
        "maxSegmentDuration": 10,
        "targetTotalDuration": 42,
    }

    assert not _split_request_matches_state(
        state,
        script_text="镜头 1\n镜头 2\n镜头 3",
        max_segment_duration=10.0,
        target_total_duration=42.0,
    )
    assert not _split_request_matches_state(
        state,
        script_text="镜头 1\n镜头 2",
        max_segment_duration=8.0,
        target_total_duration=42.0,
    )
    assert not _split_request_matches_state(
        state,
        script_text="镜头 1\n镜头 2",
        max_segment_duration=10.0,
        target_total_duration=40.0,
    )


def test_build_split_response_from_state_uses_cached_segments() -> None:
    state = {
        "scriptDraft": "完整剧本",
        "segments": [
            {"segment_number": 1, "duration": 4.0, "title": "片段 1"},
            {"segment_number": 2, "duration": 5.0, "title": "片段 2"},
        ],
        "splitValidationReport": {
            "status": "pass",
            "actual_total_duration": 9.0,
        },
        "continuityPoints": [{"between_segments": [1, 2]}],
    }

    result = _build_split_response_from_state(state)

    assert result == {
        "script_text": "完整剧本",
        "total_duration": 9.0,
        "segment_count": 2,
        "segments": state["segments"],
        "continuity_points": state["continuityPoints"],
        "validation_report": state["splitValidationReport"],
    }
