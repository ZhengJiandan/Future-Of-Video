"""
数据库基础配置
"""
from urllib.parse import urlparse

from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)

# 创建声明性基类
Base = declarative_base()

def build_sync_database_url(database_url: str) -> str:
    if database_url.startswith("sqlite+aiosqlite"):
        return database_url.replace("+aiosqlite", "", 1)
    if database_url.startswith("mysql+aiomysql"):
        return database_url.replace("+aiomysql", "+pymysql", 1)
    return database_url


def build_sync_engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "echo": settings.DEBUG,
        }
    return {
        "pool_pre_ping": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "echo": settings.DEBUG,
    }


def build_async_engine_kwargs(database_url: str) -> dict:
    if database_url.startswith("sqlite"):
        return {
            "connect_args": {"check_same_thread": False},
            "echo": settings.DEBUG,
        }
    return {
        "pool_pre_ping": True,
        "pool_size": settings.DATABASE_POOL_SIZE,
        "max_overflow": settings.DATABASE_MAX_OVERFLOW,
        "echo": settings.DEBUG,
    }


# 同步引擎（用于Alembic迁移）
sync_engine = create_engine(
    build_sync_database_url(settings.DATABASE_URL),
    **build_sync_engine_kwargs(settings.DATABASE_URL),
)

SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)

# 异步引擎（用于应用运行时）
async_engine = create_async_engine(
    settings.DATABASE_URL,
    **build_async_engine_kwargs(settings.DATABASE_URL),
)

AsyncSessionLocal = sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)


CHARACTER_PROFILE_COMPAT_COLUMNS = {
    "face_closeup_image_url": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `face_closeup_image_url` VARCHAR(500) NULL AFTER `three_view_prompt`",
    "face_closeup_image_path": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `face_closeup_image_path` VARCHAR(500) NULL AFTER `face_closeup_image_url`",
    "voice_description": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `voice_description` TEXT NULL AFTER `emotion_baseline`",
    "kling_subject_id": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `kling_subject_id` VARCHAR(100) NULL AFTER `voice_profile`",
    "kling_subject_name": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `kling_subject_name` VARCHAR(255) NULL AFTER `kling_subject_id`",
    "kling_subject_status": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `kling_subject_status` VARCHAR(100) NULL AFTER `kling_subject_name`",
    "deleted_at": "ALTER TABLE `pipeline_character_profiles` ADD COLUMN `deleted_at` DATETIME NULL AFTER `face_closeup_image_path`",
}

PROJECT_COMPAT_COLUMNS = {
    "deleted_at": "ALTER TABLE `pipeline_projects` ADD COLUMN `deleted_at` DATETIME NULL AFTER `summary`",
}

SCENE_PROFILE_COMPAT_COLUMNS = {
    "deleted_at": "ALTER TABLE `pipeline_scene_profiles` ADD COLUMN `deleted_at` DATETIME NULL AFTER `reference_image_original_name`",
}


async def get_db() -> AsyncSession:
    """获取数据库会话的依赖函数"""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception as e:
            await session.rollback()
            logger.error(f"Database session error: {e}")
            raise
        finally:
            await session.close()


def get_sync_db():
    """获取同步数据库会话（用于Alembic迁移）"""
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


async def init_db():
    """初始化数据库，创建所有表"""
    try:
        async with async_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            await _ensure_schema_compatibility(conn)
        logger.info("Database initialized successfully")
    except OperationalError as e:
        parsed = urlparse(settings.DATABASE_URL)
        host = parsed.hostname or ""
        port = parsed.port or ""
        if parsed.scheme.startswith("mysql"):
            logger.error(
                "Database initialization failed for MySQL host=%s port=%s db=%s. "
                "If mysqld only listens on 127.0.0.1, do not use localhost in DATABASE_URL.",
                host,
                port,
                parsed.path.lstrip("/"),
            )
        logger.error(f"Database initialization failed: {e}")
        raise
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise


async def close_db():
    """关闭数据库连接"""
    try:
        await async_engine.dispose()
        sync_engine.dispose()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database connections: {e}")


async def _ensure_schema_compatibility(conn: AsyncSession) -> None:
    """为旧版本数据库自动补齐新增但可兼容的字段。"""
    if settings.DATABASE_URL.startswith("mysql"):
        compat_columns = {
            "pipeline_projects": PROJECT_COMPAT_COLUMNS,
            "pipeline_character_profiles": CHARACTER_PROFILE_COMPAT_COLUMNS,
            "pipeline_scene_profiles": SCENE_PROFILE_COMPAT_COLUMNS,
        }
        for table_name, columns in compat_columns.items():
            for column_name, ddl in columns.items():
                result = await conn.execute(
                    text(
                        """
                        SELECT COUNT(*)
                        FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = :table_name
                          AND COLUMN_NAME = :column_name
                        """
                    ),
                    {
                        "table_name": table_name,
                        "column_name": column_name,
                    },
                )
                exists = int(result.scalar() or 0) > 0
                if not exists:
                    logger.warning("Auto-migrating missing column: %s.%s", table_name, column_name)
                    await conn.execute(text(ddl))
        return

    if settings.DATABASE_URL.startswith("sqlite"):
        sqlite_compat_columns = {
            "pipeline_projects": {
                "deleted_at": "ALTER TABLE pipeline_projects ADD COLUMN deleted_at DATETIME",
            },
            "pipeline_character_profiles": {
                "face_closeup_image_url": "ALTER TABLE pipeline_character_profiles ADD COLUMN face_closeup_image_url VARCHAR(500)",
                "face_closeup_image_path": "ALTER TABLE pipeline_character_profiles ADD COLUMN face_closeup_image_path VARCHAR(500)",
                "voice_description": "ALTER TABLE pipeline_character_profiles ADD COLUMN voice_description TEXT",
                "kling_subject_id": "ALTER TABLE pipeline_character_profiles ADD COLUMN kling_subject_id VARCHAR(100)",
                "kling_subject_name": "ALTER TABLE pipeline_character_profiles ADD COLUMN kling_subject_name VARCHAR(255)",
                "kling_subject_status": "ALTER TABLE pipeline_character_profiles ADD COLUMN kling_subject_status VARCHAR(100)",
                "deleted_at": "ALTER TABLE pipeline_character_profiles ADD COLUMN deleted_at DATETIME",
            },
            "pipeline_scene_profiles": {
                "deleted_at": "ALTER TABLE pipeline_scene_profiles ADD COLUMN deleted_at DATETIME",
            },
        }
        for table_name, columns in sqlite_compat_columns.items():
            result = await conn.execute(text(f"PRAGMA table_info('{table_name}')"))
            existing_columns = {str(row[1]) for row in result.fetchall()}
            for column_name, ddl in columns.items():
                if column_name not in existing_columns:
                    logger.warning("Auto-migrating missing column: %s.%s", table_name, column_name)
                    await conn.execute(text(ddl))
