#!/usr/bin/env python3
"""统一图片生成路由：优先 NanoBanana，回退到豆包 Seedream。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from loguru import logger

from app.core.provider_keys import DOUBAO_API_KEY_ERROR_CODE, MissingProviderConfigError
from app.services.doubao_image_generation import DoubaoImageGenerationClient
from app.services.nanobanana_pro import NanoBananaProClient


class PreferredImageGenerationClient:
    def __init__(
        self,
        nanobanana: Optional[NanoBananaProClient] = None,
        doubao: Optional[DoubaoImageGenerationClient] = None,
    ) -> None:
        self.nanobanana = nanobanana or NanoBananaProClient()
        self.doubao = doubao or DoubaoImageGenerationClient()

    def _provider_attempts(self) -> List[str]:
        attempts: List[str] = []
        if getattr(self.nanobanana, "api_key", None):
            attempts.append("nanobanana")
        if getattr(self.doubao, "configured", False):
            attempts.append("doubao")
        return attempts

    def _ensure_provider_configured(self) -> None:
        if self._provider_attempts():
            return
        raise MissingProviderConfigError(
            code=DOUBAO_API_KEY_ERROR_CODE,
            message=(
                "未配置可用的图片生成凭证，无法生成图片。"
                "请先配置 NANOBANANA_API_KEY，或在前端临时填写 DOUBAO_API_KEY 后重试。"
            ),
        )

    def _finalize(self, result: Dict[str, Any], *, source: str, provider: str) -> Dict[str, Any]:
        normalized = dict(result or {})
        normalized["source"] = source
        normalized["provider"] = provider
        return normalized

    def _run_with_fallback(
        self,
        *,
        operation_label: str,
        nanobanana_call,
        nanobanana_source: str,
        doubao_call,
        doubao_source: str,
    ) -> Dict[str, Any]:
        self._ensure_provider_configured()

        if getattr(self.nanobanana, "api_key", None):
            try:
                result = nanobanana_call()
            except Exception as exc:
                logger.warning("NanoBanana {} failed, fallback to Doubao: {}", operation_label, exc)
            else:
                if result.get("success") and result.get("image_data"):
                    return self._finalize(result, source=nanobanana_source, provider="nanobanana")
                logger.warning(
                    "NanoBanana {} returned no image, fallback to Doubao: {}",
                    operation_label,
                    result.get("error"),
                )

        if getattr(self.doubao, "configured", False):
            try:
                result = doubao_call()
            except Exception as exc:
                logger.warning("Doubao {} failed: {}", operation_label, exc)
            else:
                if result.get("success") and result.get("image_data"):
                    return self._finalize(result, source=doubao_source, provider="doubao")
                logger.warning("Doubao {} returned no image: {}", operation_label, result.get("error"))

        attempted = ", ".join(self._provider_attempts()) or "none"
        return {
            "success": False,
            "error": f"No image provider succeeded for {operation_label}. attempted={attempted}",
        }

    def generate_text_to_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
    ) -> Dict[str, Any]:
        return self._run_with_fallback(
            operation_label="text_to_image",
            nanobanana_call=lambda: self.nanobanana.generate_text_to_image(
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
            nanobanana_source="nanobanana-text-to-image",
            doubao_call=lambda: self.doubao.generate_text_to_image(
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
            doubao_source="doubao-seedream-text-to-image",
        )

    def generate_image_to_image(
        self,
        input_image_path: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
        source_image_url: str = "",
    ) -> Dict[str, Any]:
        return self._run_with_fallback(
            operation_label="image_to_image",
            nanobanana_call=lambda: self.nanobanana.generate_image_to_image(
                input_image_path,
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
            nanobanana_source="nanobanana-image-to-image",
            doubao_call=lambda: self.doubao.generate_image_to_image(
                input_image_path,
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
                source_image_url=source_image_url,
            ),
            doubao_source="doubao-seedream-image-to-image",
        )

    def generate_multi_image_mix(
        self,
        input_image_paths: List[str],
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k",
    ) -> Dict[str, Any]:
        return self._run_with_fallback(
            operation_label="multi_image_mix",
            nanobanana_call=lambda: self.nanobanana.generate_multi_image_mix(
                input_image_paths,
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
            nanobanana_source="nanobanana-multi-image-mix",
            doubao_call=lambda: self.doubao.generate_multi_image_mix(
                input_image_paths,
                prompt,
                aspect_ratio=aspect_ratio,
                image_size=image_size,
            ),
            doubao_source="doubao-seedream-image-to-image",
        )
