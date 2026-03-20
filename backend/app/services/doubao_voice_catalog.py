#!/usr/bin/env python3
"""豆包 TTS 官方音色目录服务。"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List


CATALOG_PATH = Path(__file__).resolve().parents[1] / "data" / "doubao_tts_voice_catalog.json"


class DoubaoVoiceCatalogService:
    def list_voices(self) -> Dict[str, Any]:
        payload = self._load_catalog()
        voices: List[Dict[str, Any]] = []

        for item in payload.get("voices") or []:
            if not isinstance(item, dict):
                continue
            voice_type = str(item.get("voice_type") or "").strip()
            if not voice_type:
                continue
            normalized = {
                "voice_type": voice_type,
                "voice_name": str(item.get("voice_name") or "").strip() or voice_type,
                "scenario": str(item.get("scenario") or "").strip(),
                "language": str(item.get("language") or "").strip(),
                "gender": str(item.get("gender") or "").strip(),
                "style": str(item.get("style") or "").strip(),
                "provider": "doubao-tts",
            }
            if normalized["voice_type"] == "zh_female_wanqudashu_moon_bigtts":
                normalized["metadata_warning"] = (
                    "Official search snippet shows inconsistent display name/gender for this voice_type; "
                    "retain the voice_type as authoritative."
                )
            voices.append(normalized)

        return {
            "provider": str(payload.get("provider") or "doubao-tts"),
            "catalog_version": str(payload.get("catalog_version") or ""),
            "source": dict(payload.get("source") or {}),
            "items": voices,
        }

    @lru_cache(maxsize=1)
    def _load_catalog(self) -> Dict[str, Any]:
        return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


doubao_voice_catalog_service = DoubaoVoiceCatalogService()
