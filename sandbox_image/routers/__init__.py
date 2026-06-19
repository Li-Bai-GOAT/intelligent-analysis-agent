# -*- coding: utf-8 -*-
"""
Routers for the data analysis sandbox.
保留原有 routers，增加 kuncode 流式路由。
"""
from .generic import generic_router
from .mcp import mcp_router
from .runtime_watcher import watcher_router
from .workspace import workspace_router
from .kuncode_stream import router as kuncode_router

__all__ = [
    "mcp_router",
    "generic_router",
    "watcher_router",
    "workspace_router",
    "kuncode_router",
]
