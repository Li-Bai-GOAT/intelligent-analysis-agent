# -*- coding: utf-8 -*-
"""
Celery 异步任务

用于长时间运行的分析任务。Windows 下使用本地线程池替代 Celery Worker。
"""

import asyncio
import logging
import platform
import uuid
from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Any, Optional

from celery import Celery

from app.config import settings
from app.database import init_db, close_db
from app.services.agent_service import AgentService

logger = logging.getLogger(__name__)

_is_windows = platform.system() == "Windows"

# Windows 兼容：本地后台任务执行器
_local_executor: Optional[ThreadPoolExecutor] = None
_local_tasks: Dict[str, asyncio.Task] = {}

def _get_local_executor() -> ThreadPoolExecutor:
    """获取或创建本地执行器"""
    global _local_executor
    if _local_executor is None:
        _local_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="bg_task_")
    return _local_executor


# Celery 应用 (非 Windows 时使用)
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
    result_expires=settings.CELERY_RESULT_EXPIRES,
    task_time_limit=settings.CELERY_TASK_TIME_LIMIT,
    task_soft_time_limit=settings.CELERY_TASK_SOFT_TIME_LIMIT,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_routes={
        "app.tasks.analyze_task": {"queue": "rca_tasks"},
        "app.tasks.auto_continue_task": {"queue": "rca_tasks"},
    },
)


def _run_async(coro):
    """在独立线程中运行异步函数"""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _close_task_agent_service(agent_service: AgentService) -> None:
    """Close per-task async resources without releasing shared sandboxes."""
    for resource in (
        getattr(agent_service, "cleanup_service", None),
        getattr(agent_service, "session_service", None),
        getattr(agent_service, "state_service", None),
    ):
        if resource:
            try:
                await resource.stop()
            except Exception:
                logger.exception("Failed to stop task resource")

    redis_client = getattr(agent_service, "_redis", None)
    if redis_client:
        try:
            await redis_client.aclose()
        except Exception:
            logger.exception("Failed to close task redis client")

    agent_service._redis = None
    agent_service._started = False


# ============================================================================
# Windows 兼容：本地后台任务执行 (替代 Celery Worker)
# ============================================================================

def start_local_task(coro_or_func, *args, task_id: str | None = None) -> str:
    """在 Windows 上启动本地后台任务，返回 task_id

    Args:
        coro_or_func: 协程对象或返回协程的异步函数
        *args: 如果传入的是函数，这些是函数的参数
    """
    task_id = task_id or str(uuid.uuid4())

    try:
        # 获取当前正在运行的事件循环（FastAPI 的主循环）
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # 主循环正在运行，使用 run_coroutine_threadsafe 将任务调度到主循环
        # 这样避免创建新的事件循环和数据库连接池
        if callable(coro_or_func):
            coro = coro_or_func(*args)
        else:
            coro = coro_or_func

        future = asyncio.run_coroutine_threadsafe(coro, loop)
        _local_tasks[task_id] = future

        def _cleanup(fut):
            _local_tasks.pop(task_id, None)
            # 如果任务有异常，记录日志
            try:
                fut.result(timeout=0)
            except Exception as e:
                logger.error(f"Local task {task_id} error: {e}")

        future.add_done_callback(_cleanup)
    else:
        # 没有运行中的事件循环（不太可能在 FastAPI 中发生），回退到独立线程
        executor = _get_local_executor()

        def run_and_monitor():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                if callable(coro_or_func):
                    coro = coro_or_func(*args)
                else:
                    coro = coro_or_func
                task = loop.create_task(coro)
                _local_tasks[task_id] = task
                loop.run_until_complete(task)
            except Exception as e:
                logger.error(f"Local task {task_id} error: {e}")
            finally:
                _local_tasks.pop(task_id, None)
                loop.close()

        executor.submit(run_and_monitor)

    return task_id


# ============================================================================
# 任务定义 (同时支持 Celery 和本地执行)
# ============================================================================

def analyze_task(request_dict: Dict[str, Any], task_id: str = None) -> Dict[str, Any]:
    """
    分析任务 (Windows 本地执行版本)
    """
    return _run_async(_execute_analyze_task(request_dict, task_id or str(uuid.uuid4())))


@celery_app.task(bind=True, name="app.tasks.analyze_task", queue="rca_tasks")
def celery_analyze_task(self, request_dict: Dict[str, Any]):
    """Celery 任务入口"""
    task_id = self.request.id
    return _run_async(_execute_analyze_task(request_dict, task_id))


