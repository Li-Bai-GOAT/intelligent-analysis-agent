# -*- coding: utf-8 -*-
"""
对话 API

提供智能体对话接口，支持 SSE 流式输出和异步任务
"""

import json
import re
from typing import Literal, Optional, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.models.user import User
from app.api.deps import get_current_user
from app.services.agent_service import AgentService
from app.services.postgres_session_history import PostgresSessionHistoryService
from app.repositories.session_repo import SessionRepository


router = APIRouter(prefix="/conversation", tags=["对话"])


async def _require_session_owner(user_id: str, session_id: str) -> None:
    """Ensure session-scoped endpoints cannot access another user's session."""
    session = await SessionRepository.get(user_id, session_id)
    if not session:
        # Avoid turning this endpoint into a session-ID enumeration oracle.
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")


class ChatRequest(BaseModel):
    """对话请求"""
    message: str
    session_id: str  # 必填，需先调用 POST /sessions 创建会话
    file_ids: Optional[List[str]] = None  # 携带的文件 ID 列表
    execution_mode: Literal["auto", "kuncode"] = "auto"


class CreateSessionResponse(BaseModel):
    """创建会话响应"""
    session_id: str
    user_id: str


class AsyncTaskResponse(BaseModel):
    """异步任务响应"""
    task_id: str
    session_id: str
    status: str = "pending"


@router.post("/sessions", response_model=CreateSessionResponse, summary="创建会话")
async def create_session(user: User = Depends(get_current_user)):
    """
    创建新会话。
    
    沙箱会在第一次对话时自动创建，无需预先创建。
    文件上传后会自动存储到沙箱挂载目录，无需手动同步。
    """
    user_id = str(user.id)
    
    # 创建会话
    session_service = PostgresSessionHistoryService()
    await session_service.start()
    session = await session_service.create_session(user_id=user_id)
    
    return CreateSessionResponse(
        session_id=session.id,
        user_id=session.user_id,
    )


@router.post("/chat", summary="发起对话")
async def chat(
    request: Request,
    data: ChatRequest,
    user: User = Depends(get_current_user),
):
    """
    与 AI 智能体进行对话，支持 SSE 流式输出。可携带文件 ID 列表，文件会自动同步到沙箱。
    
    返回 SSE 事件流:
    ```
    data: {"type": "thinking", "content": "..."}
    data: {"type": "text", "content": "..."}
    data: {"type": "tool_call", "content": "..."}
    data: {"type": "end", "content": "对话完成", "session_id": "..."}
    ```
    """
    await _require_session_owner(str(user.id), data.session_id)
    agent_service = AgentService.get_instance()
    
    async def event_generator():
        try:
            async for chunk in agent_service.chat(
                user_id=str(user.id),
                session_id=data.session_id,
                message=data.message,
                file_ids=data.file_ids,
                execution_mode=data.execution_mode,
            ):
                if await request.is_disconnected():
                    break
                yield f"data: {json.dumps(chunk, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )


class SessionTaskResponse(BaseModel):
    """会话任务状态响应"""
    session_id: str
    task_id: Optional[str] = None
    has_active_task: bool = False


@router.post("/async", response_model=AsyncTaskResponse, summary="提交异步任务")
async def submit_async_task(
    data: ChatRequest,
    user: User = Depends(get_current_user),
):
    """
    提交异步分析任务，适用于长时间运行的分析。
    返回 task_id 后，可通过 GET /api/conversation/stream/{task_id} 订阅实时输出。
    """
    await _require_session_owner(str(user.id), data.session_id)

    import platform
    from app.tasks import celery_analyze_task, start_local_task, _execute_analyze_task
    import uuid

    task_id = str(uuid.uuid4())
    request_dict = {
        "user_id": str(user.id),
        "session_id": data.session_id,
        "message": data.message,
        "file_ids": data.file_ids or [],
        "execution_mode": data.execution_mode,
    }

    # Register ownership and the active task before scheduling. A very fast
    # task may otherwise finish and clear the key before this endpoint writes
    # it, leaving a stale "active" task behind.
    agent_service = AgentService.get_instance()
    await agent_service.start()
    await agent_service.set_task_owner(task_id, str(user.id), data.session_id)
    await agent_service.set_session_task(data.session_id, task_id)

    # Windows 下使用本地执行器，非 Windows 使用 Celery
    if platform.system() == "Windows":
        # 启动本地后台任务（传入函数和参数，避免跨事件循环协程问题）
        start_local_task(
            _execute_analyze_task,
            request_dict,
            task_id,
            task_id=task_id,
        )
    else:
        # Celery 异步提交
        celery_analyze_task.apply_async(args=[request_dict], task_id=task_id)

    return AsyncTaskResponse(
        task_id=task_id,
        session_id=data.session_id,
        status="pending",
    )


@router.get("/session/{session_id}/task", response_model=SessionTaskResponse, summary="获取会话的活跃任务")
async def get_session_active_task(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """获取会话当前正在执行的任务ID，用于断点续传"""
    await _require_session_owner(str(user.id), session_id)
    agent_service = AgentService.get_instance()
    await agent_service.start()
    task_id = await agent_service.get_session_task(session_id)
    
    return SessionTaskResponse(
        session_id=session_id,
        task_id=task_id,
        has_active_task=bool(task_id),
    )


class InterruptResponse(BaseModel):
    """中断响应"""
    success: bool
    message: str


@router.post("/session/{session_id}/interrupt", response_model=InterruptResponse, summary="中断代理执行")
async def interrupt_session(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """中断当前会话中正在执行的代理，触发用户输入等待"""
    await _require_session_owner(str(user.id), session_id)
    agent_service = AgentService.get_instance()
    await agent_service.start()
    
    success = await agent_service.interrupt_agent(session_id, user_id=user.id)
    
    if success:
        return InterruptResponse(success=True, message="代理已中断，等待用户输入")
    else:
        return InterruptResponse(success=False, message="没有正在执行的代理或中断失败")


@router.get("/stream/{task_id}", summary="订阅任务流")
async def stream_task(
    task_id: str,
    request: Request,
    user: User = Depends(get_current_user),
):
    """订阅异步任务的 SSE 流式输出，用于获取 Celery 后台任务的实时结果"""
    agent_service = AgentService.get_instance()
    await agent_service.start()
    owner = await agent_service.get_task_owner(task_id)
    if not owner or owner["user_id"] != str(user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="任务不存在")

    last_event_id = request.headers.get("last-event-id", "0")
    if last_event_id != "0" and not re.fullmatch(r"\d+-\d+", last_event_id):
        last_event_id = "0"
    
    async def event_generator():
        try:
            async for data in agent_service.read_task_stream(task_id, last_id=last_event_id):
                if await request.is_disconnected():
                    break
                stream_id = data.pop("_stream_id", None)
                if stream_id:
                    yield f"id: {stream_id}\n"
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
    )
