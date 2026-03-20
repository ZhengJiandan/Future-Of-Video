import json
import shutil
import subprocess
from pathlib import Path

import pytest

from app.core.config import settings
from app.services.audio_renderer import ProjectAudioRenderer


def _build_silent_video(output_path: Path, *, duration: float) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        pytest.skip("ffmpeg not installed")

    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=640x360:r=24",
            "-t",
            f"{duration:.3f}",
            "-pix_fmt",
            "yuv420p",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _build_tone_audio(output_path: Path, *, duration: float, frequency: int) -> None:
    ffmpeg_path = shutil.which("ffmpeg")
    if not ffmpeg_path:
        pytest.skip("ffmpeg not installed")

    subprocess.run(
        [
            ffmpeg_path,
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency={frequency}:sample_rate=48000",
            "-t",
            f"{duration:.3f}",
            "-ac",
            "2",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


@pytest.mark.asyncio
@pytest.mark.unit
async def test_project_audio_renderer_generates_muxed_video_with_mock_layers(tmp_path: Path) -> None:
    for method_name in [
        "_concat_layer",
        "_mix_layers",
        "_pad_or_trim_audio",
        "_mux_video_and_audio",
        "_probe_media_duration",
    ]:
        assert hasattr(ProjectAudioRenderer, method_name), f"missing renderer method: {method_name}"

    video_path = tmp_path / "input.mp4"
    _build_silent_video(video_path, duration=2.4)

    renderer = ProjectAudioRenderer(
        output_dir=str(tmp_path / "render"),
        tts_provider="mock-silent",
        sfx_provider="mock-silent",
        ambience_provider="mock-silent",
        music_provider="mock-silent",
    )
    result = await renderer.render_project_audio(
        video_path=str(video_path),
        audio_plan={
            "strategy": "external_audio_pipeline",
            "segment_audio_plan": [
                {
                    "segment_number": 1,
                    "title": "片段一",
                    "duration": 1.2,
                    "dialogue_lines": [
                        {"speaker_name": "甲", "text": "第一句台词"},
                        {"speaker_name": "乙", "text": "第二句台词"},
                    ],
                    "sound_effects": ["脚步"],
                    "ambience": "街道环境音",
                    "music_direction": "轻微铺底",
                },
                {
                    "segment_number": 2,
                    "title": "片段二",
                    "duration": 1.2,
                    "dialogue_lines": [
                        {"speaker_name": "甲", "text": "收尾台词"},
                    ],
                    "sound_effects": ["风声"],
                    "ambience": "室内底噪",
                    "music_direction": "继续维持",
                },
            ],
        },
        project_title="audio renderer smoke",
        output_basename="audio_renderer_smoke",
        expected_duration=2.4,
    )

    manifest_path = Path(result["manifest_path"])
    master_audio_path = Path(result["master_audio_path"])
    muxed_video_path = Path(result["muxed_video_path"])

    assert result["status"] == "completed"
    assert manifest_path.exists()
    assert master_audio_path.exists()
    assert muxed_video_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["providers"] == {
        "dialogue": "mock-silent",
        "sfx": "mock-silent",
        "ambience": "mock-silent",
        "music": "mock-silent",
    }
    assert len(manifest["segments"]) == 2
    assert manifest["muxed_video"] == str(muxed_video_path)


@pytest.mark.asyncio
@pytest.mark.unit
async def test_project_audio_renderer_uses_local_library_assets(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    library_root = tmp_path / "audio_library"
    (library_root / "sfx").mkdir(parents=True, exist_ok=True)
    (library_root / "ambience").mkdir(parents=True, exist_ok=True)
    (library_root / "music").mkdir(parents=True, exist_ok=True)

    footstep_path = library_root / "sfx" / "footstep_soft.wav"
    ambience_path = library_root / "ambience" / "city_street_day.wav"
    music_path = library_root / "music" / "light_tension_pad.wav"
    _build_tone_audio(footstep_path, duration=0.4, frequency=880)
    _build_tone_audio(ambience_path, duration=0.8, frequency=330)
    _build_tone_audio(music_path, duration=0.8, frequency=220)

    manifest_path = library_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "entries": [
                    {
                        "kind": "sfx",
                        "path": "sfx/footstep_soft.wav",
                        "label": "脚步",
                        "tags": ["脚步", "走路", "footstep"],
                        "gain": 0.9,
                    },
                    {
                        "kind": "ambience",
                        "path": "ambience/city_street_day.wav",
                        "label": "城市街道白天",
                        "tags": ["街道", "城市", "环境音"],
                        "gain": 0.7,
                        "default": True,
                    },
                    {
                        "kind": "music",
                        "path": "music/light_tension_pad.wav",
                        "label": "轻微紧张铺底",
                        "tags": ["紧张", "铺底", "悬疑", "配乐"],
                        "gain": 0.6,
                        "default": True,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(settings, "AUDIO_LIBRARY_ROOT", str(library_root))
    monkeypatch.setattr(settings, "AUDIO_LIBRARY_MANIFEST", str(manifest_path))

    video_path = tmp_path / "input.mp4"
    _build_silent_video(video_path, duration=1.5)

    renderer = ProjectAudioRenderer(
        output_dir=str(tmp_path / "render"),
        tts_provider="mock-silent",
        sfx_provider="local-library",
        ambience_provider="local-library",
        music_provider="local-library",
    )
    result = await renderer.render_project_audio(
        video_path=str(video_path),
        audio_plan={
            "strategy": "external_audio_pipeline",
            "segment_audio_plan": [
                {
                    "segment_number": 1,
                    "title": "片段一",
                    "duration": 1.5,
                    "dialogue_lines": [
                        {"speaker_name": "甲", "text": "对白测试"},
                    ],
                    "sound_effects": ["脚步"],
                    "ambience": "城市街道环境音",
                    "music_direction": "轻微紧张铺底",
                }
            ],
        },
        project_title="audio library smoke",
        output_basename="audio_library_smoke",
        expected_duration=1.5,
    )

    manifest = json.loads(Path(result["manifest_path"]).read_text(encoding="utf-8"))
    assert result["status"] == "completed"
    assert manifest["providers"]["sfx"] == "local-library"
    assert manifest["providers"]["ambience"] == "local-library"
    assert manifest["providers"]["music"] == "local-library"
    assert Path(manifest["layer_outputs"]["sfx"]).exists()
    assert Path(manifest["layer_outputs"]["ambience"]).exists()
    assert Path(manifest["layer_outputs"]["music"]).exists()
