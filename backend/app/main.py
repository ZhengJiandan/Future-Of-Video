"""
FastAPI应用主入口
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
import time
import os

from app.core.config import settings
from app.db import init_db, close_db
from app.api.api import api_router
from app.services.pipeline_workflow import pipeline_workflow_service

# 配置日志
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL),
    format=settings.LOG_FORMAT,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(settings.LOG_FILE) if settings.LOG_FILE else logging.NullHandler(),
    ]
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动时执行
    logger.info(
        "Starting %s v%s (pipeline_runtime_mode=%s render_dispatch=%s)",
        settings.APP_NAME,
        settings.APP_VERSION,
        settings.PIPELINE_RUNTIME_MODE,
        settings.pipeline_render_dispatch_mode,
    )
    
    # 初始化数据库
    try:
        await init_db()
        logger.info("Database initialized successfully")
    except Exception as e:
        logger.error(f"Database initialization failed: {e}")
        raise

    recovered = await pipeline_workflow_service.recover_interrupted_tasks()
    for task_id in recovered.get("task_ids", []):
        try:
            await pipeline_workflow_service.start_render_task(task_id, mark_failed_on_enqueue_error=False)
        except Exception as exc:
            logger.error("Failed to restart recovered render task %s: %s", task_id, exc, exc_info=True)
    if (
        recovered.get("requeued")
        or recovered.get("reset_processing")
        or recovered.get("recovered_queued")
        or recovered.get("recovered_dispatching")
    ):
        logger.warning(
            "Render task recovery on startup: requeued=%s reset_processing=%s recovered_queued=%s recovered_dispatching=%s",
            recovered.get("requeued", 0),
            recovered.get("reset_processing", 0),
            recovered.get("recovered_queued", 0),
            recovered.get("recovered_dispatching", 0),
        )
    
    # 创建上传目录
    upload_dir = settings.UPLOAD_DIR
    if not os.path.exists(upload_dir):
        os.makedirs(upload_dir)
        logger.info(f"Created upload directory: {upload_dir}")
    
    yield
    
    # 关闭时执行
    logger.info(f"Shutting down {settings.APP_NAME}")
    
    # 关闭数据库连接
    try:
        await close_db()
        logger.info("Database connections closed")
    except Exception as e:
        logger.error(f"Error closing database: {e}")


# 创建FastAPI应用
app = FastAPI(
    title=settings.APP_NAME,
    description="future of video，面向完整创作链路的 AI 视频生成系统。",
    version=settings.APP_VERSION,
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
    lifespan=lifespan,
)

# 挂载当前保留的主链路 API
app.include_router(api_router, prefix="/api/v1")

# 配置CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# 请求日志中间件
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """记录所有HTTP请求"""
    start_time = time.time()
    
    # 获取请求信息
    client_host = request.client.host if request.client else "unknown"
    method = request.method
    url = request.url.path
    
    logger.debug(f"Request started: {method} {url} from {client_host}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        logger.info(
            f"Request completed: {method} {url} - {response.status_code} - {process_time:.3f}s"
        )
        
        # 添加响应时间头
        response.headers["X-Process-Time"] = str(process_time)
        return response
        
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed: {method} {url} - {str(e)} - {process_time:.3f}s")
        raise


# 全局异常处理
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """全局异常处理器"""
    logger.error(f"Global exception: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "message": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "Please contact support"
        }
    )


# 健康检查端点
@app.get("/health", tags=["system"])
async def health_check():
    """健康检查端点"""
    return {
        "status": "healthy",
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "environment": settings.ENV,
        "pipeline_runtime_mode": settings.PIPELINE_RUNTIME_MODE,
        "pipeline_render_dispatch_mode": settings.pipeline_render_dispatch_mode,
        "timestamp": time.time()
    }


# 根路径
@app.get("/", tags=["system"])
async def root():
    """根路径，返回应用信息"""
    return {
        "app_name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "description": "future of video，面向完整创作链路的 AI 视频生成系统。",
        "docs_url": "/docs",
        "health_check": "/health",
        "pipeline_runtime_mode": settings.PIPELINE_RUNTIME_MODE,
        "pipeline_render_dispatch_mode": settings.pipeline_render_dispatch_mode,
    }


# 静态文件服务
if not os.path.exists(settings.UPLOAD_DIR):
    os.makedirs(settings.UPLOAD_DIR)
app.mount("/uploads", StaticFiles(directory=settings.UPLOAD_DIR), name="uploads")


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        workers=settings.WORKERS,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower()
    )
