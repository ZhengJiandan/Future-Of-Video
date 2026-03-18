#!/usr/bin/env python3
"""
豆包 Seedance 视频生成 API 封装（官方API版本）
基于火山方舟官方API文档: https://www.volcengine.com/docs/82379/1520757
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# API配置
DEFAULT_DOUBAO_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

# 视频生成模型ID（Model ID）
SEEDANCE_10_PRO = "doubao-seedance-1-0-pro-250528"
SEEDANCE_15_PRO = "doubao-seedance-1-5-pro-251215"
SEEDANCE_15_LITE = "doubao-seedance-1-5-lite-241115"
SEEDANCE_10_LITE_I2V = "doubao-seedance-1-0-lite-i2v-250428"


class Ratio(str, Enum):
    """宽高比"""
    R_16_9 = "16:9"
    R_4_3 = "4:3"
    R_1_1 = "1:1"
    R_3_4 = "3:4"
    R_9_16 = "9:16"
    R_21_9 = "21:9"
    ADAPTIVE = "adaptive"  # 自适应（仅Seedance 1.5 Pro支持）


class Resolution(str, Enum):
    """分辨率"""
    R_480P = "480p"
    R_720P = "720p"
    R_1080P = "1080p"


@dataclass
class VideoGenerationResponse:
    """视频生成响应"""
    id: str  # 任务ID
    status: str  # pending/processing/completed/failed
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    cover_url: Optional[str] = None
    duration: Optional[int] = None
    ratio: Optional[str] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None


@dataclass
class VideoTaskStatus:
    """视频任务状态"""
    id: str
    status: str  # queued/running/succeeded/failed/expired
    progress: Optional[int] = None
    video_url: Optional[str] = None
    last_frame_url: Optional[str] = None
    cover_url: Optional[str] = None
    duration: Optional[int] = None
    ratio: Optional[str] = None
    error_message: Optional[str] = None


class DoubaoVideoGenerator:
    """豆包视频生成器（官方API版本）"""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = SEEDANCE_15_PRO,
        base_url: Optional[str] = None,
    ):
        self.api_key = api_key or settings.DOUBAO_API_KEY or os.getenv("DOUBAO_API_KEY")
        self.model = model
        self.base_url = (base_url or settings.DOUBAO_BASE_URL or DEFAULT_DOUBAO_BASE_URL).rstrip("/")
        self.debug_logging = bool(getattr(settings, "MODEL_DEBUG_LOGGING", True))
        self.debug_max_chars = int(getattr(settings, "MODEL_DEBUG_MAX_CHARS", 20000))

        if not self.api_key:
            raise ValueError("DOUBAO_API_KEY 未配置，无法调用豆包视频生成接口")

        # HTTP客户端
        self.client = httpx.AsyncClient(
            timeout=300.0,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
        )

    def _truncate_for_log(self, value: str) -> str:
        if len(value) <= self.debug_max_chars:
            return value
        return f"{value[:self.debug_max_chars]}\n...<truncated {len(value) - self.debug_max_chars} chars>"

    def _sanitize_for_log(self, value: Any, *, parent_key: str = "") -> Any:
        if isinstance(value, dict):
            sanitized: Dict[str, Any] = {}
            for key, item in value.items():
                lowered = str(key).lower()
                if lowered == "authorization":
                    sanitized[key] = "***"
                    continue
                if lowered in {"data", "binary"} and isinstance(item, str):
                    sanitized[key] = f"<blob length={len(item)}>"
                    continue
                sanitized[key] = self._sanitize_for_log(item, parent_key=lowered)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_for_log(item, parent_key=parent_key) for item in value]
        if isinstance(value, str):
            return self._truncate_for_log(value)
        return value

    def _json_for_log(self, payload: Any) -> str:
        try:
            raw = json.dumps(self._sanitize_for_log(payload), ensure_ascii=False, indent=2)
        except Exception:
            raw = str(payload)
        return self._truncate_for_log(raw)

    def _log_request(self, *, action: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao video request | model=%s | action=%s\n%s",
            self.model,
            action,
            self._json_for_log(payload),
        )

    def _log_response(self, *, action: str, payload: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao video response | model=%s | action=%s\n%s",
            self.model,
            action,
            self._json_for_log(payload),
        )
    
    async def create_video_task(
        self,
        content: List[Dict[str, Any]],
        ratio: str = "16:9",
        resolution: str = "720p",
        duration: int = 5,
        frames: Optional[int] = None,
        seed: int = -1,
        watermark: bool = False,
        camera_fixed: bool = False,
        generate_audio: bool = True,
        draft: bool = False,
        return_last_frame: bool = False,
        callback_url: Optional[str] = None,
        service_tier: str = "default",
        execution_expires_after: int = 172800
    ) -> VideoGenerationResponse:
        """
        创建视频生成任务
        
        API: POST /contents/generations/tasks
        
        Args:
            content: 输入内容，支持文本和图片
            ratio: 宽高比
            resolution: 分辨率
            duration: 时长（秒），2-12秒
            frames: 帧数（与duration二选一）
            seed: 随机种子
            watermark: 是否添加水印
            camera_fixed: 是否固定摄像头
            generate_audio: 是否生成音频（仅Seedance 1.5 Pro）
            draft: 是否为样片模式
            return_last_frame: 是否返回尾帧
            callback_url: 回调URL
            service_tier: 服务等级（default/flex）
            execution_expires_after: 任务超时时间（秒）
        """
        try:
            # 构建请求体
            body = {
                "model": self.model,
                "content": content,
                "ratio": ratio,
                "resolution": resolution,
                "duration": duration,
                "seed": seed,
                "watermark": watermark,
                "camera_fixed": camera_fixed,
                "draft": draft,
                "return_last_frame": return_last_frame,
                "service_tier": service_tier,
                "execution_expires_after": execution_expires_after
            }
            
            # 可选参数
            if frames is not None:
                body["frames"] = frames
            if generate_audio is not None:
                body["generate_audio"] = generate_audio
            if callback_url:
                body["callback_url"] = callback_url
            
            logger.info(f"创建视频生成任务，模型: {self.model}")
            logger.info(f"内容: {json.dumps(content, ensure_ascii=False)[:200]}...")
            self._log_request(action="create_video_task", payload=body)
            
            # 发送请求
            response = await self.client.post(
                f"{self.base_url}/contents/generations/tasks",
                json=body
            )
            response.raise_for_status()
            
            data = response.json()
            self._log_response(action="create_video_task", payload=data)
            logger.info(f"任务创建成功: {data.get('id')}")
            media = self._extract_media_fields(data)
            
            return VideoGenerationResponse(
                id=data.get("id"),
                status=data.get("status", "pending"),
                video_url=media.get("video_url"),
                last_frame_url=media.get("last_frame_url"),
                cover_url=media.get("cover_url"),
                duration=media.get("duration"),
                ratio=media.get("ratio"),
                created_at=datetime.now()
            )
            
        except httpx.HTTPError as e:
            logger.error(f"HTTP错误: {e}")
            if hasattr(e, 'response') and e.response is not None:
                try:
                    error_detail = e.response.json()
                    logger.error(f"错误详情: {error_detail}")
                except:
                    logger.error(f"响应内容: {e.response.text}")
            raise
        except Exception as e:
            logger.error(f"创建视频任务失败: {e}")
            raise
    
    async def get_task_status(self, task_id: str) -> VideoTaskStatus:
        """
        查询视频生成任务状态
        
        API: GET /contents/generations/tasks/{task_id}
        
        状态说明:
        - queued: 排队中
        - running: 运行中
        - succeeded: 成功
        - failed: 失败
        - expired: 超时
        """
        try:
            self._log_request(
                action="get_task_status",
                payload={"task_id": task_id, "url": f"{self.base_url}/contents/generations/tasks/{task_id}"},
            )
            response = await self.client.get(
                f"{self.base_url}/contents/generations/tasks/{task_id}"
            )
            response.raise_for_status()
            
            data = response.json()
            self._log_response(action="get_task_status", payload=data)
            media = self._extract_media_fields(data)
            error_message = (
                data.get("error_message")
                or ((data.get("error") or {}).get("message") if isinstance(data.get("error"), dict) else None)
            )
            if data.get("status") == "succeeded" and not media.get("video_url"):
                logger.warning(
                    "任务 %s succeeded but no video_url parsed, raw payload: %s",
                    task_id,
                    json.dumps(data, ensure_ascii=False)[:4000],
                )
            
            return VideoTaskStatus(
                id=data.get("id"),
                status=data.get("status"),
                progress=data.get("progress"),
                video_url=media.get("video_url"),
                last_frame_url=media.get("last_frame_url"),
                cover_url=media.get("cover_url"),
                duration=media.get("duration"),
                ratio=media.get("ratio"),
                error_message=error_message,
            )
            
        except httpx.HTTPError as e:
            logger.error(f"查询任务状态HTTP错误: {e}")
            raise
        except Exception as e:
            logger.error(f"查询任务状态失败: {e}")
            raise
    
    async def wait_for_completion(
        self, 
        task_id: str, 
        poll_interval: int = 5,
        max_wait_time: int = 600
    ) -> VideoGenerationResponse:
        """
        等待视频生成完成
        
        Args:
            task_id: 任务ID
            poll_interval: 轮询间隔（秒）
            max_wait_time: 最大等待时间（秒）
        """
        import time
        start_time = time.time()
        
        logger.info(f"开始等待视频生成完成，任务ID: {task_id}")
        
        while time.time() - start_time < max_wait_time:
            status = await self.get_task_status(task_id)
            
            logger.info(f"任务状态: {status.status}, 进度: {status.progress}%")
            
            if status.status == "succeeded":
                logger.info(f"视频生成完成: {status.video_url}")
                if not status.video_url:
                    logger.warning("任务 %s 已 succeeded，但未解析到 video_url", task_id)
                return VideoGenerationResponse(
                    id=task_id,
                    status="completed",
                    video_url=status.video_url,
                    last_frame_url=status.last_frame_url,
                    cover_url=status.cover_url,
                    duration=status.duration,
                    ratio=status.ratio,
                    completed_at=datetime.now()
                )
            elif status.status == "failed":
                logger.error(f"视频生成失败: {status.error_message}")
                return VideoGenerationResponse(
                    id=task_id,
                    status="failed",
                    error_message=status.error_message
                )
            elif status.status == "expired":
                logger.warning(f"任务超时: {task_id}")
                return VideoGenerationResponse(
                    id=task_id,
                    status="expired",
                    error_message="任务超时"
                )
            
            await asyncio.sleep(poll_interval)
        
        logger.warning(f"等待视频生成超时，任务ID: {task_id}")
        return VideoGenerationResponse(
            id=task_id,
            status="timeout",
            error_message="等待视频生成超时"
        )
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()

    def _extract_media_fields(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        从方舟视频任务响应中提取媒体字段。

        官方返回中的视频地址通常位于 content.video_url，而不是顶层。
        这里做兼容提取，避免因为字段位置差异误判任务失败。
        """
        content = data.get("content") if isinstance(data.get("content"), dict) else {}
        result = data.get("result") if isinstance(data.get("result"), dict) else {}
        output = data.get("output") if isinstance(data.get("output"), dict) else {}

        candidates = [data, content, result, output]

        def first_value(*keys: str) -> Optional[Any]:
            for payload in candidates:
                for key in keys:
                    value = payload.get(key)
                    if value not in (None, "", []):
                        return value
            return None

        return {
            "video_url": first_value("video_url", "url"),
            "last_frame_url": first_value("last_frame_url"),
            "cover_url": first_value("cover_url", "poster_url", "cover"),
            "duration": first_value("duration"),
            "ratio": first_value("ratio"),
        }


