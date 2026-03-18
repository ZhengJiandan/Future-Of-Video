#!/usr/bin/env python3
"""
视频合并服务
提供视频片段合并、转场效果、FFmpeg处理等功能
"""

import os
import subprocess
import tempfile
import asyncio
import json
import shutil
from typing import List, Optional, Dict, Any, Literal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import logging
import httpx

logger = logging.getLogger(__name__)


@dataclass
class VideoSegment:
    """视频片段信息"""
    id: str
    video_url: str
    duration: float
    order: int
    transition_in: Optional[str] = None
    transition_out: Optional[str] = None


@dataclass
class MergeOptions:
    """视频合并选项"""
    output_resolution: Literal["480p", "720p", "1080p"] = "720p"
    output_format: Literal["mp4", "mov"] = "mp4"
    fps: int = 24
    video_codec: Literal["h264", "h265"] = "h264"
    audio_codec: Literal["aac", "mp3"] = "aac"
    add_watermark: bool = False
    watermark_path: Optional[str] = None
    watermark_position: Literal["top-left", "top-right", "bottom-left", "bottom-right", "center"] = "bottom-right"


@dataclass
class TransitionEffect:
    """转场效果配置"""
    name: str
    duration: float  # 转场时长（秒）
    params: Optional[Dict[str, Any]] = None


# 支持的转场效果
SUPPORTED_TRANSITIONS = {
    "fade": "淡入淡出",
    "dissolve": "溶解",
    "wipe": "擦除",
    "slide": "滑动",
    "zoom": "缩放",
    "blur": "模糊过渡",
    "pixelate": "像素化",
    "none": "无转场"
}


