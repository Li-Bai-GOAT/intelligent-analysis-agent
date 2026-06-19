# -*- coding: utf-8 -*-
"""
FastAPI 应用入口

统一入口，包含：
- 用户认证 API
- 会话管理 API
- 知识库 CRUD API
- 智能体对话 API（SSE 流式）
"""

import os
os.environ.setdefault("RUNTIME_SANDBOX_TIMEOUT", "7200")

import logging
from contextlib import asynccontextmanager

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# 禁用 watchfiles 的无用日志
logging.getLogger("watchfiles.main").setLevel(logging.WARNING)

from app.config import settings
from app.database import init_db, close_db
from app.api import api_router
from app.services.agent_service import AgentService


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    # 启动数据库
    await init_db()
    print(f"[Database] PostgreSQL 已连接: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    
    # 启动智能体服务
    agent_service = AgentService.get_instance()
    await agent_service.start()
    
    yield
    
    # 关闭智能体服务
    await agent_service.stop()
    
    # 关闭数据库
    await close_db()
    print("[App] 服务已停止")


def create_app() -> FastAPI:
    """创建 FastAPI 应用"""
    app = FastAPI(
        title=settings.APP_NAME,
        description="数据分析智能体 - 统一 API 服务",
        version="1.0.0",
        lifespan=lifespan,
    )
    
    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    
    # 注册 API 路由
    app.include_router(api_router)
    
    # 健康检查
    @app.get("/health")
    async def health():
        agent_service = AgentService.get_instance()
        return {
            "status": "ok",
            "service": "rca-agent",
            "agent_ready": agent_service._started,
        }
    
    # 静态文件服务
    frontend_dir = Path(__file__).parent.parent / "frontend"
    if frontend_dir.exists():
        app.mount("/css", StaticFiles(directory=frontend_dir / "css"), name="css")
        app.mount("/js", StaticFiles(directory=frontend_dir / "js"), name="js")
        
        @app.get("/")
        async def serve_index():
            return FileResponse(frontend_dir / "index.html")
        
        @app.get("/html-editor.html")
        async def serve_html_editor():
            return FileResponse(frontend_dir / "html-editor.html")
    
    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    
    print("=" * 60)
    print("数据分析智能体 - 统一 API 服务")
    print("=" * 60)
    print(f"服务地址: http://{settings.APP_HOST}:{settings.APP_PORT}")
    print(f"API 文档: http://{settings.APP_HOST}:{settings.APP_PORT}/docs")
    print("-" * 60)
    print("接口说明:")
    print("  POST /api/auth/register     - 用户注册")
    print("  POST /api/auth/login        - 用户登录")
    print("  POST /api/conversation/chat - 智能体对话 (SSE)")
    print("  GET  /api/sessions          - 历史会话")
    print("  CRUD /api/knowledge         - 知识库管理")
    print("=" * 60)
    
    uvicorn.run(
        "app.main:app",
        host=settings.APP_HOST,
        port=settings.APP_PORT,
        reload=False,
        reload_excludes=["logs/*", "*.log", "sessions_mount_dir/*", "__pycache__/*", ".git/*"],
    )
