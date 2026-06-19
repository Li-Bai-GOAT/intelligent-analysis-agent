# -*- coding: utf-8 -*-
"""
Custom app.py for Data Analysis Sandbox

基于 agentscope-runtime 原生 app.py，增加 kuncode SSE 流式路由。
保持原有功能不变。
"""
import logging

from fastapi import FastAPI, Response, Depends
from routers import (
    generic_router,
    mcp_router,
    watcher_router,
    workspace_router,
)
from dependencies import verify_secret_token

# 导入自定义 kuncode 流式路由
try:
    from routers.kuncode_stream import router as kuncode_router
    KUNCODE_ROUTER_AVAILABLE = True
except ImportError:
    KUNCODE_ROUTER_AVAILABLE = False

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AgentScope Runtime Sandbox Server",
    version="1.0",
    description="Agentscope runtime sandbox server with KunCode streaming support.",
)


@app.get(
    "/healthz",
    summary="Check the health of the API",
    dependencies=[Depends(verify_secret_token)],
)
async def healthz():
    return Response(content="OK", status_code=200)


# 注册原有路由
app.include_router(mcp_router, dependencies=[Depends(verify_secret_token)])
app.include_router(generic_router, dependencies=[Depends(verify_secret_token)])
app.include_router(watcher_router, dependencies=[Depends(verify_secret_token)])
app.include_router(
    workspace_router,
    dependencies=[Depends(verify_secret_token)],
)

# 注册 KunCode SSE 流式路由
if KUNCODE_ROUTER_AVAILABLE:
    app.include_router(kuncode_router, dependencies=[Depends(verify_secret_token)])
    logger.info("KunCode streaming router registered")
else:
    logger.warning("KunCode streaming router not available")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000, workers=1)
