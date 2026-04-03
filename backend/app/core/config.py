"""
应用核心配置。
"""
from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings
from typing import List, Optional
import os
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用基础配置
    APP_NAME: str = "future of video"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = Field(default=False, validation_alias=AliasChoices("DEBUG"))
    ENV: str = Field(default="development", validation_alias=AliasChoices("ENV", "ENVIRONMENT"))
    PIPELINE_RUNTIME_MODE: str = "minimal"
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8080
    WORKERS: int = 1
    
    # 数据库配置
    # URL 格式: mysql+aiomysql://用户名:密码@主机:端口/数据库名
    # 注意: 密码中的 @ 需要替换为 %40
    DATABASE_URL: str = "mysql+aiomysql://user:password@127.0.0.1:3306/future_of_video"
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis 配置
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_POOL_SIZE: int = 50
    
    # JWT认证配置
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1天
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # 文件上传配置
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/webp"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4", "video/webm"]
    
    # 可灵 AI
    KLING_ACCESS_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("KLING_ACCESS_KEY", "KLING_API_KEY", "KELING_API_KEY"),
    )
    KLING_SECRET_KEY: Optional[str] = Field(
        default=None,
        validation_alias=AliasChoices("KLING_SECRET_KEY", "KELING_SECRET_KEY"),
    )
    KLING_BASE_URL: str = Field(
        default="https://api-beijing.klingai.com",
        validation_alias=AliasChoices("KLING_BASE_URL", "KELING_BASE_URL"),
    )
    KLING_VIDEO_MODEL: str = Field(
        default="kling-v3-omni",
        validation_alias=AliasChoices("KLING_VIDEO_MODEL", "KELING_VIDEO_MODEL"),
    )
    KLING_VIDEO_MODE: str = Field(
        default="std",
        validation_alias=AliasChoices("KLING_VIDEO_MODE", "KELING_VIDEO_MODE"),
    )

    # NanoBanana 图片生成
    NANOBANANA_API_KEY: Optional[str] = None
    NANOBANANA_BASE_URL: str = "https://api.laozhang.ai/v1beta/models/gemini-3-pro-image-preview:generateContent"
    ALLOW_PLACEHOLDER_KEYFRAMES: bool = True
    
    # 豆包大模型 API 配置
    DOUBAO_API_KEY: Optional[str] = None
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DOUBAO_MODEL: str = "doubao-seed-2-0-lite-260215"
    DOUBAO_IMAGE_BASE_URL: str = "https://operator.las.cn-beijing.volces.com/api/v1"
    DOUBAO_IMAGE_MODEL: str = "doubao-seedream-5-0-260128"
    DOUBAO_VIDEO_MODEL: str = "doubao-seedance-1-5-pro-251215"
    DOUBAO_TTS_API_URL: str = "https://openspeech.bytedance.com/api/v1/tts"
    DOUBAO_TTS_APP_ID: Optional[str] = None
    DOUBAO_TTS_ACCESS_TOKEN: Optional[str] = None
    DOUBAO_TTS_CLUSTER: str = "volcano_tts"
    DOUBAO_TTS_DEFAULT_VOICE_TYPE: str = "zh_female_shaoergushi_mars_bigtts"
    DOUBAO_CONNECT_TIMEOUT: float = 20.0
    DOUBAO_READ_TIMEOUT: float = 240.0
    DOUBAO_WRITE_TIMEOUT: float = 60.0
    DOUBAO_POOL_TIMEOUT: float = 60.0
    DOUBAO_SCRIPT_READ_TIMEOUT: float = 360.0
    DOUBAO_MAX_RETRIES: int = 2
    DOUBAO_RETRY_BACKOFF_SECONDS: float = 2.0
    KLING_MAX_DURATION: int = Field(
        default=10,
        validation_alias=AliasChoices("KLING_MAX_DURATION", "KELING_MAX_DURATION"),
    )
    
    # 即梦AI
    JIMENG_API_KEY: Optional[str] = None
    JIMENG_BASE_URL: str = "https://api.jimeng.com/v1"
    JIMENG_MAX_DURATION: int = 12
    
    # OpenAI（用于剧本润色）
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4"
    OPENAI_VISION_MODEL: str = "gpt-4o-mini"

    # 项目级音频后处理链路
    AUDIO_PIPELINE_ENABLED: bool = False
    AUDIO_TTS_PROVIDER: str = "doubao-tts"
    AUDIO_SFX_PROVIDER: str = "local-library"
    AUDIO_AMBIENCE_PROVIDER: str = "local-library"
    AUDIO_MUSIC_PROVIDER: str = "local-library"
    AUDIO_LIBRARY_ROOT: str = "uploads/generated/pipeline/audio_library"
    AUDIO_LIBRARY_MANIFEST: str = ""
    AUDIO_SAMPLE_RATE: int = 48000
    AUDIO_CHANNELS: int = 2
    AUDIO_MASTER_CODEC: str = "aac"
    AUDIO_MASTER_BITRATE: str = "192k"
    
    # 视频生成默认配置
    DEFAULT_VIDEO_DURATION: int = 10
    DEFAULT_VIDEO_RESOLUTION: str = "1080p"
    DEFAULT_VIDEO_FPS: int = 30
    DEFAULT_VIDEO_STYLE: str = "realistic"
    
    # 异步任务队列配置（Celery）
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"
    CELERY_TASK_SERIALIZER: str = "json"
    CELERY_RESULT_SERIALIZER: str = "json"
    CELERY_ACCEPT_CONTENT: List[str] = ["json"]
    CELERY_TIMEZONE: str = "Asia/Shanghai"
    CELERY_ENABLE_UTC: bool = True
    CELERY_WORKER_CONCURRENCY: int = 4
    CELERY_TASK_SOFT_TIME_LIMIT: int = 300  # 5分钟
    CELERY_TASK_TIME_LIMIT: int = 600  # 10分钟
    CELERY_RENDER_TASK_SOFT_TIME_LIMIT: int = 3600  # 60分钟
    CELERY_RENDER_TASK_TIME_LIMIT: int = 3900  # 65分钟
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None
    MODEL_DEBUG_LOGGING: bool = False
    MODEL_DEBUG_MAX_CHARS: int = 20000
    
    # 安全配置
    SECRET_KEY: str = "change-me-in-production"
    ALLOWED_HOSTS: List[str] = ["*"]
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:5173"]
    
    # 限流配置
    RATE_LIMIT_ENABLED: bool = True
    RATE_LIMIT_REQUESTS: int = 100
    RATE_LIMIT_PERIOD: int = 60  # 60秒

    class Config:
        env_file = str(ENV_FILE_PATH)
        case_sensitive = True
        extra = 'ignore'  # 忽略未定义的环境变量

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value):
        if isinstance(value, bool):
            return value
        if value is None:
            return False
        normalized = str(value).strip().lower()
        if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
            return True
        if normalized in {"0", "false", "no", "off", "release", "prod", "production"}:
            return False
        raise ValueError("DEBUG must be a boolean-like value such as true/false/debug/release")

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_database_url(cls, value):
        if value is None:
            return value

        raw = str(value).strip()
        if not raw:
            return raw

        parsed = urlsplit(raw)
        if not parsed.scheme.startswith("mysql"):
            return raw

        hostname = parsed.hostname or ""
        if hostname != "localhost":
            return raw

        username = parsed.username or ""
        password = parsed.password or ""
        auth = username
        if password:
            auth = f"{auth}:{password}"
        host = "127.0.0.1"
        if parsed.port:
            host = f"{host}:{parsed.port}"
        netloc = f"{auth}@{host}" if auth else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    @field_validator("PIPELINE_RUNTIME_MODE", mode="before")
    @classmethod
    def normalize_pipeline_runtime_mode(cls, value):
        normalized = str(value or "minimal").strip().lower()
        aliases = {
            "full": "full",
            "complete": "full",
            "celery": "full",
            "minimal": "minimal",
            "local": "minimal",
            "standalone": "minimal",
            "single-process": "minimal",
            "single_process": "minimal",
        }
        if normalized not in aliases:
            raise ValueError("PIPELINE_RUNTIME_MODE must be one of: full, minimal")
        return aliases[normalized]

    @property
    def pipeline_uses_local_render_dispatch(self) -> bool:
        return self.PIPELINE_RUNTIME_MODE == "minimal"

    @property
    def pipeline_render_dispatch_mode(self) -> str:
        return "local" if self.pipeline_uses_local_render_dispatch else "celery"


# 全局配置实例
settings = Settings()