class VideoMergerService:
    """视频合并服务"""
    
    def __init__(self, temp_dir: Optional[str] = None, output_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.gettempdir()
        self.output_dir = output_dir or os.path.join(self.temp_dir, "video_output")
        os.makedirs(self.output_dir, exist_ok=True)
        self.ffmpeg_path = shutil.which("ffmpeg")
        self.ffprobe_path = shutil.which("ffprobe")

        # 检查 FFmpeg 是否可用
        self.ffmpeg_available = self._check_ffmpeg()
    
    def _check_ffmpeg(self):
        """检查 FFmpeg 是否已安装"""
        if not self.ffmpeg_path:
            logger.error("FFmpeg 未安装！请安装 FFmpeg: sudo apt install ffmpeg")
            return False

        try:
            result = subprocess.run(
                [self.ffmpeg_path, "-version"],
                capture_output=True,
                text=True,
                timeout=15
            )
            if result.returncode == 0:
                version_line = result.stdout.split('\n')[0]
                logger.info(f"FFmpeg 已安装: {version_line}")
                return True
            logger.warning("FFmpeg 版本探测返回非零退出码: %s", result.returncode)
            return True
        except subprocess.TimeoutExpired:
            logger.warning("FFmpeg 版本探测超时，但已检测到可执行文件: %s", self.ffmpeg_path)
            return True
        except Exception as e:
            logger.error(f"检查 FFmpeg 时出错: {e}")
            return True
    
    async def merge_videos(
        self,
        segments: List[VideoSegment],
        options: MergeOptions = None,
        transitions: Optional[List[TransitionEffect]] = None,
        output_filename: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        合并多个视频片段
        
        Args:
            segments: 视频片段列表
            options: 合并选项
            transitions: 转场效果列表
            output_filename: 输出文件名（不含扩展名）
        
        Returns:
            包含输出路径、时长、状态等信息的字典
        """
        options = options or MergeOptions()
        
        if not segments:
            raise ValueError("视频片段列表不能为空")
        
        if len(segments) < 2:
            logger.warning("只有一个视频片段，无需合并")
        
        # 生成输出文件名
        if not output_filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"merged_video_{timestamp}"
        
        output_path = os.path.join(self.output_dir, f"{output_filename}.{options.output_format}")
        
        try:
            # 根据转场效果选择合并策略
            if transitions and len(transitions) > 0:
                result = await self._merge_with_transitions(segments, options, transitions, output_path)
            else:
                result = await self._simple_concat(segments, options, output_path)
            
            logger.info(f"视频合并成功: {output_path}")
            return {
                "status": "success",
                "output_path": output_path,
                "output_url": f"/output/{output_filename}.{options.output_format}",
                "filename": f"{output_filename}.{options.output_format}",
                "segment_count": len(segments),
                "options": options.__dict__,
                "created_at": datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"视频合并失败: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "output_path": None
            }
    
    async def _simple_concat(
        self,
        segments: List[VideoSegment],
        options: MergeOptions,
        output_path: str
    ) -> bool:
        """
        简单的视频拼接（无转场效果）
        使用 FFmpeg concat demuxer
        """
        # 创建临时文件列表
        concat_file = os.path.join(self.temp_dir, f"concat_list_{datetime.now().timestamp()}.txt")
        
        try:
            # 写入文件列表
            with open(concat_file, 'w', encoding='utf-8') as f:
                for segment in segments:
                    # 下载视频到本地（如果是URL）
                    local_path = await self._ensure_local_file(segment.video_url)
                    f.write(f"file '{local_path}'\n")
            
            # 构建 FFmpeg 命令
            cmd = [
                self.ffmpeg_path or "ffmpeg",
                "-y",  # 覆盖输出文件
                "-f", "concat",
                "-safe", "0",
                "-i", concat_file,
                "-c:v", self._get_video_codec(options.video_codec),
                "-preset", "medium",
                "-crf", "23",
                "-r", str(options.fps),
                "-c:a", options.audio_codec,
                "-b:a", "128k",
                "-movflags", "+faststart",
                output_path
            ]
            
            # 执行 FFmpeg
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"视频拼接成功: {output_path}")
                return True
            else:
                error_msg = stderr.decode('utf-8', errors='ignore')
                logger.error(f"FFmpeg 错误: {error_msg}")
                raise RuntimeError(f"视频拼接失败: {error_msg}")
                
        finally:
            # 清理临时文件
            if os.path.exists(concat_file):
                os.remove(concat_file)
    
    async def _merge_with_transitions(
        self,
        segments: List[VideoSegment],
        options: MergeOptions,
        transitions: List[TransitionEffect],
        output_path: str
    ) -> bool:
        """
        带转场效果的视频合并
        使用 FFmpeg filter_complex
        """
        # TODO: 实现复杂的转场效果
        # 目前先使用简单拼接
        logger.warning("转场效果暂未实现，使用简单拼接")
        return await self._simple_concat(segments, options, output_path)
    
    async def _ensure_local_file(self, video_url: str) -> str:
        """
        确保视频文件在本地
        如果是URL，下载到本地；如果是本地路径，直接返回
        """
        if video_url.startswith(('http://', 'https://')):
            # 下载视频
            local_filename = os.path.join(
                self.temp_dir,
                f"video_{datetime.now().timestamp()}_{hash(video_url) % 10000}.mp4"
            )
            
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(video_url, timeout=60.0)
                    response.raise_for_status()
                    
                    with open(local_filename, 'wb') as f:
                        f.write(response.content)
                
                logger.info(f"视频下载成功: {local_filename}")
                return local_filename
                
            except Exception as e:
                logger.error(f"下载视频失败: {e}")
                raise
        else:
            # 本地路径
            if os.path.exists(video_url):
                return video_url
            else:
                raise FileNotFoundError(f"视频文件不存在: {video_url}")
    
    def _get_video_codec(self, codec: str) -> str:
        """获取FFmpeg编码器名称"""
        codec_map = {
            "h264": "libx264",
            "h265": "libx265"
        }
        return codec_map.get(codec, "libx264")
    
    async def get_video_info(self, video_path: str) -> Dict[str, Any]:
        """
        获取视频信息
        使用 FFprobe
        """
        try:
            cmd = [
                self.ffprobe_path or "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration,size,bit_rate",
                "-show_entries", "stream=width,height,codec_name,avg_frame_rate",
                "-of", "json",
                video_path
            ]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                info = json.loads(stdout.decode('utf-8'))
                return {
                    "status": "success",
                    "format": info.get("format", {}),
                    "streams": info.get("streams", []),
                    "video_path": video_path
                }
            else:
                error_msg = stderr.decode('utf-8', errors='ignore')
                logger.error(f"FFprobe 错误: {error_msg}")
                return {
                    "status": "error",
                    "error": error_msg
                }
                
        except Exception as e:
            logger.error(f"获取视频信息失败: {e}")
            return {
                "status": "error",
                "error": str(e)
            }


# ==================== 便捷函数 ====================

async def merge_video_segments(
    segments: List[Dict[str, Any]],
    output_resolution: str = "720p",
    output_format: str = "mp4",
    add_transitions: bool = False
) -> Dict[str, Any]:
    """
    便捷函数：合并视频片段
    
    Args:
        segments: 视频片段列表，每个片段包含 video_url, duration 等
        output_resolution: 输出分辨率
        output_format: 输出格式
        add_transitions: 是否添加转场效果
    
    Returns:
        合并结果
    """
    # 转换为 VideoSegment 对象
    video_segments = [
        VideoSegment(
            id=str(i),
            video_url=seg["video_url"],
            duration=seg.get("duration", 5.0),
            order=i
        )
        for i, seg in enumerate(segments)
    ]
    
    # 创建合并服务
    merger = VideoMergerService()
    
    # 合并选项
    options = MergeOptions(
        output_resolution=output_resolution,
        output_format=output_format
    )
    
    # 执行合并
    result = await merger.merge_videos(
        segments=video_segments,
        options=options,
        transitions=None if not add_transitions else []
    )
    
    return result


# 同步便捷函数
def merge_videos_sync(
    segments: List[Dict[str, Any]],
    output_resolution: str = "720p"
) -> Dict[str, Any]:
    """同步版本的合并函数"""
    return asyncio.run(merge_video_segments(
        segments=segments,
        output_resolution=output_resolution
    ))


if __name__ == "__main__":
    # 测试代码
    async def test():
        print("测试视频合并服务...")
        
        # 检查 FFmpeg
        merger = VideoMergerService()
        
        # 测试视频信息获取
        # info = await merger.get_video_info("test.mp4")
        # print(info)
    
    asyncio.run(test())
