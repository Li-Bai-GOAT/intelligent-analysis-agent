# -*- coding: utf-8 -*-
"""
API 路由层
"""

from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.sessions import router as sessions_router
from app.api.knowledge import router as knowledge_router
from app.api.conversation import router as conversation_router
from app.api.files import router as files_router
from app.api.plans import router as plans_router
from app.api.kuncode import router as kuncode_router
from app.api.system_prompt import router as system_prompt_router
from app.api.sandbox import router as sandbox_router

api_router = APIRouter(prefix="/api")
api_router.include_router(auth_router)
api_router.include_router(sessions_router)
api_router.include_router(knowledge_router)
api_router.include_router(conversation_router)
api_router.include_router(files_router)
api_router.include_router(plans_router)
api_router.include_router(kuncode_router)
api_router.include_router(system_prompt_router)
api_router.include_router(sandbox_router)

__all__ = ["api_router"]
