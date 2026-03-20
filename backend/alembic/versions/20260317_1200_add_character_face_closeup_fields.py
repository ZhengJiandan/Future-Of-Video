"""
为主链路角色档案增加面部特写锚点字段

Revision ID: 20260317_1200_add_character_face_closeup_fields
Revises:
Create Date: 2026-03-17 12:00:00
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "20260317_1200_add_character_face_closeup_fields"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}

    if "face_closeup_image_url" not in columns:
        op.add_column("pipeline_character_profiles", sa.Column("face_closeup_image_url", sa.String(length=500), nullable=True))
    if "face_closeup_image_path" not in columns:
        op.add_column("pipeline_character_profiles", sa.Column("face_closeup_image_path", sa.String(length=500), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    columns = {column["name"] for column in inspector.get_columns("pipeline_character_profiles")}

    if "face_closeup_image_path" in columns:
        op.drop_column("pipeline_character_profiles", "face_closeup_image_path")
    if "face_closeup_image_url" in columns:
        op.drop_column("pipeline_character_profiles", "face_closeup_image_url")
