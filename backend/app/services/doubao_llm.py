#!/usr/bin/env python3
"""
豆包大模型 (Doubao/火山引擎) API 封装
用于剧本生成和视频提示词优化
"""

import json
import httpx
import asyncio
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from datetime import datetime
import logging

from app.core.config import settings

logger = logging.getLogger(__name__)

# 豆包大模型配置
DEFAULT_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"

# Coding Plan 支持的模型列表：
# - doubao-pro-4k: 专业级，适合复杂任务
# - doubao-lite-4k: 轻量级，响应更快
# - doubao-1-5-pro-32k: 长上下文模型
# 推荐使用 doubao-pro-4k 进行剧本生成
DEFAULT_MODEL = "doubao-seed-2-0-lite-260215"

# 备用：如果使用端点ID方式，可以设置具体的端点
# DEFAULT_ENDPOINT = "ep-20250220-xxxxxxxxx-xxxxx"


@dataclass
class DoubaoMessage:
    """豆包消息格式"""
    role: str  # system/user/assistant
    content: str


@dataclass
class DoubaoResponse:
    """豆包响应格式 - 支持动态字段"""
    id: str
    choices: List[Dict[str, Any]]
    usage: Dict[str, int]
    created: int
    model: str
    # 可选字段 - 不同模型可能返回不同字段
    service_tier: Optional[str] = None
    object: Optional[str] = None
    
    def __post_init__(self):
        """后处理，确保兼容性"""
        # 如果 choices 为空，初始化为空列表
        if self.choices is None:
            self.choices = []
    
    def get_content(self) -> str:
        """获取生成的内容"""
        if self.choices and len(self.choices) > 0:
            return self.choices[0].get("message", {}).get("content", "")
        return ""


