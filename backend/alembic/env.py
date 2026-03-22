"""
Alembic 环境配置。

只加载当前仓库仍在使用的主链路模型，避免旧模块残留导致迁移失败。
"""

from __future__ import annotations

import re
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, inspect, pool, text

from app.core.config import settings
from app.db.base import Base, build_sync_database_url
from app.models import (
    PipelineCharacterProfile,
    PipelineProject,
    PipelineRenderTask,
    PipelineSceneProfile,
    User,
)

# 保持显式引用，确保 metadata 完整注册。
_ = (
    User,
    PipelineProject,
    PipelineCharacterProfile,
    PipelineSceneProfile,
    PipelineRenderTask,
)

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata
ALEMBIC_VERSION_LENGTH = 128


def get_url() -> str:
    return build_sync_database_url(settings.DATABASE_URL)


def ensure_alembic_version_capacity(connection) -> None:
    inspector = inspect(connection)
    table_names = set(inspector.get_table_names())

    if "alembic_version" not in table_names:
        connection.execute(
            text(
                f"CREATE TABLE alembic_version ("
                f"version_num VARCHAR({ALEMBIC_VERSION_LENGTH}) NOT NULL PRIMARY KEY"
                f")"
            )
        )
        return

    version_columns = {
        str(column.get("name") or ""): column
        for column in inspector.get_columns("alembic_version")
    }
    version_column = version_columns.get("version_num")
    if not version_column:
        return

    current_length = getattr(version_column.get("type"), "length", None)
    if current_length and int(current_length) >= ALEMBIC_VERSION_LENGTH:
        return

    if connection.dialect.name == "mysql":
        connection.execute(
            text(
                f"ALTER TABLE alembic_version "
                f"MODIFY COLUMN version_num VARCHAR({ALEMBIC_VERSION_LENGTH}) NOT NULL"
            )
        )
        return

    type_text = str(version_column.get("type") or "")
    match = re.search(r"\((\d+)\)", type_text)
    parsed_length = int(match.group(1)) if match else 0
    if parsed_length >= ALEMBIC_VERSION_LENGTH:
        return


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section) or {}
    configuration["sqlalchemy.url"] = get_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        ensure_alembic_version_capacity(connection)
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
