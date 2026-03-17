"""
模型基类模块
从数据库基础模块重新导出Base，供模型使用
"""
from app.db.base import Base

# 为了保持向后兼容，同时导出BaseModel别名
BaseModel = Base

__all__ = ["Base", "BaseModel"]
