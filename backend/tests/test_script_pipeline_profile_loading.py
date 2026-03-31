from app.api.endpoints.script_pipeline import _should_use_all_library_profiles_when_unconstrained


def test_profile_loading_allows_character_autoload_when_unconstrained() -> None:
    assert _should_use_all_library_profiles_when_unconstrained(
        selected_ids=[],
        direct_profiles=[],
        auto_match_when_empty=True,
    )


def test_profile_loading_disables_scene_autoload_when_unconstrained() -> None:
    assert not _should_use_all_library_profiles_when_unconstrained(
        selected_ids=[],
        direct_profiles=[],
        auto_match_when_empty=False,
    )


def test_profile_loading_skips_autoload_when_user_already_provided_constraints() -> None:
    assert not _should_use_all_library_profiles_when_unconstrained(
        selected_ids=["scene-1"],
        direct_profiles=[],
        auto_match_when_empty=False,
    )
    assert not _should_use_all_library_profiles_when_unconstrained(
        selected_ids=[],
        direct_profiles=[{"id": "scene-1", "name": "教室"}],
        auto_match_when_empty=False,
    )
