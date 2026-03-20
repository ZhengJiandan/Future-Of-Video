"""
新增渲染任务持久化表

Revision ID: 20260317_1500_add_pipeline_render_tasks
Revises: 20260317_1200_add_character_face_closeup_fields
Create Date: 2026-03-17 15:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260317_1500_add_pipeline_render_tasks"
down_revision = "20260317_1200_add_character_face_closeup_fields"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "pipeline_render_tasks" not in tables:
        op.create_table(
            "pipeline_render_tasks",
            sa.Column("id", sa.String(length=50), primary_key=True, nullable=False),
            sa.Column("user_id", sa.String(length=50), nullable=False),
            sa.Column("project_id", sa.String(length=50), nullable=True),
            sa.Column("project_title", sa.String(length=255), nullable=False),
            sa.Column("segments", sa.JSON(), nullable=False),
            sa.Column("keyframes", sa.JSON(), nullable=False),
            sa.Column("character_profiles", sa.JSON(), nullable=False),
            sa.Column("scene_profiles", sa.JSON(), nullable=False),
            sa.Column("render_config", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="queued"),
            sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
            sa.Column("current_step", sa.String(length=255), nullable=False, server_default="等待开始"),
            sa.Column("renderer", sa.String(length=100), nullable=False, server_default="pending"),
            sa.Column("clips", sa.JSON(), nullable=False),
            sa.Column("final_output", sa.JSON(), nullable=False),
            sa.Column("fallback_used", sa.Boolean(), nullable=False, server_default=sa.text("0")),
            sa.Column("warnings", sa.JSON(), nullable=False),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
        )

    indexes = {item["name"] for item in inspector.get_indexes("pipeline_render_tasks")}
    if "ix_pipeline_render_tasks_user_id" not in indexes:
        op.create_index("ix_pipeline_render_tasks_user_id", "pipeline_render_tasks", ["user_id"])
    if "ix_pipeline_render_tasks_project_id" not in indexes:
        op.create_index("ix_pipeline_render_tasks_project_id", "pipeline_render_tasks", ["project_id"])
    if "ix_pipeline_render_tasks_status" not in indexes:
        op.create_index("ix_pipeline_render_tasks_status", "pipeline_render_tasks", ["status"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "pipeline_render_tasks" not in tables:
        return

    indexes = {item["name"] for item in inspector.get_indexes("pipeline_render_tasks")}
    if "ix_pipeline_render_tasks_status" in indexes:
        op.drop_index("ix_pipeline_render_tasks_status", table_name="pipeline_render_tasks")
    if "ix_pipeline_render_tasks_project_id" in indexes:
        op.drop_index("ix_pipeline_render_tasks_project_id", table_name="pipeline_render_tasks")
    if "ix_pipeline_render_tasks_user_id" in indexes:
        op.drop_index("ix_pipeline_render_tasks_user_id", table_name="pipeline_render_tasks")
    op.drop_table("pipeline_render_tasks")