# ==================== 便捷函数 ====================

async def create_text_to_video(
    text: str,
    model: str = SEEDANCE_15_PRO,
    ratio: str = "16:9",
    resolution: str = "720p",
    duration: int = 5,
    wait_for_completion: bool = False
) -> VideoGenerationResponse:
    """
    文生视频便捷函数
    
    Args:
        text: 视频描述文本（中文）
        model: 模型ID
        ratio: 宽高比
        resolution: 分辨率
        duration: 时长（秒）
        wait_for_completion: 是否等待完成
    """
    generator = DoubaoVideoGenerator(model=model)
    
    try:
        content = [{"type": "text", "text": text}]
        
        response = await generator.create_video_task(
            content=content,
            ratio=ratio,
            resolution=resolution,
            duration=duration
        )
        
        if wait_for_completion and response.status == "pending":
            response = await generator.wait_for_completion(response.id)
        
        return response
        
    finally:
        await generator.close()


# 同步便捷函数
def create_text_to_video_sync(
    text: str,
    model: str = SEEDANCE_15_PRO,
    wait_for_completion: bool = True
) -> VideoGenerationResponse:
    """文生视频同步函数"""
    return asyncio.run(create_text_to_video(
        text=text,
        model=model,
        wait_for_completion=wait_for_completion
    ))


if __name__ == "__main__":
    # 测试代码
    async def test():
        print("测试豆包视频生成API（官方版本）...")
        
        # 测试文生视频
        print("\n=== 测试文生视频 ===")
        try:
            response = await create_text_to_video(
                text="小猫对着镜头打哈欠",
                model=SEEDANCE_15_PRO,
                ratio="16:9",
                resolution="720p",
                duration=5,
                wait_for_completion=False
            )
            
            print(f"✅ 任务创建成功!")
            print(f"   任务ID: {response.id}")
            print(f"   状态: {response.status}")
            
        except Exception as e:
            print(f"❌ 错误: {e}")
            import traceback
            traceback.print_exc()
    
    asyncio.run(test())