class DoubaoLLM:
    """豆包大模型封装类"""
    
    def __init__(self, api_key: Optional[str] = None, model: str = DEFAULT_MODEL):
        self.api_key = api_key or getattr(settings, "DOUBAO_API_KEY", None)
        self.model = model or getattr(settings, "DOUBAO_MODEL", DEFAULT_MODEL)
        self.base_url = getattr(settings, "DOUBAO_BASE_URL", DEFAULT_BASE_URL).rstrip("/")

        if not self.api_key:
            raise ValueError("DOUBAO_API_KEY 未配置，无法调用豆包大模型生成剧本")

        self.default_timeout = httpx.Timeout(
            connect=float(getattr(settings, "DOUBAO_CONNECT_TIMEOUT", 20.0)),
            read=float(getattr(settings, "DOUBAO_READ_TIMEOUT", 240.0)),
            write=float(getattr(settings, "DOUBAO_WRITE_TIMEOUT", 60.0)),
            pool=float(getattr(settings, "DOUBAO_POOL_TIMEOUT", 60.0)),
        )
        self.max_retries = max(0, int(getattr(settings, "DOUBAO_MAX_RETRIES", 2)))
        self.retry_backoff_seconds = float(getattr(settings, "DOUBAO_RETRY_BACKOFF_SECONDS", 2.0))
        self.debug_logging = bool(getattr(settings, "MODEL_DEBUG_LOGGING", True))
        self.debug_max_chars = int(getattr(settings, "MODEL_DEBUG_MAX_CHARS", 20000))

        # 初始化 HTTP 客户端
        self.client = httpx.AsyncClient(
            timeout=self.default_timeout,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json"
            }
        )

    def _truncate_for_log(self, value: str) -> str:
        if len(value) <= self.debug_max_chars:
            return value
        return f"{value[:self.debug_max_chars]}\n...<truncated {len(value) - self.debug_max_chars} chars>"

    def _json_for_log(self, payload: Any) -> str:
        try:
            raw = json.dumps(payload, ensure_ascii=False, indent=2)
        except Exception:
            raw = str(payload)
        return self._truncate_for_log(raw)

    def _log_request(self, *, request_label: str, request_body: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao request | model=%s | label=%s\n%s",
            self.model,
            request_label,
            self._json_for_log(request_body),
        )

    def _log_response(self, *, request_label: str, response_body: Dict[str, Any]) -> None:
        if not self.debug_logging:
            return
        logger.info(
            "Doubao response | model=%s | label=%s\n%s",
            self.model,
            request_label,
            self._json_for_log(response_body),
        )
    
    async def chat_completion(
        self,
        messages: List[DoubaoMessage],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        top_p: float = 0.9,
        timeout: Optional[httpx.Timeout] = None,
        max_retries: Optional[int] = None,
        request_label: str = "chat_completion",
    ) -> DoubaoResponse:
        """
        调用豆包大模型进行对话
        
        Args:
            messages: 对话消息列表
            temperature: 温度参数（0-2，越高越随机）
            max_tokens: 最大生成token数
            top_p: 核采样参数
            
        Returns:
            DoubaoResponse: 模型响应
        """
        request_body = {
            "model": self.model,
            "messages": [
                {"role": msg.role, "content": msg.content}
                for msg in messages
            ],
            "temperature": temperature,
            "top_p": top_p
        }

        if max_tokens:
            request_body["max_tokens"] = max_tokens

        effective_timeout = timeout or self.default_timeout
        effective_retries = self.max_retries if max_retries is None else max(0, int(max_retries))
        self._log_request(request_label=request_label, request_body=request_body)

        for attempt in range(effective_retries + 1):
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    json=request_body,
                    timeout=effective_timeout,
                )
                response.raise_for_status()

                data = response.json()
                self._log_response(request_label=request_label, response_body=data)
                return DoubaoResponse(**data)

            except httpx.HTTPStatusError as e:
                response_text = ""
                try:
                    response_text = e.response.text
                except Exception:
                    response_text = ""
                logger.error(
                    "HTTP error calling Doubao API: %s | model=%s | label=%s | url=%s | response=%s",
                    e,
                    self.model,
                    request_label,
                    e.request.url,
                    response_text[:1000],
                )
                raise
            except httpx.ReadTimeout as e:
                if attempt < effective_retries:
                    wait_seconds = self.retry_backoff_seconds * (attempt + 1)
                    logger.warning(
                        "Doubao API read timeout, retrying: model=%s label=%s attempt=%s/%s wait=%.1fs",
                        self.model,
                        request_label,
                        attempt + 1,
                        effective_retries + 1,
                        wait_seconds,
                    )
                    await asyncio.sleep(wait_seconds)
                    continue
                logger.error(
                    "Doubao API read timeout after retries: model=%s label=%s retries=%s timeout=%s",
                    self.model,
                    request_label,
                    effective_retries,
                    effective_timeout,
                )
                raise RuntimeError("豆包剧本生成超时，请稍后重试；如持续发生，可增大 DOUBAO_SCRIPT_READ_TIMEOUT") from e
            except httpx.HTTPError as e:
                logger.error(
                    "HTTP transport error calling Doubao API: %s | model=%s | label=%s",
                    e,
                    self.model,
                    request_label,
                )
                raise
            except Exception as e:
                logger.error("Error calling Doubao API: %s | label=%s", e, request_label)
                raise

        raise RuntimeError("豆包请求失败，超过最大重试次数")
    
    def generate_script_prompt(self, user_input: str) -> str:
        """
        生成用于剧本生成的系统提示词
        
        Args:
            user_input: 用户输入的场景描述
            
        Returns:
            str: 完整的系统提示词
        """
        system_prompt = f"""你是一位专业的短视频剧本策划师，专门负责将用户的创意转化为可用于AI视频生成的专业剧本。

【任务】
将用户的输入转化为完整的视频剧本，包括：
1. 剧本润色和优化
2. 场景分析（地点、时间、天气、氛围）
3. 角色分析（匹配三角洲行动干员）
4. 分镜脚本（镜号、时长、画面描述）
5. 视频生成提示词（用于可灵/即梦等AI）

【三角洲行动干员数据库】
- 突击：威龙（王宇昊）、疾风（克莱尔）、无名（埃利）
- 支援：蛊（佐娅·庞琴科娃）、蜂医
- 工程：比特（拉希德）、牧羊人
- 侦察：骇爪（麦晓雯）、银翼（兰登）

【输出格式】
请以JSON格式输出，包含以下字段：
{{
    "polished_script": "润色后的完整剧本",
    "scene_analysis": "场景描述",
    "character_analysis": "角色匹配分析",
    "matched_operators": ["匹配的干员名称"],
    "scene_breakdown": [
        {{
            "scene_number": 1,
            "description": "场景描述",
            "characters": ["出场角色"],
            "action": "动作描述",
            "duration": "预估时长"
        }}
    ],
    "video_prompts": [
        {{
            "prompt": "用于AI视频生成的英文提示词",
            "negative_prompt": "负面提示词",
            "duration": 10,
            "style": "写实/电影风格"
        }}
    ]
}}

【用户输入】
{user_input}

请生成专业的视频剧本："""
        
        return system_prompt
    
    async def close(self):
        """关闭HTTP客户端"""
        await self.client.aclose()


# 便捷使用函数
async def generate_script_with_doubao(user_input: str) -> dict:
    """
    使用豆包大模型生成剧本的便捷函数
    
    Args:
        user_input: 用户输入的场景描述
        
    Returns:
        dict: 生成的剧本JSON
    """
    llm = DoubaoLLM()
    
    try:
        # 构建消息
        messages = [
            DoubaoMessage(role="system", content="你是一位专业的短视频剧本策划师。"),
            DoubaoMessage(role="user", content=llm.generate_script_prompt(user_input))
        ]
        
        # 调用API
        response = await llm.chat_completion(messages, temperature=0.7)
        
        # 解析JSON响应
        content = response.get_content()
        
        # 尝试解析JSON
        try:
            script_json = json.loads(content)
            return script_json
        except json.JSONDecodeError:
            # 如果返回的不是JSON，包装成标准格式
            return {
                "polished_script": content,
                "scene_analysis": "场景信息待提取",
                "character_analysis": "角色分析待提取",
                "matched_operators": [],
                "scene_breakdown": [],
                "video_prompts": [],
                "raw_response": content
            }
    
    finally:
        await llm.close()


# 同步便捷函数（用于非异步环境）
def generate_script_sync(user_input: str) -> dict:
    """同步版本的剧本生成函数"""
    return asyncio.run(generate_script_with_doubao(user_input))


if __name__ == "__main__":
    # 测试
    async def test():
        result = await generate_script_with_doubao("威龙和蛊在废弃工厂执行秘密任务")
        print(json.dumps(result, ensure_ascii=False, indent=2))
    
    asyncio.run(test())
