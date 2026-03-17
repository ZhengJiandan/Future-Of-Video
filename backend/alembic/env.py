"""
Alembic环境配置
"""
from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

# 导入模型基类和所有模型
from app.db.base import Base
from app.models.user import User
from app.models.character import Character
from app.models.map import Map
from app.models.script import Script
from app.models.video_task import VideoTask
from app.models.video_segment import VideoSegment

# Alembic配置对象
config = context.config

# 配置日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# 设置目标元数据
target_metadata = Base.metadata


def get_url():
    """获取数据库URL"""
    from app.core.config import settings
    # 将异步URL转换为同步URL用于Alembic
    return settings.DATABASE_URL.replace("+aiomysql", "+pymysql")


def run_migrations_offline() -> None:
    """以离线模式运行迁移"""
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """以在线模式运行迁移"""
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection, 
            target_metadata=target_metadata,
            compare_type=True,  # 比较列类型
            compare_server_default=True,  # 比较默认值
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
