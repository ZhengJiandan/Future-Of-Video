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

# 同步引擎（用于Alembic迁移）
sync_engine = create_engine(
    settings.DATABASE_URL.replace("+aiomysql", "+pymysql"),
    pool_pre_ping=True,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG
)

SyncSessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=sync_engine
)

# 异步引擎（用于应用运行时）
async_engine = create_async_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    pool_size=settings.DATABASE_POOL_SIZE,
    max_overflow=settings.DATABASE_MAX_OVERFLOW,
    echo=settings.DEBUG
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
        for column_name, ddl in CHARACTER_PROFILE_COMPAT_COLUMNS.items():
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
                    "table_name": "pipeline_character_profiles",
                    "column_name": column_name,
                },
            )
            exists = int(result.scalar() or 0) > 0
            if not exists:
                logger.warning("Auto-migrating missing column: pipeline_character_profiles.%s", column_name)
                await conn.execute(text(ddl))
        return

    if settings.DATABASE_URL.startswith("sqlite"):
        result = await conn.execute(text("PRAGMA table_info('pipeline_character_profiles')"))
        existing_columns = {str(row[1]) for row in result.fetchall()}
        if "face_closeup_image_url" not in existing_columns:
            logger.warning("Auto-migrating missing column: pipeline_character_profiles.face_closeup_image_url")
            await conn.execute(text("ALTER TABLE pipeline_character_profiles ADD COLUMN face_closeup_image_url VARCHAR(500)"))
        if "face_closeup_image_path" not in existing_columns:
            logger.warning("Auto-migrating missing column: pipeline_character_profiles.face_closeup_image_path")
            await conn.execute(text("ALTER TABLE pipeline_character_profiles ADD COLUMN face_closeup_image_path VARCHAR(500)"))
