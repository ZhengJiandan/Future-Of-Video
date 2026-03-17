"""
基础Pydantic模型
"""
from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


class BaseSchema(BaseModel):
    """基础Schema"""
    model_config = ConfigDict(from_attributes=True)


class TimeStampSchema(BaseSchema):
    """带时间戳的基础Schema"""
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ResponseSchema(BaseSchema):
    """统一响应Schema"""
    success: bool = True
    message: str = "操作成功"
    data: Optional[dict] = None


class PaginationSchema(BaseSchema):
    """分页Schema"""
    page: int = 1
    page_size: int = 20
    total: int = 0
    pages: int = 0
