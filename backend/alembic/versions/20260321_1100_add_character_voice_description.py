"""
为角色档案增加音色描述字段

Revision ID: 20260321_1100_add_character_voice_description
Revises: 20260319_1600_add_character_voice_profile
Create Date: 2026-03-21 11:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260321_1100_add_character_voice_description"
down_revision = "20260319_1600_add_character_voice_profile"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}
    if "voice_description" not in columns:
        op.add_column("pipeline_character_profiles", sa.Column("voice_description", sa.Text(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}
    if "voice_description" in columns:
        op.drop_column("pipeline_character_profiles", "voice_description")
