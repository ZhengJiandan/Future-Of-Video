import requests
import base64
import os
from datetime import datetime
from typing import Optional, List, Dict, Any
from loguru import logger

from app.core.config import settings


class NanoBananaProClient:
    """NanoBanana Pro API 客户端

    用于调用 NanoBanana Pro 生成图片，作为视频分段生成的首尾帧参考图
    API 文档：https://docs.laozhang.ai/api-capabilities/nano-banana-pro-image

    支持三种生成模式：
    1. 文生图 (text-to-image): 纯文本提示生成图片
    2. 图生图 (image-to-image): 基于输入图修改生成新图
    3. 多图混合 (multi-image-mix): 多张图混合 + 文字提示生成新图
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        api_url: Optional[str] = None,
    ):
        self.api_key = api_key or getattr(settings, "NANOBANANA_API_KEY", None) or os.getenv("NANOBANANA_API_KEY")
        self.api_url = api_url or getattr(settings, "NANOBANANA_BASE_URL", None) or "https://api.laozhang.ai/v1beta/models/gemini-3-pro-image-preview:generateContent"
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _call_api(
        self,
        payload: Dict[str, Any],
        timeout: int = 180
    ) -> Dict[str, Any]:
        """底层API调用封装

        Returns:
            dict: {
                "success": bool,
                "image_data": bytes,
                "image_b64": str,
                "error": str
            }
        """
        if not self.api_key:
            return {
                "success": False,
                "error": "NANOBANANA_API_KEY not configured"
            }

        try:
            response = requests.post(
                self.api_url,
                headers=self.headers,
                json=payload,
                timeout=timeout
            )

            if response.status_code != 200:
                error_msg = f"API Error: {response.status_code} - {response.text[:200]}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

            result = response.json()

            # 提取图片数据
            try:
                image_b64 = result["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                image_data = base64.b64decode(image_b64)

                logger.info(f"Image generated successfully, size: {len(image_data)} bytes")
                return {
                    "success": True,
                    "image_data": image_data,
                    "image_b64": image_b64,
                    "error": ""
                }
            except KeyError as e:
                error_msg = f"Failed to parse response: missing key {e}"
                logger.error(error_msg)
                return {
                    "success": False,
                    "error": error_msg
                }

        except Exception as e:
            error_msg = f"Request failed: {str(e)}"
            logger.error(error_msg)
            return {
                "success": False,
                "error": error_msg
            }

    def generate_text_to_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k"
    ) -> Dict[str, Any]:
        """模式1：文生图 - 纯文本提示生成图片

        Args:
            prompt: 图片生成提示词
            aspect_ratio: 宽高比 ("1:1", "16:9", "9:16", "4:3", "3:4")
            image_size: 图片大小 ("1k", "2k", "4k")

        Returns:
            dict: {
                "success": bool,
                "image_data": bytes,  # 解码后的图片二进制数据
                "image_b64": str,    # base64编码的图片数据
                "error": str          # 错误信息（如果失败）
            }
        """
        logger.info(f"🔸 Text to image: {prompt[:100]}...")

        payload = {
            "contents": [{
                "parts": [{"text": prompt}]
            }],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }

        return self._call_api(payload)

    def generate_image_to_image(
        self,
        input_image_path: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k"
    ) -> Dict[str, Any]:
        """模式2：图生图 - 基于输入图修改生成新图

        Args:
            input_image_path: 输入参考图片文件路径
            prompt: 生成提示词（描述你想要的修改）
            aspect_ratio: 宽高比
            image_size: 图片大小

        Returns:
            dict: 生成结果
        """
        logger.info(f"🔸 Image to image: {input_image_path}, prompt: {prompt[:100]}...")

        # 读取并编码输入图片
        with open(input_image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode("utf-8")

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inlineData": {
                            "mimeType": "image/jpeg",
                            "data": img_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }

        return self._call_api(payload)

    def generate_image_to_image_b64(
        self,
        input_image_b64: str,
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k"
    ) -> Dict[str, Any]:
        """模式2b：图生图 - 使用base64编码的输入图

        Args:
            input_image_b64: base64编码的输入图片
            prompt: 生成提示词
            aspect_ratio: 宽高比
            image_size: 图片大小

        Returns:
            dict: 生成结果
        """
        logger.info(f"🔸 Image to image (base64), prompt: {prompt[:100]}...")

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": input_image_b64
                        }
                    }
                ]
            }],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }

        return self._call_api(payload)

    def generate_multi_image_mix(
        self,
        input_image_paths: List[str],
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k"
    ) -> Dict[str, Any]:
        """模式3：多图混合 - 多张图混合 + 文字提示生成新图

        Args:
            input_image_paths: 输入图片文件路径列表
            prompt: 生成提示词
            aspect_ratio: 宽高比
            image_size: 图片大小

        Returns:
            dict: 生成结果
        """
        logger.info(f"🔸 Multi-image mix: {len(input_image_paths)} images, prompt: {prompt[:100]}...")

        parts = [{"text": prompt}]

        for img_path in input_image_paths:
            with open(img_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode("utf-8")
                parts.append({
                    "inlineData": {
                        "mimeType": "image/jpeg",
                        "data": img_b64
                    }
                })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }

        return self._call_api(payload)

    def generate_multi_image_mix_b64(
        self,
        input_image_b64_list: List[str],
        prompt: str,
        aspect_ratio: str = "16:9",
        image_size: str = "2k"
    ) -> Dict[str, Any]:
        """模式3b：多图混合 - 使用base64编码的输入图片列表

        Args:
            input_image_b64_list: base64编码的输入图片列表
            prompt: 生成提示词
            aspect_ratio: 宽高比
            image_size: 图片大小

        Returns:
            dict: 生成结果
        """
        logger.info(f"🔸 Multi-image mix (base64): {len(input_image_b64_list)} images, prompt: {prompt[:100]}...")

        parts = [{"text": prompt}]

        for img_b64 in input_image_b64_list:
            parts.append({
                "inlineData": {
                    "mimeType": "image/jpeg",
                    "data": img_b64
                }
            })

        payload = {
            "contents": [{"parts": parts}],
            "generationConfig": {
                "responseModalities": ["IMAGE"],
                "imageConfig": {
                    "aspectRatio": aspect_ratio,
                    "imageSize": image_size
                }
            }
        }

        return self._call_api(payload)

    def save_to_file(
        self,
        image_data: bytes,
        prefix: str = "generated"
    ) -> str:
        """将生成的图片保存到文件

        Args:
            image_data: 图片二进制数据
            prefix: 文件名前缀

        Returns:
            str: 保存的文件路径
        """
        filename = f"{prefix}_{datetime.now().strftime('%y%m%d_%H%M%S')}.png"
        with open(filename, "wb") as f:
            f.write(image_data)
        logger.info(f"✅ Saved to: {filename}")
        return filename

    # 向后兼容别名
    def generate_image(
        self,
        prompt: str,
        image_size: str = "2K",
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """兼容旧接口 - 文生图"""
        return self.generate_text_to_image(prompt, aspect_ratio, image_size.lower())

    def generate_image_to_file(
        self,
        prompt: str,
        output_path: str,
        image_size: str = "2K",
        aspect_ratio: str = "16:9"
    ) -> Dict[str, Any]:
        """生成图片并保存到指定路径"""
        result = self.generate_text_to_image(prompt, aspect_ratio, image_size.lower())

        if result["success"]:
            try:
                with open(output_path, "wb") as f:
                    f.write(result["image_data"])
                logger.info(f"Image saved to: {output_path}")
            except Exception as e:
                return {
                    "success": False,
                    "error": f"Failed to save file: {str(e)}"
                }

        return result
