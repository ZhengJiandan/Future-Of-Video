"""
为角色档案增加语音绑定配置

Revision ID: 20260319_1600_add_character_voice_profile
Revises: 20260317_1500_add_pipeline_render_tasks
Create Date: 2026-03-19 16:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260319_1600_add_character_voice_profile"
down_revision = "20260317_1500_add_pipeline_render_tasks"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}
    if "voice_profile" not in columns:
        op.add_column("pipeline_character_profiles", sa.Column("voice_profile", sa.JSON(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}
    if "voice_profile" in columns:
        op.drop_column("pipeline_character_profiles", "voice_profile")
