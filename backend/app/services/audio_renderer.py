#!/usr/bin/env python3
"""
项目级音频渲染与混音服务。

当前实现目标：
1. 消化 pipeline_workflow 生成的 audio_plan
2. 产出项目级音频 manifest
3. 生成可回退的分层音频资产（当前默认 mock-silent）
4. 通过 FFmpeg 完成混音和 mux

真正的供应商接入会在后续 provider 子类中补齐。当前先把
"音频执行层" 的结构和最终成片输出打通，避免只有规划、没有执行。
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import tempfile
import uuid
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from app.core.config import settings


@dataclass
class AudioCue:
    kind: str
    segment_number: int
    start_time: float
    duration: float
    label: str
    provider: str
    prompt: str = ""
    text: str = ""
    character_name: str = ""
    voice_profile: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AudioLayerAsset:
    kind: str
    segment_number: Optional[int]
    provider: str
    duration: float
    path: str
    prompt: str = ""


@dataclass
class AudioSegmentRender:
    segment_number: int
    title: str
    start_time: float
    duration: float
    cues: List[AudioCue] = field(default_factory=list)
    layer_assets: List[AudioLayerAsset] = field(default_factory=list)


@dataclass
class AudioLibraryAsset:
    kind: str
    path: Path
    tags: List[str] = field(default_factory=list)
    label: str = ""
    gain: float = 1.0
    is_default: bool = False


class LocalAudioLibrary:
    AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".ogg", ".flac"}
    AUDIO_KINDS = ("sfx", "ambience", "music")
    LOW_SIGNAL_TAGS = {
        "ambience": {"环境音", "ambient", "loop", "tone", "room", "底噪"},
        "music": {"氛围", "铺底"},
        "sfx": set(),
    }
    SETTING_TAGS = {
        "赛博",
        "科幻",
        "太空",
        "城堡",
        "废弃",
        "东方",
        "古风",
        "寒冬",
        "winter",
        "space",
        "castle",
        "abandoned",
        "cyberworld",
    }
    PROMPT_HINTS = {
        "ambience": {
            "后院": ["庭院", "院子", "户外"],
            "院内": ["庭院", "院子", "户外"],
            "雨后": ["风声", "户外", "庭院"],
            "便利店": ["便利店", "商店", "冰柜", "fridge", "shop", "室内"],
            "店内": ["商店", "室内", "冰柜", "shop", "fridge"],
            "药铺": ["商店", "室内"],
            "室内": ["室内", "内景", "room", "interior"],
            "悬疑": ["悬疑", "紧张", "压迫", "dark", "tension"],
            "危险": ["紧张", "压迫", "tension"],
            "昏暗": ["暗场", "dark"],
        },
        "music": {
            "悬疑": ["悬疑", "紧张", "压迫", "tension"],
            "危险": ["紧张", "压迫", "tension"],
            "克制": ["压抑"],
            "安静": ["温柔", "舒缓"],
            "悲伤": ["悲伤", "低落", "沉思", "sad"],
            "古风": ["古风", "东方", "oriental"],
            "昏暗": ["压抑", "悬疑"],
        },
        "sfx": {
            "潜行": ["脚步", "走路", "摩擦", "rustle"],
            "贴地": ["脚步", "摩擦"],
            "落地": ["落地", "landing", "脚步"],
            "转身": ["转身", "摩擦", "rustle"],
            "扑": ["落地", "碰撞", "hit"],
            "打斗": ["打斗", "碰撞", "击中", "fight", "hit"],
            "对峙": ["打斗", "碰撞", "fight"],
            "碰撞": ["碰撞", "击中", "hit"],
            "脚步": ["脚步", "走路", "footstep"],
        },
    }
    MIN_SCORE_BY_KIND = {
        "ambience": 2,
        "music": 2,
        "sfx": 2,
    }

    def __init__(self, *, root_dir: Path, manifest_path: Optional[Path] = None) -> None:
        self.root_dir = Path(root_dir)
        self.manifest_path = Path(manifest_path) if manifest_path else self.root_dir / "manifest.json"
        self.root_dir.mkdir(parents=True, exist_ok=True)
        for kind in self.AUDIO_KINDS:
            (self.root_dir / kind).mkdir(parents=True, exist_ok=True)
        self.entries_by_kind = self._load_entries()

    def match_asset(self, *, kind: str, prompt: str) -> Optional[AudioLibraryAsset]:
        entries = list(self.entries_by_kind.get(kind) or [])
        if not entries:
            return None

        normalized_prompt = self._normalize_text(prompt)
        prompt_terms = self._build_prompt_terms(kind=kind, normalized_prompt=normalized_prompt)
        scored = sorted(
            entries,
            key=lambda item: (
                self._score_entry(
                    item=item,
                    kind=kind,
                    normalized_prompt=normalized_prompt,
                    prompt_terms=prompt_terms,
                ),
                1 if item.is_default else 0,
                len(item.tags),
                item.label,
            ),
            reverse=True,
        )
        if not scored:
            return None

        best = scored[0]
        best_score = self._score_entry(
            item=best,
            kind=kind,
            normalized_prompt=normalized_prompt,
            prompt_terms=prompt_terms,
        )
        if best_score < self.MIN_SCORE_BY_KIND.get(kind, 1):
            return None
        return best

    def _load_entries(self) -> Dict[str, List[AudioLibraryAsset]]:
        entries_by_kind: Dict[str, List[AudioLibraryAsset]] = {kind: [] for kind in self.AUDIO_KINDS}

        if self.manifest_path.exists():
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            for raw_item in payload.get("entries") or []:
                if not isinstance(raw_item, dict):
                    continue
                kind = str(raw_item.get("kind") or "").strip().lower()
                if kind not in entries_by_kind:
                    continue
                path_value = str(raw_item.get("path") or "").strip()
                if not path_value:
                    continue
                asset_path = Path(path_value)
                if not asset_path.is_absolute():
                    asset_path = self.root_dir / asset_path
                if not asset_path.exists() or asset_path.suffix.lower() not in self.AUDIO_EXTENSIONS:
                    continue
                tags = [str(item).strip() for item in (raw_item.get("tags") or []) if str(item).strip()]
                label = str(raw_item.get("label") or asset_path.stem).strip() or asset_path.stem
                entries_by_kind[kind].append(
                    AudioLibraryAsset(
                        kind=kind,
                        path=asset_path,
                        tags=tags or self._derive_tags(asset_path),
                        label=label,
                        gain=self._bounded_gain(raw_item.get("gain")),
                        is_default=bool(raw_item.get("default")),
                    )
                )

        for kind in self.AUDIO_KINDS:
            if entries_by_kind[kind]:
                continue
            entries_by_kind[kind].extend(self._scan_kind_directory(kind))

        return entries_by_kind

    def _scan_kind_directory(self, kind: str) -> List[AudioLibraryAsset]:
        kind_dir = self.root_dir / kind
        if not kind_dir.exists():
            return []

        scanned: List[AudioLibraryAsset] = []
        for path in sorted(kind_dir.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in self.AUDIO_EXTENSIONS:
                continue
            scanned.append(
                AudioLibraryAsset(
                    kind=kind,
                    path=path,
                    tags=self._derive_tags(path),
                    label=path.stem,
                )
            )
        return scanned

    def _derive_tags(self, path: Path) -> List[str]:
        parts = [path.stem]
        try:
            relative_parent = path.parent.relative_to(self.root_dir)
            parts.extend(relative_parent.parts)
        except ValueError:
            parts.extend(path.parent.parts[-2:])
        tags: List[str] = []
        for part in parts:
            normalized_part = str(part or "").strip()
            if not normalized_part:
                continue
            tags.append(normalized_part)
            tags.extend(token for token in re.split(r"[_\-\s]+", normalized_part) if token)
        unique_tags: List[str] = []
        for item in tags:
            if item and item not in unique_tags:
                unique_tags.append(item)
        return unique_tags

    def _score_entry(
        self,
        *,
        item: AudioLibraryAsset,
        kind: str,
        normalized_prompt: str,
        prompt_terms: set[str],
    ) -> int:
        score = 0
        if not normalized_prompt:
            return 1 if item.is_default else 0

        label = self._normalize_text(item.label)
        if label and label in prompt_terms:
            score += 4

        stem = self._normalize_text(item.path.stem)
        if stem and stem in prompt_terms:
            score += 3

        for tag in item.tags:
            normalized_tag = self._normalize_text(tag)
            if not normalized_tag:
                continue
            if normalized_tag in self._low_signal_tags_for_kind(kind):
                continue
            if normalized_tag in prompt_terms:
                score += 2 if len(normalized_tag) <= 2 else 3
                continue
            if normalized_tag in self._setting_tags() and normalized_tag not in prompt_terms:
                score -= 2
        if item.is_default and score > 0:
            score += 1
        return score

    def _normalize_text(self, value: str) -> str:
        return re.sub(r"[\s_\-./|]+", "", str(value or "").strip().lower())

    def _build_prompt_terms(self, *, kind: str, normalized_prompt: str) -> set[str]:
        terms = {normalized_prompt} if normalized_prompt else set()
        for raw_hint, aliases in self.PROMPT_HINTS.get(kind, {}).items():
            normalized_hint = self._normalize_text(raw_hint)
            if normalized_hint and normalized_hint in normalized_prompt:
                terms.add(normalized_hint)
                for alias in aliases:
                    normalized_alias = self._normalize_text(alias)
                    if normalized_alias:
                        terms.add(normalized_alias)
        return terms

    def _low_signal_tags_for_kind(self, kind: str) -> set[str]:
        return {
            self._normalize_text(tag)
            for tag in self.LOW_SIGNAL_TAGS.get(kind, set())
            if self._normalize_text(tag)
        }

    def _setting_tags(self) -> set[str]:
        return {
            self._normalize_text(tag)
            for tag in self.SETTING_TAGS
            if self._normalize_text(tag)
        }

    def _bounded_gain(self, value: Any) -> float:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return 1.0
        return max(0.1, min(normalized, 3.0))


class BaseAudioProvider(ABC):
    def __init__(self, *, ffmpeg_path: str, sample_rate: int, channels: int) -> None:
        self.ffmpeg_path = ffmpeg_path
        self.sample_rate = sample_rate
        self.channels = channels

    @property
    @abstractmethod
    def name(self) -> str:
        raise NotImplementedError

    @abstractmethod
    async def render_segment_layer(
        self,
        *,
        output_path: Path,
        duration: float,
        kind: str,
        prompt: str,
        segment_number: int,
        segment: Dict[str, Any],
        cues: List[AudioCue],
    ) -> None:
        raise NotImplementedError

    async def _run_ffmpeg(self, args: List[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise RuntimeError(stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore"))


class MockSilentAudioProvider(BaseAudioProvider):
    @property
    def name(self) -> str:
        return "mock-silent"

    async def render_segment_layer(
        self,
        *,
        output_path: Path,
        duration: float,
        kind: str,
        prompt: str,
        segment_number: int,
        segment: Dict[str, Any],
        cues: List[AudioCue],
    ) -> None:
        del kind, prompt, segment_number, segment, cues
        await self._render_silence(output_path=output_path, duration=duration)

    async def _render_silence(self, *, output_path: Path, duration: float) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        duration = max(float(duration or 0.0), 0.05)
        channel_layout = "mono" if int(self.channels or 2) == 1 else "stereo"
        await self._run_ffmpeg(
            [
                self.ffmpeg_path,
                "-y",
                "-f",
                "lavfi",
                "-i",
                f"anullsrc=r={self.sample_rate}:cl={channel_layout}",
                "-t",
                f"{duration:.3f}",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
        )


class DoubaoTTSProvider(MockSilentAudioProvider):
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        sample_rate: int,
        channels: int,
        app_id: str,
        access_token: str,
        cluster: str,
        api_url: str,
        default_voice_type: str,
    ) -> None:
        super().__init__(ffmpeg_path=ffmpeg_path, sample_rate=sample_rate, channels=channels)
        self.app_id = app_id
        self.access_token = access_token
        self.cluster = cluster
        self.api_url = api_url
        self.default_voice_type = default_voice_type

    @property
    def name(self) -> str:
        return "doubao-tts"

    async def render_segment_layer(
        self,
        *,
        output_path: Path,
        duration: float,
        kind: str,
        prompt: str,
        segment_number: int,
        segment: Dict[str, Any],
        cues: List[AudioCue],
    ) -> None:
        del prompt, segment
        if kind != "dialogue" or not cues:
            await self._render_silence(output_path=output_path, duration=duration)
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        cue_assets: List[tuple[AudioCue, Path]] = []
        for index, cue in enumerate(cues):
            text = str(cue.text or cue.label).strip()
            if not text:
                continue
            cue_path = output_path.parent / f"dialogue_cue_{segment_number:02d}_{index + 1:02d}.wav"
            await self._synthesize_cue_to_wav(
                text=text,
                cue=cue,
                output_path=cue_path,
            )
            cue_assets.append((cue, cue_path))

        if not cue_assets:
            await self._render_silence(output_path=output_path, duration=duration)
            return

        base_path = output_path.parent / f"dialogue_base_{segment_number:02d}.wav"
        await self._render_silence(output_path=base_path, duration=duration)
        try:
            await self._overlay_cues_on_base(
                base_path=base_path,
                cue_assets=cue_assets,
                output_path=output_path,
            )
        finally:
            base_path.unlink(missing_ok=True)

    async def _synthesize_cue_to_wav(
        self,
        *,
        text: str,
        cue: AudioCue,
        output_path: Path,
    ) -> None:
        voice_profile = dict(cue.voice_profile or {})
        voice_type = str(voice_profile.get("voice_type") or self.default_voice_type or "").strip()
        if not voice_type:
            raise RuntimeError(
                f"Doubao TTS 缺少 voice_type，角色 `{cue.character_name or 'unknown'}` 未配置 voice_profile.voice_type，"
                "且 DOUBAO_TTS_DEFAULT_VOICE_TYPE 也为空"
            )

        audio_config: Dict[str, Any] = {
            "voice_type": voice_type,
            "encoding": "wav",
            "speed_ratio": self._bounded_ratio(voice_profile.get("speed_ratio"), fallback=1.0),
            "pitch_ratio": self._bounded_ratio(voice_profile.get("pitch_ratio"), fallback=1.0),
            "volume_ratio": self._bounded_ratio(voice_profile.get("volume_ratio"), fallback=1.0),
        }
        emotion = str(voice_profile.get("emotion") or "").strip()
        language = str(voice_profile.get("language") or "").strip()
        if emotion:
            audio_config["emotion"] = emotion
        if language:
            audio_config["language"] = language

        payload = {
            "app": {
                "appid": self.app_id,
                "token": self.access_token,
                "cluster": self.cluster,
            },
            "user": {
                "uid": cue.character_name or f"segment-{cue.segment_number}",
            },
            "audio": audio_config,
            "request": {
                "reqid": uuid.uuid4().hex,
                "text": text,
                "text_type": "plain",
                "operation": "query",
                "with_frontend": 1,
                "frontend_type": "unitTson",
            },
        }

        headers = {
            "Authorization": f"Bearer;{self.access_token}",
            "Content-Type": "application/json",
        }
        timeout = httpx.Timeout(connect=20.0, read=120.0, write=60.0, pool=60.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(self.api_url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()

        audio_b64 = str(data.get("data") or "").strip()
        if not audio_b64:
            raise RuntimeError(f"Doubao TTS 未返回音频数据: {json.dumps(data, ensure_ascii=False)[:400]}")

        output_path.write_bytes(base64.b64decode(audio_b64))

    async def synthesize_text_to_wav(
        self,
        *,
        text: str,
        character_name: str,
        voice_profile: Dict[str, Any],
        output_path: Path,
        segment_number: int = 0,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._synthesize_cue_to_wav(
            text=str(text or "").strip(),
            cue=AudioCue(
                kind="dialogue",
                segment_number=segment_number,
                start_time=0.0,
                duration=0.0,
                label=str(text or "").strip(),
                provider=self.name,
                prompt=str(text or "").strip(),
                text=str(text or "").strip(),
                character_name=str(character_name or "").strip(),
                voice_profile=dict(voice_profile or {}),
            ),
            output_path=output_path,
        )

    async def _overlay_cues_on_base(
        self,
        *,
        base_path: Path,
        cue_assets: List[tuple[AudioCue, Path]],
        output_path: Path,
    ) -> None:
        cmd = [self.ffmpeg_path, "-y", "-i", str(base_path)]
        filter_parts: List[str] = []
        mix_inputs = ["[0:a]"]

        for index, (cue, cue_path) in enumerate(cue_assets, start=1):
            delay_ms = max(int(round(max(float(cue.start_time or 0.0), 0.0) * 1000)), 0)
            cmd.extend(["-i", str(cue_path)])
            delayed_label = f"[d{index}]"
            filter_parts.append(
                f"[{index}:a]adelay={delay_ms}|{delay_ms},aresample={self.sample_rate}{delayed_label}"
            )
            mix_inputs.append(delayed_label)

        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0,alimiter=limit=0.95[out]"
        )
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[out]",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
        )
        await self._run_ffmpeg(cmd)

    def _bounded_ratio(self, value: Any, *, fallback: float) -> float:
        try:
            normalized = float(value)
        except (TypeError, ValueError):
            return fallback
        return max(0.2, min(normalized, 3.0))


class LocalLibraryAudioProvider(MockSilentAudioProvider):
    def __init__(
        self,
        *,
        ffmpeg_path: str,
        sample_rate: int,
        channels: int,
        kind: str,
        library: LocalAudioLibrary,
        warnings_sink: List[str],
    ) -> None:
        super().__init__(ffmpeg_path=ffmpeg_path, sample_rate=sample_rate, channels=channels)
        self.kind = kind
        self.library = library
        self.warnings_sink = warnings_sink

    @property
    def name(self) -> str:
        return "local-library"

    async def render_segment_layer(
        self,
        *,
        output_path: Path,
        duration: float,
        kind: str,
        prompt: str,
        segment_number: int,
        segment: Dict[str, Any],
        cues: List[AudioCue],
    ) -> None:
        del segment
        if kind == "sfx":
            await self._render_sfx_layer(
                output_path=output_path,
                duration=duration,
                prompt=prompt,
                segment_number=segment_number,
                cues=cues,
            )
            return

        asset = self.library.match_asset(kind=kind, prompt=prompt)
        if asset is None:
            self._push_warning(f"{kind} 未匹配到本地素材，已回退到静音。prompt={prompt or 'empty'}")
            await self._render_silence(output_path=output_path, duration=duration)
            return
        await self._render_looped_asset(
            asset=asset,
            output_path=output_path,
            duration=duration,
        )

    async def _render_sfx_layer(
        self,
        *,
        output_path: Path,
        duration: float,
        prompt: str,
        segment_number: int,
        cues: List[AudioCue],
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        base_path = output_path.parent / f"sfx_base_{segment_number:02d}.wav"
        await self._render_silence(output_path=base_path, duration=duration)

        cue_assets: List[tuple[AudioCue, Path]] = []
        try:
            for index, cue in enumerate(cues):
                asset = self.library.match_asset(kind="sfx", prompt=cue.prompt or cue.label or prompt)
                if asset is None:
                    self._push_warning(
                        f"sfx cue 未匹配到本地素材，已跳过。segment={segment_number} prompt={cue.prompt or cue.label or prompt or 'empty'}"
                    )
                    continue
                cue_path = output_path.parent / f"sfx_cue_{segment_number:02d}_{index + 1:02d}.wav"
                await self._render_looped_asset(
                    asset=asset,
                    output_path=cue_path,
                    duration=max(float(cue.duration or 0.0), 0.05),
                )
                cue_assets.append((cue, cue_path))

            if not cue_assets:
                await self._render_silence(output_path=output_path, duration=duration)
                return

            await self._overlay_assets_on_base(
                base_path=base_path,
                cue_assets=cue_assets,
                output_path=output_path,
            )
        finally:
            base_path.unlink(missing_ok=True)
            for _, cue_path in cue_assets:
                cue_path.unlink(missing_ok=True)

    async def _render_looped_asset(
        self,
        *,
        asset: AudioLibraryAsset,
        output_path: Path,
        duration: float,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            self.ffmpeg_path,
            "-y",
            "-stream_loop",
            "-1",
            "-i",
            str(asset.path),
            "-t",
            f"{max(float(duration or 0.0), 0.05):.3f}",
            "-ar",
            str(self.sample_rate),
            "-ac",
            str(self.channels),
        ]
        if abs(asset.gain - 1.0) > 0.001:
            cmd.extend(["-af", f"volume={asset.gain:.3f}"])
        cmd.extend(["-c:a", "pcm_s16le", str(output_path)])
        await self._run_ffmpeg(cmd)

    async def _overlay_assets_on_base(
        self,
        *,
        base_path: Path,
        cue_assets: List[tuple[AudioCue, Path]],
        output_path: Path,
    ) -> None:
        cmd = [self.ffmpeg_path, "-y", "-i", str(base_path)]
        filter_parts: List[str] = []
        mix_inputs = ["[0:a]"]

        for index, (cue, cue_path) in enumerate(cue_assets, start=1):
            delay_ms = max(int(round(max(float(cue.start_time or 0.0), 0.0) * 1000)), 0)
            cmd.extend(["-i", str(cue_path)])
            delayed_label = f"[d{index}]"
            filter_parts.append(
                f"[{index}:a]adelay={delay_ms}|{delay_ms},aresample={self.sample_rate}{delayed_label}"
            )
            mix_inputs.append(delayed_label)

        filter_parts.append(
            f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0,alimiter=limit=0.95[out]"
        )
        cmd.extend(
            [
                "-filter_complex",
                ";".join(filter_parts),
                "-map",
                "[out]",
                "-c:a",
                "pcm_s16le",
                str(output_path),
            ]
        )
        await self._run_ffmpeg(cmd)

    def _push_warning(self, message: str) -> None:
        if message not in self.warnings_sink:
            self.warnings_sink.append(message)


class ProjectAudioRenderer:
    def __init__(
        self,
        *,
        output_dir: str,
        sample_rate: int = 48000,
        channels: int = 2,
        master_codec: str = "aac",
        master_bitrate: str = "192k",
        tts_provider: str = "mock-silent",
        sfx_provider: str = "mock-silent",
        ambience_provider: str = "mock-silent",
        music_provider: str = "mock-silent",
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.sample_rate = sample_rate
        self.channels = channels
        self.master_codec = master_codec
        self.master_bitrate = master_bitrate
        self.ffmpeg_path = shutil.which("ffmpeg")
        self.ffprobe_path = shutil.which("ffprobe")
        self.provider_warnings: List[str] = []
        if not self.ffmpeg_path:
            raise RuntimeError("FFmpeg 未安装，无法执行项目级音频渲染")

        self.providers = {
            "dialogue": self._build_provider(tts_provider, kind="对白"),
            "sfx": self._build_provider(sfx_provider, kind="音效"),
            "ambience": self._build_provider(ambience_provider, kind="环境"),
            "music": self._build_provider(music_provider, kind="配乐"),
        }

    async def render_project_audio(
        self,
        *,
        video_path: str,
        audio_plan: Dict[str, Any],
        project_title: str,
        output_basename: str,
        expected_duration: Optional[float] = None,
    ) -> Dict[str, Any]:
        strategy = str(audio_plan.get("strategy") or "external_audio_pipeline")
        segment_plans = list(audio_plan.get("segment_audio_plan") or [])
        if not segment_plans:
            return {
                "status": "skipped",
                "reason": "audio_plan_empty",
                "strategy": strategy,
                "warnings": ["audio_plan 不包含 segment_audio_plan，已跳过项目级音频渲染。"],
            }

        video_duration = expected_duration or await self._probe_media_duration(video_path)
        if not video_duration:
            video_duration = sum(max(float(segment.get("duration") or 0.0), 0.0) for segment in segment_plans)

        working_root = self.output_dir / "audio"
        segments_root = working_root / "segments"
        layers_root = working_root / "layers"
        for path in (working_root, segments_root, layers_root):
            path.mkdir(parents=True, exist_ok=True)

        segment_renders = await self._render_segment_layers(
            segment_plans=segment_plans,
            segments_root=segments_root,
        )

        dialogue_path = await self._concat_layer(
            [asset.path for render in segment_renders for asset in render.layer_assets if asset.kind == "dialogue"],
            layers_root / f"{output_basename}_dialogue.wav",
        )
        ambience_path = await self._concat_layer(
            [asset.path for render in segment_renders for asset in render.layer_assets if asset.kind == "ambience"],
            layers_root / f"{output_basename}_ambience.wav",
        )
        music_path = await self._concat_layer(
            [asset.path for render in segment_renders for asset in render.layer_assets if asset.kind == "music"],
            layers_root / f"{output_basename}_music.wav",
        )
        sfx_path = await self._concat_layer(
            [asset.path for render in segment_renders for asset in render.layer_assets if asset.kind == "sfx"],
            layers_root / f"{output_basename}_sfx.wav",
        )

        master_raw_path = working_root / f"{output_basename}_master_raw.m4a"
        await self._mix_layers(
            dialogue_path=dialogue_path,
            ambience_path=ambience_path,
            music_path=music_path,
            sfx_path=sfx_path,
            output_path=master_raw_path,
        )

        master_path = working_root / f"{output_basename}_master.m4a"
        await self._pad_or_trim_audio(
            input_path=master_raw_path,
            output_path=master_path,
            target_duration=max(float(video_duration or 0.0), 0.05),
        )

        muxed_video_path = self.output_dir / f"{output_basename}_with_audio.mp4"
        await self._mux_video_and_audio(
            video_path=Path(video_path),
            audio_path=master_path,
            output_path=muxed_video_path,
        )

        manifest_path = working_root / f"{output_basename}_audio_manifest.json"
        manifest = {
            "project_title": project_title or "未命名项目",
            "strategy": strategy,
            "status": "completed",
            "duration": round(float(video_duration or 0.0), 3),
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "providers": {kind: provider.name for kind, provider in self.providers.items()},
            "segments": [self._segment_render_to_manifest(render) for render in segment_renders],
            "layer_outputs": {
                "dialogue": str(dialogue_path),
                "ambience": str(ambience_path),
                "music": str(music_path),
                "sfx": str(sfx_path),
            },
            "master_audio": str(master_path),
            "muxed_video": str(muxed_video_path),
            "warnings": list(dict.fromkeys(self.provider_warnings)),
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "status": "completed",
            "strategy": strategy,
            "duration": round(float(video_duration or 0.0), 3),
            "providers": manifest["providers"],
            "manifest_path": str(manifest_path),
            "master_audio_path": str(master_path),
            "muxed_video_path": str(muxed_video_path),
            "segment_count": len(segment_renders),
            "warnings": manifest["warnings"],
        }

    def _build_provider(self, provider_name: str, *, kind: str) -> BaseAudioProvider:
        normalized = str(provider_name or "mock-silent").strip().lower()
        if normalized in {"", "mock", "mock-silent", "silent", "noop"}:
            return MockSilentAudioProvider(
                ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                sample_rate=self.sample_rate,
                channels=self.channels,
            )
        if normalized in {"local-library", "library", "local-assets"}:
            if kind == "对白":
                self.provider_warnings.append(
                    f"{kind} provider `{provider_name}` 当前不支持本地素材库，已自动回退到 mock-silent。"
                )
                return MockSilentAudioProvider(
                    ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                )

            library_root = Path(
                str(settings.AUDIO_LIBRARY_ROOT or Path(settings.UPLOAD_DIR) / "generated" / "pipeline" / "audio_library")
            )
            manifest_value = str(settings.AUDIO_LIBRARY_MANIFEST or "").strip()
            manifest_path = Path(manifest_value) if manifest_value else None
            try:
                library = LocalAudioLibrary(root_dir=library_root, manifest_path=manifest_path)
            except Exception as exc:
                self.provider_warnings.append(
                    f"{kind} provider `{provider_name}` 加载本地素材库失败，已自动回退到 mock-silent。error={exc}"
                )
                return MockSilentAudioProvider(
                    ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                )
            return LocalLibraryAudioProvider(
                ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                sample_rate=self.sample_rate,
                channels=self.channels,
                kind=kind,
                library=library,
                warnings_sink=self.provider_warnings,
            )
        if normalized in {"doubao", "doubao-tts", "volcengine", "bytedance"}:
            if kind != "对白":
                self.provider_warnings.append(
                    f"{kind} provider `{provider_name}` 当前未实现，已自动回退到 mock-silent。"
                )
                return MockSilentAudioProvider(
                    ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                )

            app_id = str(settings.DOUBAO_TTS_APP_ID or "").strip()
            access_token = str(settings.DOUBAO_TTS_ACCESS_TOKEN or "").strip()
            cluster = str(settings.DOUBAO_TTS_CLUSTER or "volcano_tts").strip()
            api_url = str(settings.DOUBAO_TTS_API_URL or "https://openspeech.bytedance.com/api/v1/tts").strip()
            default_voice_type = str(settings.DOUBAO_TTS_DEFAULT_VOICE_TYPE or "").strip()
            if not app_id or not access_token:
                self.provider_warnings.append(
                    f"{kind} provider `{provider_name}` 缺少 DOUBAO_TTS_APP_ID / DOUBAO_TTS_ACCESS_TOKEN，已回退到 mock-silent。"
                )
                return MockSilentAudioProvider(
                    ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                    sample_rate=self.sample_rate,
                    channels=self.channels,
                )
            return DoubaoTTSProvider(
                ffmpeg_path=self.ffmpeg_path or "ffmpeg",
                sample_rate=self.sample_rate,
                channels=self.channels,
                app_id=app_id,
                access_token=access_token,
                cluster=cluster,
                api_url=api_url,
                default_voice_type=default_voice_type,
            )

        self.provider_warnings.append(
            f"{kind} provider `{provider_name}` 当前未实现，已自动回退到 mock-silent。"
        )
        return MockSilentAudioProvider(
            ffmpeg_path=self.ffmpeg_path or "ffmpeg",
            sample_rate=self.sample_rate,
            channels=self.channels,
        )

    async def _render_segment_layers(
        self,
        *,
        segment_plans: List[Dict[str, Any]],
        segments_root: Path,
    ) -> List[AudioSegmentRender]:
        segment_renders: List[AudioSegmentRender] = []
        cursor = 0.0

        for index, segment in enumerate(segment_plans):
            segment_number = int(segment.get("segment_number") or index + 1)
            duration = max(float(segment.get("duration") or 0.0), 0.05)
            title = str(segment.get("title") or f"片段 {segment_number}")
            segment_dir = segments_root / f"segment_{segment_number:02d}"
            segment_dir.mkdir(parents=True, exist_ok=True)

            render = AudioSegmentRender(
                segment_number=segment_number,
                title=title,
                start_time=round(cursor, 3),
                duration=duration,
            )

            cue_map = self._build_segment_cues(segment=segment, segment_start=cursor, duration=duration)
            for cues in cue_map.values():
                render.cues.extend(cues)

            dialogue_prompt_items = [
                self._dialogue_line_display_text(item, include_character_id=True)
                for item in self._normalize_dialogue_lines(segment.get("dialogue_lines") or [])
            ]
            prompt_map = {
                "dialogue": self._join_non_empty(
                    [
                        "；".join(item for item in dialogue_prompt_items if item),
                        "；".join(str(item).strip() for item in (segment.get("dialogue_focus") or []) if str(item).strip()),
                        self._voice_tracks_prompt(segment),
                    ]
                ),
                "sfx": "；".join(str(item).strip() for item in (segment.get("sound_effects") or []) if str(item).strip()),
                "ambience": str(segment.get("ambience") or "").strip(),
                "music": str(segment.get("music_direction") or "").strip(),
            }

            for kind in ("dialogue", "ambience", "music", "sfx"):
                provider = self.providers[kind]
                output_path = segment_dir / f"{kind}.wav"
                await provider.render_segment_layer(
                    output_path=output_path,
                    duration=duration,
                    kind=kind,
                    prompt=prompt_map[kind],
                    segment_number=segment_number,
                    segment=segment,
                    cues=cue_map.get(kind) or [],
                )
                render.layer_assets.append(
                    AudioLayerAsset(
                        kind=kind,
                        segment_number=segment_number,
                        provider=provider.name,
                        duration=duration,
                        path=str(output_path),
                        prompt=prompt_map[kind],
                    )
                )

            segment_renders.append(render)
            cursor += duration

        return segment_renders

    def _build_segment_cues(
        self,
        *,
        segment: Dict[str, Any],
        segment_start: float,
        duration: float,
    ) -> Dict[str, List[AudioCue]]:
        del segment_start
        dialogue_items = self._normalize_dialogue_lines(segment.get("dialogue_lines") or [])
        if not dialogue_items:
            dialogue_items = self._normalize_dialogue_lines(segment.get("dialogue_focus") or [])
        sfx_items = [str(item).strip() for item in (segment.get("sound_effects") or []) if str(item).strip()]
        segment_number = int(segment.get("segment_number") or 0)
        voices = list(segment.get("voice_tracks") or [])

        cue_map: Dict[str, List[AudioCue]] = {
            "dialogue": [],
            "sfx": [],
            "ambience": [],
            "music": [],
        }

        cue_map["ambience"].append(
            AudioCue(
                kind="ambience",
                segment_number=segment_number,
                start_time=0.0,
                duration=duration,
                label=str(segment.get("ambience") or "环境层"),
                provider=self.providers["ambience"].name,
                prompt=str(segment.get("ambience") or "").strip(),
            )
        )
        cue_map["music"].append(
            AudioCue(
                kind="music",
                segment_number=segment_number,
                start_time=0.0,
                duration=duration,
                label=str(segment.get("music_direction") or "配乐层"),
                provider=self.providers["music"].name,
                prompt=str(segment.get("music_direction") or "").strip(),
            )
        )

        for index, dialogue in enumerate(dialogue_items):
            text = str(dialogue.get("text") or "").strip()
            if not text:
                continue
            estimated_duration = min(max(duration / max(len(dialogue_items), 1), 0.6), duration)
            max_offset = max(duration - estimated_duration, 0.0)
            offset = 0.0 if len(dialogue_items) == 1 else max_offset * (index / max(len(dialogue_items) - 1, 1))
            voice = self._match_voice_track(dialogue=dialogue, voices=voices) or (voices[index % len(voices)] if voices else {})
            voice_profile = dict((voice or {}).get("voice_profile") or {})
            dialogue_emotion = str(dialogue.get("emotion") or "").strip()
            if dialogue_emotion:
                voice_profile["emotion"] = dialogue_emotion
            cue_map["dialogue"].append(
                AudioCue(
                    kind="dialogue",
                    segment_number=segment_number,
                    start_time=round(offset, 3),
                    duration=round(estimated_duration, 3),
                    label=self._dialogue_line_display_text(dialogue, include_character_id=False) or text,
                    provider=self.providers["dialogue"].name,
                    prompt=self._dialogue_line_display_text(dialogue, include_character_id=True) or text,
                    text=text,
                    character_name=str(dialogue.get("speaker_name") or (voice or {}).get("name") or ""),
                    voice_profile=voice_profile,
                )
            )

        for index, text in enumerate(sfx_items):
            estimated_duration = min(max(duration / max(len(sfx_items) * 2, 1), 0.25), duration)
            max_offset = max(duration - estimated_duration, 0.0)
            offset = 0.0 if len(sfx_items) == 1 else max_offset * (index / max(len(sfx_items) - 1, 1))
            cue_map["sfx"].append(
                AudioCue(
                    kind="sfx",
                    segment_number=segment_number,
                    start_time=round(offset, 3),
                    duration=round(estimated_duration, 3),
                    label=text,
                    provider=self.providers["sfx"].name,
                    prompt=text,
                )
            )

        return cue_map

    def _normalize_lookup_key(self, value: str) -> str:
        return "".join(str(value or "").strip().lower().split())

    def _looks_like_character_id(self, value: str) -> bool:
        return bool(str(value or "").strip()) and bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{5,}", str(value or "").strip()))

    def _parse_dialogue_line_text(self, raw_value: Any) -> Dict[str, str]:
        raw_text = str(raw_value or "").strip()
        if not raw_text:
            return {}

        speaker_name = ""
        speaker_character_id = ""
        emotion = ""
        tone = ""
        text = raw_text

        prefix = ""
        content = ""
        for separator in ("：", ":"):
            if separator in raw_text:
                prefix, content = raw_text.split(separator, 1)
                break

        if prefix:
            bracket_values = re.findall(r"\[([^\]]+)\]", prefix)
            speaker_name = re.sub(r"\[[^\]]+\]", "", prefix).strip()
            text = content.strip()
            for item in bracket_values:
                normalized = str(item or "").strip()
                if not normalized:
                    continue
                if not speaker_character_id and self._looks_like_character_id(normalized):
                    speaker_character_id = normalized
                    continue
                labels = [part.strip() for part in re.split(r"\s*/\s*", normalized) if part.strip()]
                if labels and not emotion:
                    emotion = labels[0]
                if len(labels) >= 2 and not tone:
                    tone = labels[1]

        return {
            "text": text or raw_text,
            "speaker_name": speaker_name,
            "speaker_character_id": speaker_character_id,
            "emotion": emotion,
            "tone": tone,
        }

    def _normalize_dialogue_lines(self, value: Any) -> List[Dict[str, str]]:
        if isinstance(value, (str, dict)):
            iterable = [value]
        elif isinstance(value, (list, tuple)):
            iterable = list(value)
        else:
            iterable = []

        normalized: List[Dict[str, str]] = []
        for item in iterable:
            if isinstance(item, dict):
                line = {
                    "text": str(item.get("text") or "").strip(),
                    "speaker_name": str(item.get("speaker_name") or item.get("speaker") or "").strip(),
                    "speaker_character_id": str(item.get("speaker_character_id") or item.get("character_id") or "").strip(),
                    "emotion": str(item.get("emotion") or "").strip(),
                    "tone": str(item.get("tone") or "").strip(),
                }
            else:
                line = self._parse_dialogue_line_text(item)
            if line.get("text"):
                normalized.append(line)

        return normalized

    def _dialogue_line_display_text(
        self,
        dialogue: Dict[str, Any],
        *,
        include_character_id: bool,
    ) -> str:
        text = str(dialogue.get("text") or "").strip()
        speaker_name = str(dialogue.get("speaker_name") or "").strip()
        speaker_character_id = str(dialogue.get("speaker_character_id") or "").strip()
        labels = [part for part in [str(dialogue.get("emotion") or "").strip(), str(dialogue.get("tone") or "").strip()] if part]

        prefix = speaker_name
        if include_character_id and speaker_character_id:
            prefix = f"{prefix} [{speaker_character_id}]".strip()
        if labels:
            prefix = f"{prefix} [{' / '.join(labels)}]".strip()

        if prefix and text:
            return f"{prefix}: {text}"
        return text or prefix

    def _match_voice_track(
        self,
        *,
        dialogue: Dict[str, Any],
        voices: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        character_id = str(dialogue.get("speaker_character_id") or "").strip()
        speaker_name = self._normalize_lookup_key(str(dialogue.get("speaker_name") or ""))

        for voice in voices:
            if character_id and str(voice.get("character_id") or "").strip() == character_id:
                return voice
        for voice in voices:
            if speaker_name and self._normalize_lookup_key(str(voice.get("name") or "")) == speaker_name:
                return voice
        return None

    async def _concat_layer(self, input_paths: List[str], output_path: Path) -> Path:
        if not input_paths:
            raise RuntimeError(f"缺少输入音频，无法拼接层文件: {output_path.name}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        concat_file = Path(tempfile.mkstemp(prefix="audio_concat_", suffix=".txt")[1])
        try:
            concat_file.write_text(
                "".join(f"file '{Path(path).resolve().as_posix()}'\n" for path in input_paths),
                encoding="utf-8",
            )
            await self._run_ffmpeg(
                [
                    self.ffmpeg_path or "ffmpeg",
                    "-y",
                    "-f",
                    "concat",
                    "-safe",
                    "0",
                    "-i",
                    str(concat_file),
                    "-c",
                    "copy",
                    str(output_path),
                ]
            )
        finally:
            concat_file.unlink(missing_ok=True)
        return output_path

    async def _mix_layers(
        self,
        *,
        dialogue_path: Path,
        ambience_path: Path,
        music_path: Path,
        sfx_path: Path,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        filter_graph = (
            "[2:a][0:a]sidechaincompress=threshold=0.02:ratio=10:attack=15:release=280[musicduck];"
            "[1:a][0:a]sidechaincompress=threshold=0.04:ratio=4:attack=10:release=220[ambduck];"
            "[0:a]volume=1.8[d0];"
            "[ambduck]volume=0.35[a1];"
            "[musicduck]volume=0.22[a2];"
            "[3:a]volume=0.85[a3];"
            "[d0][a1][a2][a3]amix=inputs=4:normalize=0,alimiter=limit=0.95[out]"
        )
        await self._run_ffmpeg(
            [
                self.ffmpeg_path or "ffmpeg",
                "-y",
                "-i",
                str(dialogue_path),
                "-i",
                str(ambience_path),
                "-i",
                str(music_path),
                "-i",
                str(sfx_path),
                "-filter_complex",
                filter_graph,
                "-map",
                "[out]",
                "-c:a",
                self.master_codec,
                "-b:a",
                self.master_bitrate,
                str(output_path),
            ]
        )

    async def _pad_or_trim_audio(
        self,
        *,
        input_path: Path,
        output_path: Path,
        target_duration: float,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._run_ffmpeg(
            [
                self.ffmpeg_path or "ffmpeg",
                "-y",
                "-i",
                str(input_path),
                "-af",
                f"apad=whole_dur={target_duration:.3f},atrim=0:{target_duration:.3f}",
                "-c:a",
                self.master_codec,
                "-b:a",
                self.master_bitrate,
                str(output_path),
            ]
        )

    async def _mux_video_and_audio(
        self,
        *,
        video_path: Path,
        audio_path: Path,
        output_path: Path,
    ) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        await self._run_ffmpeg(
            [
                self.ffmpeg_path or "ffmpeg",
                "-y",
                "-i",
                str(video_path),
                "-i",
                str(audio_path),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                self.master_codec,
                "-b:a",
                self.master_bitrate,
                "-shortest",
                str(output_path),
            ]
        )

    async def _probe_media_duration(self, media_path: str) -> float:
        if not self.ffprobe_path:
            return 0.0
        process = await asyncio.create_subprocess_exec(
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            media_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        if process.returncode != 0:
            return 0.0
        try:
            payload = json.loads(stdout.decode("utf-8"))
            return float((payload.get("format") or {}).get("duration") or 0.0)
        except Exception:
            return 0.0

    async def _run_ffmpeg(self, args: List[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            message = stderr.decode("utf-8", errors="ignore") or stdout.decode("utf-8", errors="ignore")
            raise RuntimeError(message)

    def _segment_render_to_manifest(self, render: AudioSegmentRender) -> Dict[str, Any]:
        return {
            "segment_number": render.segment_number,
            "title": render.title,
            "start_time": render.start_time,
            "duration": render.duration,
            "cues": [asdict(cue) for cue in render.cues],
            "layer_assets": [asdict(asset) for asset in render.layer_assets],
        }

    def _voice_tracks_prompt(self, segment: Dict[str, Any]) -> str:
        voice_tracks = list(segment.get("voice_tracks") or [])
        if not voice_tracks:
            return ""
        normalized: List[str] = []
        for item in voice_tracks:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            style = str(item.get("speaking_style") or "").strip()
            emotion = str(item.get("emotion_baseline") or "").strip()
            voice_profile = dict(item.get("voice_profile") or {})
            voice_type = str(voice_profile.get("voice_type") or "").strip()
            parts = [part for part in [name, style, emotion, voice_type] if part]
            if parts:
                normalized.append("｜".join(parts))
        return "；".join(normalized)

    def _join_non_empty(self, parts: List[str]) -> str:
        return "；".join(part for part in parts if str(part).strip())


def build_doubao_tts_provider_from_settings(
    *,
    sample_rate: Optional[int] = None,
    channels: Optional[int] = None,
) -> DoubaoTTSProvider:
    app_id = str(settings.DOUBAO_TTS_APP_ID or "").strip()
    access_token = str(settings.DOUBAO_TTS_ACCESS_TOKEN or "").strip()
    if not app_id or not access_token:
        raise RuntimeError("缺少 DOUBAO_TTS_APP_ID 或 DOUBAO_TTS_ACCESS_TOKEN，无法执行豆包 TTS 试听。")

    return DoubaoTTSProvider(
        ffmpeg_path=shutil.which("ffmpeg") or "ffmpeg",
        sample_rate=int(sample_rate or settings.AUDIO_SAMPLE_RATE or 48000),
        channels=int(channels or settings.AUDIO_CHANNELS or 2),
        app_id=app_id,
        access_token=access_token,
        cluster=str(settings.DOUBAO_TTS_CLUSTER or "volcano_tts").strip(),
        api_url=str(settings.DOUBAO_TTS_API_URL or "https://openspeech.bytedance.com/api/v1/tts").strip(),
        default_voice_type=str(settings.DOUBAO_TTS_DEFAULT_VOICE_TYPE or "").strip(),
    )
