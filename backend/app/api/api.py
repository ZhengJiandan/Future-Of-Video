"""
API路由聚合
"""
from fastapi import APIRouter

# 当前只保留主链路 + 用户认证 + 当前项目草稿。
from app.api.endpoints import auth, project_state, script_pipeline

# 创建主路由
api_router = APIRouter()

# 注册用户和项目状态
api_router.include_router(auth.router, prefix="/auth", tags=["用户认证"])
api_router.include_router(project_state.router, prefix="/projects", tags=["项目草稿"])

# 注册主链路
api_router.include_router(script_pipeline.router, prefix="/pipeline", tags=["剧本流水线"])
