"""
核心配置文件 - 开发测试版（使用SQLite）
"""
from pydantic_settings import BaseSettings
from typing import List, Optional
import os
from pathlib import Path


ENV_FILE_PATH = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    """应用配置类"""
    
    # 应用基础配置
    APP_NAME: str = "三角洲视频生成系统"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = True  # 开发模式开启
    ENV: str = "development"
    
    # 服务器配置
    HOST: str = "0.0.0.0"
    PORT: int = 8080  # 修改为8080，避免8000端口被占用
    WORKERS: int = 1
    
    # 数据库配置 - 使用 MySQL
    # URL 格式: mysql+aiomysql://用户名:密码@主机:端口/数据库名
    # 注意: 密码中的 @ 需要替换为 %40
    DATABASE_URL: str = "mysql+aiomysql://delta_user:Delta123456@localhost:3306/delta_force_video"
    # 开发测试可使用 SQLite：sqlite+aiosqlite:///./delta_force_video.db
    DATABASE_POOL_SIZE: int = 20
    DATABASE_MAX_OVERFLOW: int = 10
    
    # Redis配置 - 开发模式可选
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_POOL_SIZE: int = 50
    
    # JWT认证配置
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 1天
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    
    # 文件上传配置
    UPLOAD_DIR: str = "uploads"
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    ALLOWED_IMAGE_TYPES: List[str] = ["image/jpeg", "image/png", "image/webp"]
    ALLOWED_VIDEO_TYPES: List[str] = ["video/mp4", "video/webm"]
    
    # AI视频生成服务配置
    # 可灵AI
    KELING_API_KEY: Optional[str] = None
    KELING_BASE_URL: str = "https://api.kelingai.com/v1"

    # NanoBanana 关键帧生成
    NANOBANANA_API_KEY: Optional[str] = "sk-Pyi0dVMauiJVvmOW5aD80eD5B4E1477886Bc8a83A24eAbCa"
    NANOBANANA_BASE_URL: str = "https://api.laozhang.ai/v1beta/models/gemini-3-pro-image-preview:generateContent"
    ALLOW_PLACEHOLDER_KEYFRAMES: bool = True
    
    # 豆包大模型API配置（用于剧本分析）
    DOUBAO_API_KEY: Optional[str] = None
    DOUBAO_BASE_URL: str = "https://ark.cn-beijing.volces.com/api/v3"
    DOUBAO_MODEL: str = "doubao-seed-2-0-lite-260215"
    DOUBAO_VIDEO_MODEL: str = "doubao-seedance-1-5-pro-251215"
    KELING_MAX_DURATION: int = 10
    
    # 即梦AI
    JIMENG_API_KEY: Optional[str] = None
    JIMENG_BASE_URL: str = "https://api.jimeng.com/v1"
    JIMENG_MAX_DURATION: int = 12
    
    # OpenAI（用于剧本润色）
    OPENAI_API_KEY: Optional[str] = None
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL: str = "gpt-4"
    
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
    
    # 日志配置
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_FILE: Optional[str] = None
    
    # 安全配置
    SECRET_KEY: str = "your-secret-key-change-in-production"
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


# 全局配置实例
settings = Settings()
