# -*- coding: utf-8 -*-
"""
Celery 异步任务

用于长时间运行的分析任务
"""

import asyncio
import logging
from typing import Dict, Any

from celery import Celery

from app.config import settings
from app.database import init_db
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)


# Celery 应用
celery_app = Celery(
    "rca_tasks",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_BACKEND_URL,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 任务结果过期时间（自动清理）
    result_expires=settings.CELERY_RESULT_EXPIRES,
    # 任务超时设置
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    # 任务确认：任务完成后才确认，防止 Worker 崩溃丢失任务
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # 路由
    task_routes={
        "app.tasks.analyze_task": {"queue": "rca_tasks"},
        "app.tasks.auto_continue_task": {"queue": "rca_tasks"},
    },
)


def _run_async(coro):
    """在 Celery Worker 中安全运行异步函数"""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@celery_app.task(bind=True, name="app.tasks.analyze_task", queue="rca_tasks")
def analyze_task(self, request_dict: Dict[str, Any]):
    """
    Celery 异步分析任务
    
    Args:
        request_dict: {
            "user_id": str,
            "session_id": str (optional),
            "message": str
        }
    """
    task_id = self.request.id
    return _run_async(_execute_analyze_task(request_dict, task_id))


async def _execute_analyze_task(request_dict: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    """执行分析任务"""
    user_id = request_dict.get("user_id", "anonymous")
    session_id = request_dict.get("session_id")
    message = request_dict.get("message", "")
    file_ids = request_dict.get("file_ids", [])
    
    if not message:
        return {"success": False, "error": "未提供任务内容"}
    
    # 初始化数据库和服务
    await init_db()
    agent_service = AgentService.get_instance()
    await agent_service.start()
    
    try:
        await agent_service.write_task_stream(task_id, {"type": "status", "content": "任务开始"}, session_id)
        
        final_result = None
        async for chunk in agent_service.chat(
            user_id=user_id,
            session_id=session_id,
            message=message,
            file_ids=file_ids,
        ):
            await agent_service.write_task_stream(task_id, chunk, session_id)
            if chunk.get("type") == "end":
                final_result = chunk
                break
        
        # 任务完成，清除会话任务映射
        if session_id:
            await agent_service.clear_session_task(session_id)
        
        return {
            "success": True,
            "session_id": final_result.get("session_id") if final_result else session_id,
            "task_id": task_id,
        }
    
    except Exception as e:
        await agent_service.write_task_stream(task_id, {"type": "error", "content": str(e)}, session_id)
        await agent_service.write_task_stream(task_id, {"type": "end", "content": "任务失败"}, session_id)
        # 任务失败也清除会话任务映射
        if session_id:
            await agent_service.clear_session_task(session_id)
        return {"success": False, "error": str(e)}


@celery_app.task(bind=True, name="app.tasks.auto_continue_task", queue="rca_tasks")
def auto_continue_task(self, session_id: str, user_id: str, preview_id: str):
    """
    自动继续任务 - 计划未完成超时后自动发送"继续"消息
    
    Args:
        session_id: 会话ID
        user_id: 用户ID
        preview_id: 预览ID（用于验证是否是同一个 auto_continue）
    """
    return _run_async(_execute_auto_continue(session_id, user_id, preview_id, self.request.id))


async def _execute_auto_continue(session_id: str, user_id: str, preview_id: str, task_id: str) -> Dict[str, Any]:
    """执行自动继续"""
    import json
    from app.api.kuncode import _get_redis, _get_auto_continue_key
    
    redis = await _get_redis()
    try:
        # 先检查是否有活跃任务正在运行，有任务运行时不触发自动继续
        active_task_key = f"session_task:{session_id}"
        active_task = await redis.get(active_task_key)
        if active_task:
            logger.info(f"会话有活跃任务运行中，跳过自动继续: {session_id}")
            return {"success": False, "reason": "active_task_running"}
        
        # 检查 auto_continue 状态是否仍然是 pending 且 preview_id 匹配
        key = _get_auto_continue_key(session_id)
        data = await redis.get(key)
        
        if not data:
            logger.info(f"自动继续已被清除，跳过: {session_id}")
            return {"success": False, "reason": "cleared"}
        
        pending = json.loads(data)
        
        # 检查是否是同一个 auto_continue 且仍然是 pending
        if pending.get("preview_id") != preview_id:
            logger.info(f"preview_id 不匹配，跳过: {session_id}")
            return {"success": False, "reason": "preview_id_mismatch"}
        
        if pending.get("status") != "pending":
            logger.info(f"自动继续已被用户处理 ({pending.get('status')})，跳过: {session_id}")
            return {"success": False, "reason": pending.get("status")}
        
        # 标记为自动继续，保存 task_id 以便前端重连
        pending["status"] = "auto_triggered"
        pending["task_id"] = task_id
        await redis.set(key, json.dumps(pending), ex=300)
    finally:
        await redis.close()
    
    logger.info(f"自动继续触发: {session_id}")
    
    # 初始化数据库和服务
    await init_db()
    agent_service = AgentService.get_instance()
    await agent_service.start()
    
    try:
        await agent_service.write_task_stream(task_id, {"type": "status", "content": "自动继续执行"}, session_id)
        
        async for chunk in agent_service.chat(
            user_id=user_id,
            session_id=session_id,
            message="继续",
            file_ids=[],
        ):
            await agent_service.write_task_stream(task_id, chunk, session_id)
            if chunk.get("type") == "end":
                break
        
        if session_id:
            await agent_service.clear_session_task(session_id)
        
        return {
            "success": True,
            "session_id": session_id,
            "task_id": task_id,
        }
    
    except Exception as e:
        logger.error(f"自动继续失败: {e}")
        await agent_service.write_task_stream(task_id, {"type": "error", "content": str(e)}, session_id)
        await agent_service.write_task_stream(task_id, {"type": "end", "content": "自动继续失败"}, session_id)
        if session_id:
            await agent_service.clear_session_task(session_id)
        return {"success": False, "error": str(e)}
