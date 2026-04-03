from app.api.endpoints.script_pipeline import _build_keyframe_state_signature, _build_keyframes_response_from_state, _keyframe_request_matches_state


def test_keyframe_request_matches_state_when_signature_matches() -> None:
    state = {
        "keyframeRequestSignature": _build_keyframe_state_signature(
            style="写实",
            selected_character_ids=["char-a", "char-b"],
            selected_scene_ids=["scene-a"],
            segments=[{"segment_number": 1, "title": "片段 1"}],
            reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
            workflow_mode="long_shot",
        )
    }

    assert _keyframe_request_matches_state(
        state,
        style="写实",
        selected_character_ids=["char-a", "char-b"],
        selected_scene_ids=["scene-a"],
        segments=[{"segment_number": 1, "title": "片段 1"}],
        reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        workflow_mode="long_shot",
    )


def test_keyframe_request_matches_state_returns_false_when_request_differs() -> None:
    state = {
        "keyframeRequestSignature": _build_keyframe_state_signature(
            style="写实",
            selected_character_ids=["char-a"],
            selected_scene_ids=["scene-a"],
            segments=[{"segment_number": 1, "title": "片段 1"}],
            reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
            workflow_mode="long_shot",
        )
    }

    assert not _keyframe_request_matches_state(
        state,
        style="二次元",
        selected_character_ids=["char-a"],
        selected_scene_ids=["scene-a"],
        segments=[{"segment_number": 1, "title": "片段 1"}],
        reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        workflow_mode="long_shot",
    )
    assert not _keyframe_request_matches_state(
        state,
        style="写实",
        selected_character_ids=["char-b"],
        selected_scene_ids=["scene-a"],
        segments=[{"segment_number": 1, "title": "片段 1"}],
        reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        workflow_mode="long_shot",
    )
    assert not _keyframe_request_matches_state(
        state,
        style="写实",
        selected_character_ids=["char-a"],
        selected_scene_ids=["scene-a"],
        segments=[{"segment_number": 2, "title": "片段 2"}],
        reference_images=[{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        workflow_mode="long_shot",
    )


def test_build_keyframes_response_from_state_uses_cached_keyframes() -> None:
    state = {
        "projectTitle": "测试项目",
        "stylePreference": "写实",
        "selectedCharacterIds": ["char-a"],
        "selectedSceneIds": ["scene-a"],
        "referenceImages": [{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        "generatedScript": {
            "character_profiles": [{"id": "char-a", "name": "角色A"}],
            "scene_profiles": [{"id": "scene-a", "name": "场景A"}],
        },
        "keyframes": [
            {
                "segment_number": 1,
                "title": "片段 1",
                "start_frame": {"asset_url": "/uploads/start.png", "asset_type": "image/png", "asset_filename": "start.png"},
                "end_frame": {"asset_url": "", "asset_type": "image/png", "asset_filename": ""},
            }
        ],
    }

    result = _build_keyframes_response_from_state(state)

    assert result == {
        "project_title": "测试项目",
        "style": "写实",
        "selected_character_ids": ["char-a"],
        "selected_scene_ids": ["scene-a"],
        "character_profiles": [{"id": "char-a", "name": "角色A"}],
        "scene_profiles": [{"id": "scene-a", "name": "场景A"}],
        "reference_images": [{"id": "ref-1", "url": "/uploads/ref-1.png"}],
        "keyframes": state["keyframes"],
    }
