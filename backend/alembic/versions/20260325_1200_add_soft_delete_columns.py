"""
为项目、角色档案、场景档案增加软删除字段

Revision ID: 20260325_1200_add_soft_delete_columns
Revises: 20260321_1100_add_character_voice_description
Create Date: 2026-03-25 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260325_1200_add_soft_delete_columns"
down_revision = "20260321_1100_add_character_voice_description"
branch_labels = None
depends_on = None


def _column_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {column["name"] for column in inspector.get_columns(table_name)}


def _index_names(table_name: str) -> set[str]:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    return {index["name"] for index in inspector.get_indexes(table_name)}


def upgrade():
    if "deleted_at" not in _column_names("pipeline_projects"):
        op.add_column("pipeline_projects", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    if "ix_pipeline_projects_deleted_at" not in _index_names("pipeline_projects"):
        op.create_index("ix_pipeline_projects_deleted_at", "pipeline_projects", ["deleted_at"])

    if "deleted_at" not in _column_names("pipeline_character_profiles"):
        op.add_column("pipeline_character_profiles", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    if "ix_pipeline_character_profiles_deleted_at" not in _index_names("pipeline_character_profiles"):
        op.create_index("ix_pipeline_character_profiles_deleted_at", "pipeline_character_profiles", ["deleted_at"])

    if "deleted_at" not in _column_names("pipeline_scene_profiles"):
        op.add_column("pipeline_scene_profiles", sa.Column("deleted_at", sa.DateTime(), nullable=True))
    if "ix_pipeline_scene_profiles_deleted_at" not in _index_names("pipeline_scene_profiles"):
        op.create_index("ix_pipeline_scene_profiles_deleted_at", "pipeline_scene_profiles", ["deleted_at"])


def downgrade():
    if "ix_pipeline_scene_profiles_deleted_at" in _index_names("pipeline_scene_profiles"):
        op.drop_index("ix_pipeline_scene_profiles_deleted_at", table_name="pipeline_scene_profiles")
    if "deleted_at" in _column_names("pipeline_scene_profiles"):
        op.drop_column("pipeline_scene_profiles", "deleted_at")

    if "ix_pipeline_character_profiles_deleted_at" in _index_names("pipeline_character_profiles"):
        op.drop_index("ix_pipeline_character_profiles_deleted_at", table_name="pipeline_character_profiles")
    if "deleted_at" in _column_names("pipeline_character_profiles"):
        op.drop_column("pipeline_character_profiles", "deleted_at")

    if "ix_pipeline_projects_deleted_at" in _index_names("pipeline_projects"):
        op.drop_index("ix_pipeline_projects_deleted_at", table_name="pipeline_projects")
    if "deleted_at" in _column_names("pipeline_projects"):
        op.drop_column("pipeline_projects", "deleted_at")
