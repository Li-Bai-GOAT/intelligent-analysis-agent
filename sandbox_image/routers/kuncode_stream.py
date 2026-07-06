# -*- coding: utf-8 -*-
"""
KunCode SSE Streaming Router

提供 /run_kuncode 端点，支持流式输出 kuncode 执行结果。
参考 agentscope-runtime 代码风格实现。
"""

import asyncio
import logging
import os
from typing import Optional, List
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

router = APIRouter(tags=["kuncode"])


def _normalize_model_name(model: Optional[str]) -> Optional[str]:
    if model == "mimo-v2.5-pro":
        return "mimo/mimo-v2.5-pro"
    return model


def _normalize_agent_name(agent: Optional[str]) -> Optional[str]:
    if agent is None:
        return None
    normalized = str(agent).strip()
    if not normalized or normalized.lower() in {"none", "null", "undefined", "default"}:
        return None
    return normalized


class KunCodeRequest(BaseModel):
    """KunCode 执行请求参数"""
    prompt: str = Field(..., description="要执行的任务描述")
    agent: Optional[str] = Field(None, description="指定使用的智能体")
    model: Optional[str] = Field(None, description="覆盖默认模型")
    files: Optional[List[str]] = Field(None, description="附加的文件路径列表")
    continue_session: bool = Field(False, description="是否继续上次会话")
    session_id: Optional[str] = Field(None, description="指定会话 ID")
    output_format: str = Field("default", description="输出格式: default 或 json")


def _build_kuncode_command(request: KunCodeRequest) -> List[str]:
    """
    构建 kuncode 命令参数列表（安全方式，不经过 shell）
    
    Args:
        request: KunCode 请求参数
        
    Returns:
        命令参数列表，直接传给 subprocess，防止注入
    """
    cmd = ["kuncode", "run"]
    
    if request.continue_session:
        cmd.append("-c")
    
    if request.session_id:
        cmd.extend(["-s", request.session_id])
    
    agent = _normalize_agent_name(request.agent)
    if agent:
        cmd.extend(["--agent", agent])
    
    model = _normalize_model_name(request.model)
    if model:
        cmd.extend(["-m", model])
    
    if request.files:
        for file_path in request.files:
            cmd.extend(["-f", file_path])
    
    if request.output_format and request.output_format != "default":
        cmd.extend(["--format", request.output_format])
    
    # prompt 作为最后一个参数，作为独立参数传递，不经过 shell 解析
    cmd.append(request.prompt)
    
    return cmd


async def _stream_kuncode_output(cmd: List[str]):
    """
    异步流式执行 kuncode 命令并 yield SSE 格式输出
    
    真正的流式：每次解码出内容就立即发送 SSE 事件。
    使用 JSON 编码保留换行符等特殊字符。
    
    Args:
        cmd: 命令参数列表
        
    Yields:
        SSE 格式的输出
    """
    import codecs
    import json
    idle_timeout = int(os.getenv("KUNCODE_STREAM_IDLE_TIMEOUT", "300"))
    
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        started_message = "[KunCode] process started, waiting for model output...\n"
        yield f"data: {json.dumps(started_message)}\n\n"
        
        # 使用增量解码器，正确处理多字节 UTF-8 字符
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        
        while True:
            # 读取小块数据
            try:
                chunk = await asyncio.wait_for(process.stdout.read(64), timeout=idle_timeout)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()
                message = (
                    f"\n[ERROR] KunCode produced no output for {idle_timeout}s "
                    "and was stopped.\n"
                )
                yield f"data: {json.dumps(message)}\n\n"
                yield f"data: [ERROR] {message.strip()}\n\n"
                return
            if not chunk:
                # 处理解码器中剩余的字节
                remaining = decoder.decode(b"", final=True)
                if remaining:
                    # JSON 编码保留换行符
                    yield f"data: {json.dumps(remaining)}\n\n"
                break
            
            # 增量解码后立即发送，JSON 编码保留特殊字符
            text = decoder.decode(chunk)
            if text:
                yield f"data: {json.dumps(text)}\n\n"
        
        return_code = await process.wait()
        if return_code != 0:
            message = f"\n[ERROR] KunCode exited with code {return_code}.\n"
            yield f"data: {json.dumps(message)}\n\n"
            yield f"data: [ERROR] {message.strip()}\n\n"
            return
        
        # 发送完成标记
        yield "data: [DONE]\n\n"
        
    except Exception as e:
        logger.exception("KunCode execution failed")
        yield f"data: [ERROR] {str(e)}\n\n"


@router.post("/run_kuncode")
async def run_kuncode_stream(request: KunCodeRequest):
    """
    流式执行 KunCode 命令
    
    使用 Server-Sent Events (SSE) 实时返回 kuncode 输出。
    
    Args:
        request: KunCode 执行请求参数
        
    Returns:
        StreamingResponse: SSE 格式的流式响应
    """
    # 构建安全的命令参数列表
    cmd = _build_kuncode_command(request)
    
    logger.info(f"Starting KunCode stream: {' '.join(cmd[:3])}...")
    
    return StreamingResponse(
        _stream_kuncode_output(cmd),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用 nginx 缓冲
        },
    )


@router.get("/kuncode/health")
async def kuncode_health():
    """检查 kuncode 是否可用"""
    try:
        process = await asyncio.create_subprocess_exec(
            "kuncode", "--version",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await process.communicate()
        version = stdout.decode().strip()
        return {"status": "ok", "version": version}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"KunCode not available: {e}")
