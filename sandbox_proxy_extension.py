# -*- coding: utf-8 -*-
"""
SandboxManager 代理扩展

为 SandboxManager 添加 /sandbox/{sandbox_id}/fastapi/{path:path} 路由，
代理请求到容器内的 FastAPI 服务。

用法:
    runtime-sandbox-server --extension sandbox_proxy_extension.py
"""
import logging

import httpx
from fastapi import Request, HTTPException
from fastapi.responses import StreamingResponse, Response

# 导入 SandboxManager 的 app 和 manager
from agentscope_runtime.sandbox.manager.server.app import (
    app,
    get_sandbox_manager,
    verify_token,
)
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _get_container_info(sandbox_id: str) -> dict:
    """获取容器信息"""
    manager = get_sandbox_manager()
    container_json = manager.container_mapping.get(sandbox_id)
    if not container_json:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id} not found")
    return container_json


async def _proxy_request(
    sandbox_id: str,
    path: str,
    request: Request,
    method: str = "GET",
) -> Response:
    """代理请求到容器"""
    container_json = await _get_container_info(sandbox_id)
    
    base_url = container_json.get("url")
    if not base_url:
        raise HTTPException(status_code=404, detail="Container URL not found")
    
    runtime_token = container_json.get("runtime_token")
    target_url = f"{base_url}/fastapi/{path}"
    
    # 构建请求头
    headers = {
        "Content-Type": request.headers.get("Content-Type", "application/json"),
    }
    if runtime_token:
        headers["Authorization"] = f"Bearer {runtime_token}"
    
    try:
        body = await request.body()
        
        async with httpx.AsyncClient(timeout=3600.0) as client:
            if method == "GET":
                response = await client.get(target_url, headers=headers)
            else:
                response = await client.request(
                    method,
                    target_url,
                    headers=headers,
                    content=body,
                )
            
            return Response(
                content=response.content,
                status_code=response.status_code,
                media_type=response.headers.get("content-type"),
            )
    except httpx.RequestError as e:
        logger.error(f"Proxy request failed: {e}")
        raise HTTPException(status_code=502, detail=f"Upstream request failed: {str(e)}")


async def _proxy_stream(
    sandbox_id: str,
    path: str,
    request: Request,
) -> StreamingResponse:
    """代理 SSE 流式请求到容器"""
    container_json = await _get_container_info(sandbox_id)
    
    base_url = container_json.get("url")
    if not base_url:
        raise HTTPException(status_code=404, detail="Container URL not found")
    
    runtime_token = container_json.get("runtime_token")
    target_url = f"{base_url}/fastapi/{path}"
    
    headers = {
        "Content-Type": "application/json",
    }
    if runtime_token:
        headers["Authorization"] = f"Bearer {runtime_token}"
    
    body = await request.body()
    
    async def stream_generator():
        async with httpx.AsyncClient(timeout=3600.0) as client:
            async with client.stream(
                "POST",
                target_url,
                headers=headers,
                content=body,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    yield line + "\n"
    
    return StreamingResponse(
        stream_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# 注册代理路由
@app.api_route(
    "/sandbox/{sandbox_id}/fastapi/{path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
)
async def proxy_fastapi(
    sandbox_id: str,
    path: str,
    request: Request,
    token: HTTPAuthorizationCredentials = Depends(verify_token),
):
    """
    代理请求到容器内的 FastAPI 服务
    
    支持普通请求和 SSE 流式请求
    """
    method = request.method
    
    # 检查是否是 SSE 请求（通过 Accept 头或路径判断）
    accept = request.headers.get("Accept", "")
    if "text/event-stream" in accept or path == "run_kuncode":
        logger.info(f"Proxying SSE stream to sandbox {sandbox_id}: /{path}")
        return await _proxy_stream(sandbox_id, path, request)
    
    logger.info(f"Proxying {method} request to sandbox {sandbox_id}: /{path}")
    return await _proxy_request(sandbox_id, path, request, method)


logger.info("Sandbox FastAPI proxy extension loaded")
logger.info("Route registered: /sandbox/{sandbox_id}/fastapi/{path:path}")
