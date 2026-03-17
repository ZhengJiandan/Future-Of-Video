"""
添加角色标准参考图字段

Revision ID: 20250313_2000
Revises: 
Create Date: 2025-03-13 20:00:00

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision = '20250313_2000_add_character_reference_fields'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    """添加角色标准参考图相关字段"""
    
    # 添加标准参考图相关字段
    op.add_column('characters', sa.Column('standard_reference_image_url', sa.String(500), nullable=True, comment='标准参考图访问URL'))
    op.add_column('characters', sa.Column('standard_reference_image_path', sa.String(500), nullable=True, comment='标准参考图本地存储路径'))
    op.add_column('characters', sa.Column('standard_reference_prompt', sa.Text, nullable=True, comment='生成此参考图使用的prompt'))
    op.add_column('characters', sa.Column('visual_features', sa.JSON, nullable=True, comment='可视化特征标签，如 {"hair_color": "black", "uniform": "tactical green"}'))
    op.add_column('characters', sa.Column('is_custom_reference', sa.Integer, default=0, comment='是否是用户自定义上传（0=自动生成，1=用户上传）'))
    op.add_column('characters', sa.Column('reference_created_at', sa.DateTime, nullable=True, comment='参考图生成时间'))
    op.add_column('characters', sa.Column('reference_updated_at', sa.DateTime, nullable=True, comment='参考图更新时间'))
    
    # 创建索引以优化查询
    op.create_index('idx_characters_reference', 'characters', ['is_custom_reference', 'reference_created_at'])
    
    print("✅ 成功添加角色标准参考图相关字段")


def downgrade():
    """回滚删除字段"""
    
    # 删除索引
    op.drop_index('idx_characters_reference', 'characters')
    
    # 删除字段
    columns_to_drop = [
        'standard_reference_image_url',
        'standard_reference_image_path',
        'standard_reference_prompt',
        'visual_features',
        'is_custom_reference',
        'reference_created_at',
        'reference_updated_at'
    ]
    
    for column in columns_to_drop:
        try:
            op.drop_column('characters', column)
            print(f"✅ 成功删除字段: {column}")
        except Exception as e:
            print(f"⚠️ 删除字段 {column} 失败: {e}")
    
    print("✅ 回滚完成")