async def _execute_analyze_task(request_dict: Dict[str, Any], task_id: str) -> Dict[str, Any]:
    """执行分析任务"""
    user_id = request_dict.get("user_id", "anonymous")
    session_id = request_dict.get("session_id")
    message = request_dict.get("message", "")
    file_ids = request_dict.get("file_ids", [])
    execution_mode = request_dict.get("execution_mode", "auto")

    if not message:
        return {"success": False, "error": "未提供任务内容"}

    # Windows local tasks run inside FastAPI's event loop and must reuse the
    # application's global ORM pool and AgentService lifecycle. Reinitializing
    # or closing either resource here breaks the next API request.
    owns_resources = platform.system() != "Windows"
    if owns_resources:
        await init_db()
        agent_service = AgentService()
    else:
        agent_service = AgentService.get_instance()
    await agent_service.start()

    try:
        await agent_service.write_task_stream(task_id, {"type": "status", "content": "任务开始"}, session_id)

        final_result = None
        saw_end = False
        async for chunk in agent_service.chat(
            user_id=user_id,
            session_id=session_id,
            message=message,
            file_ids=file_ids,
            execution_mode=execution_mode,
        ):
            await agent_service.write_task_stream(task_id, chunk, session_id)
            if chunk.get("type") == "end":
                final_result = chunk
                break

        if final_result is None:
            final_result = {"type": "end", "content": "任务结束", "session_id": session_id}
            await agent_service.write_task_stream(task_id, final_result, session_id)

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
        if session_id:
            await agent_service.clear_session_task(session_id)
        return {"success": False, "error": str(e)}
    finally:
        if owns_resources:
            await _close_task_agent_service(agent_service)
            await close_db()


def auto_continue_task(session_id: str, user_id: str, preview_id: str, task_id: str = None) -> Dict[str, Any]:
    """自动继续任务 (Windows 本地执行版本)"""
    return _run_async(_execute_auto_continue(
        session_id, user_id, preview_id, task_id or str(uuid.uuid4())
    ))


@celery_app.task(bind=True, name="app.tasks.auto_continue_task", queue="rca_tasks")
def celery_auto_continue_task(self, session_id: str, user_id: str, preview_id: str):
    """Celery 任务入口"""
    return _run_async(_execute_auto_continue(session_id, user_id, preview_id, self.request.id))


async def _execute_auto_continue(session_id: str, user_id: str, preview_id: str, task_id: str) -> Dict[str, Any]:
    """执行自动继续"""
    import json
    from app.api.kuncode import _get_redis, _get_auto_continue_key

    redis = await _get_redis()
    try:
        active_task_key = f"session_task:{session_id}"
        active_task = await redis.get(active_task_key)
        if active_task:
            logger.info(f"会话有活跃任务运行中，跳过自动继续: {session_id}")
            return {"success": False, "reason": "active_task_running"}

        key = _get_auto_continue_key(session_id)
        data = await redis.get(key)

        if not data:
            logger.info(f"自动继续已被清除，跳过: {session_id}")
            return {"success": False, "reason": "cleared"}

        pending = json.loads(data)

        if pending.get("preview_id") != preview_id:
            logger.info(f"preview_id 不匹配，跳过: {session_id}")
            return {"success": False, "reason": "preview_id_mismatch"}

        if pending.get("status") != "pending":
            logger.info(f"自动继续已被用户处理 ({pending.get('status')})，跳过: {session_id}")
            return {"success": False, "reason": pending.get("status")}

        pending["status"] = "auto_triggered"
        pending["task_id"] = task_id
        await redis.set(key, json.dumps(pending), ex=300)
    finally:
        await redis.aclose()

    logger.info(f"自动继续触发: {session_id}")

    owns_resources = platform.system() != "Windows"
    if owns_resources:
        await init_db()
        agent_service = AgentService()
    else:
        agent_service = AgentService.get_instance()
    await agent_service.start()

    try:
        await agent_service.write_task_stream(task_id, {"type": "status", "content": "自动继续执行"}, session_id)

        saw_end = False
        async for chunk in agent_service.chat(
            user_id=user_id,
            session_id=session_id,
            message="继续",
            file_ids=[],
        ):
            await agent_service.write_task_stream(task_id, chunk, session_id)
            if chunk.get("type") == "end":
                saw_end = True
                break

        if not saw_end:
            await agent_service.write_task_stream(
                task_id,
                {"type": "end", "content": "任务结束", "session_id": session_id},
                session_id,
            )

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
    finally:
        if owns_resources:
            await _close_task_agent_service(agent_service)
            await close_db()
