# -*- coding: utf-8 -*-
"""
Kuncode 预览确认 API

实现 Human-in-the-loop 功能：AI 生成 kuncode 指令后，用户可预览、编辑、确认或取消
"""

import json
from typing import Optional
from pydantic import BaseModel

from fastapi import APIRouter, Depends, HTTPException
import redis.asyncio as aioredis

from app.models.user import User
from app.api.deps import get_current_user
from app.config import settings

router = APIRouter(prefix="/kuncode", tags=["Kuncode预览"])


# ==================== Schema ====================

class KuncodePreviewResponse(BaseModel):
    """Kuncode 预览响应"""
    preview_id: str
    prompt: str
    agent: Optional[str] = None
    model: Optional[str] = None
    status: str  # pending, confirmed, cancelled, executed


class KuncodeConfirmRequest(BaseModel):
    """Kuncode 确认请求"""
    prompt: str  # 可能被用户编辑过的 prompt
    action: str  # confirm, cancel
    agent: Optional[str] = None  # 用户选择的 agent


# ==================== Helper Functions ====================

def _get_preview_key(session_id: str, preview_id: str) -> str:
    return f"kuncode_preview:{session_id}:{preview_id}"


def _get_pending_key(session_id: str) -> str:
    return f"kuncode_pending:{session_id}"


async def _get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.REDIS_URL, decode_responses=True)


# ==================== API Endpoints ====================

@router.get("/{session_id}/pending", summary="获取待确认的 Kuncode 请求")
async def get_pending_kuncode(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """获取当前会话中待确认的 Kuncode 请求"""
    redis = await _get_redis()
    try:
        # 先检查 kuncode pending
        pending_key = _get_pending_key(session_id)
        preview_id = await redis.get(pending_key)
        preview_key = None
        
        # 如果没有 kuncode pending，检查 plan pending
        if not preview_id:
            plan_pending_key = _get_plan_pending_key(session_id)
            preview_id = await redis.get(plan_pending_key)
            if preview_id:
                preview_id_str = preview_id.decode() if isinstance(preview_id, bytes) else preview_id
                preview_key = _get_plan_preview_key(session_id, preview_id_str)
        
        # 如果没有 plan pending，检查 auto_continue pending
        if not preview_id:
            # 先检查是否有活跃任务正在运行，有任务运行时不需要询问是否继续
            active_task_key = f"session_task:{session_id}"
            active_task = await redis.get(active_task_key)
            if active_task:
                # 有任务正在运行，不显示 auto_continue 弹窗
                return {"has_pending": False}
            
            auto_continue_key = _get_auto_continue_key(session_id)
            auto_continue_data = await redis.get(auto_continue_key)
            if auto_continue_data:
                import time
                ac_pending = json.loads(auto_continue_data)
                ac_status = ac_pending.get("status")
                
                # 如果已确认/取消，不再显示（等待新任务结束后重置）
                if ac_status in ("confirmed", "cancelled"):
                    pass  # 不创建新的，直接返回 no pending
                elif ac_status == "auto_triggered":
                    # 自动继续已触发，返回特殊状态让前端重连
                    return {
                        "has_pending": True,
                        "preview_type": "auto_triggered",
                        "preview_id": ac_pending.get("preview_id"),
                        "task_id": ac_pending.get("task_id"),
                    }
                elif ac_status == "pending":
                    created_at = ac_pending.get("created_at", time.time())
                    timeout_seconds = ac_pending.get("timeout_seconds", 180)
                    elapsed = time.time() - created_at
                    remaining = max(0, int(timeout_seconds - elapsed))
                    # 即使 remaining=0 也返回，让前端继续轮询等待 auto_triggered
                    return {
                        "has_pending": True,
                        "preview_type": "auto_continue",
                        "remaining_seconds": remaining,
                        "preview_id": ac_pending.get("preview_id"),
                    }
            # 没有 auto_continue 记录，直接返回无待确认
            # 注意：auto_continue 只在 AgentService.chat 任务结束时创建，/pending 只读取状态
        
        if not preview_id:
            return {"has_pending": False}
        
        # 如果还没设置 preview_key，使用 kuncode preview key
        if not preview_key:
            preview_key = _get_preview_key(session_id, preview_id)
        data = await redis.get(preview_key)
        
        if not data:
            return {"has_pending": False}
        
        import time
        preview = json.loads(data)
        
        # 如果预览已被确认或取消，返回无待确认
        if preview.get("status") != "pending":
            # 清理残留的 pending key
            await redis.delete(pending_key)
            # 同时尝试清理 plan pending key
            plan_pending_key = _get_plan_pending_key(session_id)
            await redis.delete(plan_pending_key)
            return {"has_pending": False}
        
        # 计算剩余时间
        created_at = preview.get("created_at", time.time())
        timeout_seconds = preview.get("timeout_seconds", 180)
        elapsed = time.time() - created_at
        remaining = max(0, int(timeout_seconds - elapsed))
        
        # 如果已超时，返回无待确认
        if remaining <= 0:
            return {"has_pending": False}
        
        # 判断类型
        preview_id_str = preview_id.decode() if isinstance(preview_id, bytes) else preview_id
        if preview_id_str.startswith("plan_"):
            preview_type = "plan"
        elif preview_id_str.startswith("ask_"):
            preview_type = "ask_user"
        else:
            preview_type = "kuncode"
        
        return {
            "has_pending": True,
            "preview_type": preview_type,
            "remaining_seconds": remaining,
            "preview": KuncodePreviewResponse(
                preview_id=preview_id_str,
                prompt=preview.get("prompt", ""),
                agent=preview.get("agent"),
                model=preview.get("model"),
                status=preview.get("status", "pending"),
            ),
            # 计划特有字段
            "name": preview.get("name"),
            "subtasks": preview.get("subtasks"),
        }
    finally:
        await redis.close()


@router.post("/{session_id}/confirm/{preview_id}", summary="确认或取消 Kuncode 执行")
async def confirm_kuncode(
    session_id: str,
    preview_id: str,
    request: KuncodeConfirmRequest,
    user: User = Depends(get_current_user),
):
    """
    确认或取消 Kuncode 执行
    
    - action=confirm: 使用提供的 prompt（可能已编辑）执行 kuncode
    - action=cancel: 取消执行，返回取消消息给 AI
    """
    redis = await _get_redis()
    try:
        preview_key = _get_preview_key(session_id, preview_id)
        pending_key = _get_pending_key(session_id)
        
        data = await redis.get(preview_key)
        if not data:
            raise HTTPException(status_code=404, detail="预览请求不存在或已过期")
        
        preview = json.loads(data)
        if preview.get("status") != "pending":
            raise HTTPException(status_code=400, detail="该请求已被处理")
        
        # 更新状态
        if request.action == "confirm":
            preview["status"] = "confirmed"
            preview["confirmed_prompt"] = request.prompt  # 保存编辑后的 prompt
        elif request.action == "cancel":
            preview["status"] = "cancelled"
        else:
            raise HTTPException(status_code=400, detail="无效的 action")
        
        # 保存更新后的状态
        await redis.set(preview_key, json.dumps(preview), ex=3600)
        
        # 发送确认信号（通过 Redis pubsub 或直接更新状态）
        confirm_key = f"kuncode_confirm:{session_id}:{preview_id}"
        await redis.set(confirm_key, json.dumps({
            "action": request.action,
            "prompt": request.prompt if request.action == "confirm" else None,
            "agent": request.agent if request.action == "confirm" else None,
        }), ex=3600)
        
        # 清除 pending 状态
        await redis.delete(pending_key)
        # 尝试清理 plan pending key 以防万一
        plan_pending_key = _get_plan_pending_key(session_id)
        await redis.delete(plan_pending_key)
        
        return {
            "success": True,
            "action": request.action,
            "preview_id": preview_id,
        }
    finally:
        await redis.close()


class PlanConfirmRequest(BaseModel):
    """计划确认请求"""
    action: str  # confirm, cancel
    name: str = ""
    subtasks: list[str] = []


@router.post("/{session_id}/plan/confirm/{preview_id}", summary="确认或取消计划预览")
async def confirm_plan(
    session_id: str,
    preview_id: str,
    request: PlanConfirmRequest,
    user: User = Depends(get_current_user),
):
    """
    确认或取消计划预览
    
    - action=confirm: 使用提供的计划名称和子任务列表
    - action=cancel: 取消计划创建
    """
    from app.api.kuncode import confirm_plan_preview
    
    await confirm_plan_preview(
        session_id=session_id,
        preview_id=preview_id,
        action=request.action,
        name=request.name,
        subtasks=request.subtasks,
    )
    
    return {
        "success": True,
        "action": request.action,
        "preview_id": preview_id,
    }


class AutoContinueConfirmRequest(BaseModel):
    """自动继续确认请求"""
    action: str  # continue, cancel


@router.post("/{session_id}/auto_continue/confirm", summary="确认或取消自动继续")
async def confirm_auto_continue_api(
    session_id: str,
    request: AutoContinueConfirmRequest,
    user: User = Depends(get_current_user),
):
    """
    确认或取消自动继续
    
    - action=continue: 继续执行计划
    - action=cancel: 取消执行
    """
    await confirm_auto_continue(session_id, request.action)
    
    return {
        "success": True,
        "action": request.action,
    }


@router.post("/{session_id}/auto_continue/reset", summary="重置自动继续倒计时")
async def reset_auto_continue_api(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """
    重置自动继续倒计时（用户输入时调用）
    """
    success = await reset_auto_continue_timer(session_id)
    return {"success": success}


@router.post("/{session_id}/preview/reset", summary="重置预览倒计时")
async def reset_preview_timer_api(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """
    重置当前预览（kuncode/plan/ask_user）的倒计时（用户编辑时调用）
    """
    success = await reset_preview_timer(session_id)
    return {"success": success}


class UpdatePlanPreviewRequest(BaseModel):
    name: Optional[str] = None
    subtasks: Optional[list[str]] = None


@router.post("/{session_id}/plan/update", summary="更新计划预览内容")
async def update_plan_preview_api(
    session_id: str,
    request: UpdatePlanPreviewRequest,
    user: User = Depends(get_current_user),
):
    """
    更新计划预览的内容（用户编辑时实时保存）
    """
    success = await update_plan_preview_content(session_id, request.name, request.subtasks)
    return {"success": success}


# ==================== Internal Functions (for agent_service) ====================

async def create_kuncode_preview(
    session_id: str,
    preview_id: str,
    prompt: str,
    agent: Optional[str] = None,
    model: Optional[str] = None,
    timeout_seconds: int = 180,
    name: Optional[str] = None,
    subtasks: Optional[list] = None,
) -> None:
    """创建 Kuncode 预览请求（由 agent_service 调用）"""
    import time
    redis = await _get_redis()
    try:
        preview_key = _get_preview_key(session_id, preview_id)
        pending_key = _get_pending_key(session_id)
        
        preview_data = {
            "prompt": prompt,
            "agent": agent,
            "model": model,
            "status": "pending",
            "created_at": time.time(),  # 存储创建时间戳
            "timeout_seconds": timeout_seconds,  # 存储超时时间
        }
        
        # 计划预览额外字段
        if name is not None:
            preview_data["name"] = name
        if subtasks is not None:
            preview_data["subtasks"] = subtasks
        
        await redis.set(preview_key, json.dumps(preview_data), ex=3600)
        await redis.set(pending_key, preview_id, ex=3600)
    finally:
        await redis.close()


async def save_kuncode_to_history(
    user_id: str,
    session_id: str,
    preview_id: str,
    prompt: str,
    status: str,
    confirmed_prompt: Optional[str] = None,
    agent: Optional[str] = None,
    model: Optional[str] = None,
) -> None:
    """保存 Kuncode 预览/确认到会话历史（用于历史记录持久化）"""
    from app.repositories.session_repo import SessionRepository
    
    db_session = await SessionRepository.get(user_id, session_id)
    if not db_session:
        return
    
    # 构建 kuncode_preview 消息
    msg_dict = {
        "role": "assistant",
        "type": "kuncode_preview",
        "content": [
            {
                "type": "kuncode_preview",
                "preview_id": preview_id,
                "prompt": prompt,
                "confirmed_prompt": confirmed_prompt,
                "status": status,
                "agent": agent,
                "model": model,
            }
        ],
    }
    
    await SessionRepository.append_message(db_session, msg_dict)


async def wait_for_kuncode_confirm(
    session_id: str,
    preview_id: str,
    timeout: int = 180,  # 3 分钟超时，超时后自动继续执行
) -> Optional[dict]:
    """等待用户确认 Kuncode（由 agent_service 调用）
    
    超时后返回 action="auto_confirm"，表示自动继续执行
    取消时返回 action="cancel"
    """
    import asyncio
    import time
    
    redis = await _get_redis()
    try:
        confirm_key = f"kuncode_confirm:{session_id}:{preview_id}"
        preview_key = _get_preview_key(session_id, preview_id)
        interrupt_key = f"agent_interrupt:{session_id}"
        
        # 轮询等待确认（基于 Redis 中的 created_at 时间，支持用户编辑时重置）
        while True:
            # 检查中断信号（Redis 返回 bytes）
            # 注意：不删除中断信号，让 AgentService.check_interrupt() 统一处理
            # 这样可以确保 Agent 主循环能检测到中断并停止执行
            interrupt = await redis.get(interrupt_key)
            if interrupt:
                interrupt_str = interrupt.decode() if isinstance(interrupt, bytes) else str(interrupt)
                if interrupt_str == "1":
                    return {"action": "cancel", "interrupted": True}
            
            # 检查确认结果
            result = await redis.get(confirm_key)
            if result:
                await redis.delete(confirm_key)
                return json.loads(result)
            
            # 检查是否超时（基于 Redis 中的 created_at，支持重置）
            preview_data = await redis.get(preview_key)
            if preview_data:
                try:
                    data = json.loads(preview_data)
                    created_at = data.get("created_at", 0)
                    timeout_seconds = data.get("timeout_seconds", timeout)
                    elapsed = time.time() - created_at
                    if elapsed >= timeout_seconds:
                        break  # 超时，跳出循环
                except Exception:
                    pass
            else:
                # 预览数据不存在，视为取消
                return {"action": "cancel", "interrupted": False}
            
            await asyncio.sleep(0.5)
        
        # 超时 - 自动确认继续执行
        # 获取原始 prompt 和 agent
        preview_data = await redis.get(preview_key)
        original_prompt = ""
        original_agent = None
        if preview_data:
            try:
                data = json.loads(preview_data)
                original_prompt = data.get("prompt", "")
                original_agent = data.get("agent")
                # 更新状态为 auto_confirmed
                data["status"] = "auto_confirmed"
                await redis.set(preview_key, json.dumps(data), ex=3600)
            except Exception:
                pass
        
        # 清理 pending 状态，让前端知道预览已处理
        pending_key = _get_pending_key(session_id)
        await redis.delete(pending_key)
        
        return {"action": "auto_confirm", "prompt": original_prompt, "agent": original_agent, "timeout": True}
    finally:
        await redis.close()


# ==================== Plan Preview Functions ====================

def _get_plan_preview_key(session_id: str, preview_id: str) -> str:
    return f"plan_preview:{session_id}:{preview_id}"


def _get_plan_pending_key(session_id: str) -> str:
    return f"plan_pending:{session_id}"


async def create_plan_preview(
    session_id: str,
    preview_id: str,
    name: str,
    subtasks: list[str],
    timeout_seconds: int = 180,
) -> None:
    """创建计划预览请求"""
    import time
    redis = await _get_redis()
    try:
        preview_key = _get_plan_preview_key(session_id, preview_id)
        pending_key = _get_plan_pending_key(session_id)
        
        preview_data = {
            "name": name,
            "subtasks": subtasks,
            "status": "pending",
            "created_at": time.time(),
            "timeout_seconds": timeout_seconds,
        }
        
        await redis.set(preview_key, json.dumps(preview_data), ex=3600)
        await redis.set(pending_key, preview_id, ex=3600)
    finally:
        await redis.close()


async def wait_for_plan_confirm(
    session_id: str,
    preview_id: str,
    timeout: int = 180,
) -> dict:
    """等待用户确认计划预览"""
    import asyncio
    import time
    
    redis = await _get_redis()
    # 使用会话级别的确认键，因为前端生成的 preview_id 可能与后端不同
    confirm_key = f"plan_confirm:{session_id}"
    interrupt_key = f"agent_interrupt:{session_id}"
    preview_key = _get_plan_preview_key(session_id, preview_id)
    pending_key = _get_plan_pending_key(session_id)
    
    try:
        while True:
            # 检查中断信号（Redis 返回 bytes）
            # 注意：不删除中断信号，让 AgentService.check_interrupt() 统一处理
            # 这样可以确保 Agent 主循环能检测到中断并停止执行
            interrupt = await redis.get(interrupt_key)
            if interrupt:
                interrupt_str = interrupt.decode() if isinstance(interrupt, bytes) else str(interrupt)
                if interrupt_str == "1":
                    return {"action": "cancel", "name": "", "subtasks": [], "interrupted": True}
            
            # 检查确认结果
            result = await redis.get(confirm_key)
            if result:
                data = json.loads(result)
                # 清理确认键
                await redis.delete(confirm_key)
                return data
            
            # 检查是否超时（基于 Redis 中的 created_at，支持重置）
            preview_data = await redis.get(preview_key)
            if preview_data:
                try:
                    pdata = json.loads(preview_data)
                    created_at = pdata.get("created_at", 0)
                    timeout_seconds = pdata.get("timeout_seconds", timeout)
                    elapsed = time.time() - created_at
                    if elapsed >= timeout_seconds:
                        # 超时后清理 pending 状态
                        await redis.delete(pending_key)
                        # 更新预览状态
                        pdata["status"] = "auto_confirmed"
                        await redis.set(preview_key, json.dumps(pdata), ex=3600)
                        # 返回当前保存的数据（可能已被用户编辑）
                        return {
                            "action": "auto_confirm",
                            "name": pdata.get("name", ""),
                            "subtasks": pdata.get("subtasks", []),
                        }
                except Exception as e:
                    import logging
                    logging.getLogger(__name__).warning(f"检查计划预览超时失败: {e}")
            else:
                # 预览数据不存在，视为取消
                return {"action": "cancel", "name": "", "subtasks": [], "interrupted": False}
            
            await asyncio.sleep(0.5)
    finally:
        await redis.close()


async def confirm_plan_preview(
    session_id: str,
    preview_id: str,
    action: str,
    name: str = "",
    subtasks: list[str] = None,
) -> None:
    """确认或取消计划预览"""
    redis = await _get_redis()
    try:
        pending_key = _get_plan_pending_key(session_id)
        # 使用会话级别的确认键
        confirm_key = f"plan_confirm:{session_id}"
        
        # 保存确认结果
        confirm_data = {
            "action": action,
            "name": name,
            "subtasks": subtasks or [],
        }
        await redis.set(confirm_key, json.dumps(confirm_data), ex=300)
        
        # 清理 pending
        await redis.delete(pending_key)
        
        # 更新预览状态，防止重连时再次加载
        if action in ["confirm", "cancel"]:
            preview_key = _get_plan_preview_key(session_id, preview_id)
            preview_data = await redis.get(preview_key)
            if preview_data:
                try:
                    data = json.loads(preview_data)
                    data["status"] = "confirmed" if action == "confirm" else "cancelled"
                    if action == "confirm":
                        data["name"] = name
                        data["subtasks"] = subtasks or []
                    await redis.set(preview_key, json.dumps(data), ex=3600)
                except Exception:
                    pass
    finally:
        await redis.close()


# ==================== Auto Continue Functions ====================

def _get_auto_continue_key(session_id: str) -> str:
    return f"auto_continue:{session_id}"


async def create_auto_continue_pending(
    session_id: str,
    timeout_seconds: int = 180,
    user_id: str = None,
) -> str:
    """创建自动继续待确认状态（计划未完成时由后端调用）"""
    import time
    import uuid
    
    redis = await _get_redis()
    try:
        preview_id = f"continue_{uuid.uuid4().hex[:8]}"
        key = _get_auto_continue_key(session_id)
        
        data = {
            "preview_id": preview_id,
            "status": "pending",
            "created_at": time.time(),
            "timeout_seconds": timeout_seconds,
            "user_id": user_id,
        }
        
        await redis.set(key, json.dumps(data), ex=3600)
        
        # 调度延迟任务：超时后自动继续
        if user_id:
            from app.tasks import auto_continue_task
            auto_continue_task.apply_async(
                args=[session_id, user_id, preview_id],
                countdown=timeout_seconds,
            )
        
        return preview_id
    finally:
        await redis.close()


async def _mark_plan_subtasks_abandoned(session_id: str, user_id: str) -> None:
    """将未完成的子任务标记为 abandoned（用户中断时调用）
    
    Args:
        session_id: 会话 ID
        user_id: 用户 ID
    """
    from app.repositories.state_repo import StateRepository
    
    # 获取并更新计划状态
    state = await StateRepository.get(user_id, session_id)
    if not state:
        return
    
    plan_notebook = state.get("plan_notebook", {})
    current_plan = plan_notebook.get("current_plan")
    if not current_plan or not current_plan.get("subtasks"):
        return
    
    # 将所有未完成的子任务标记为 abandoned（AgentScope 支持的状态）
    modified = False
    for subtask in current_plan["subtasks"]:
        if subtask.get("state") not in ("done", "abandoned"):
            subtask["state"] = "abandoned"
            modified = True
    
    # 同时将主计划标记为 abandoned
    if current_plan.get("state") not in ("done", "abandoned"):
        current_plan["state"] = "abandoned"
        modified = True
    
    if modified:
        state["plan_notebook"]["current_plan"] = current_plan
        await StateRepository.save(user_id, state, session_id)


async def _mark_plan_subtasks_skipped(session_id: str) -> None:
    """将未完成的子任务标记为 skipped（用户取消继续时调用）
    
    这是持久化操作，确保用户取消后不会再被询问是否继续
    注意：此函数依赖 auto_continue Redis key，仅在自动继续场景使用
    """
    
    # 从 Redis 获取 user_id
    redis = await _get_redis()
    try:
        key = _get_auto_continue_key(session_id)
        data = await redis.get(key)
        if not data:
            return
        
        pending = json.loads(data)
        user_id = pending.get("user_id")
        if not user_id:
            return
    finally:
        await redis.close()
    
    # 调用通用函数
    await _mark_plan_subtasks_abandoned(session_id, user_id)


async def confirm_auto_continue(
    session_id: str,
    action: str,  # continue, cancel
) -> None:
    """确认自动继续操作"""
    redis = await _get_redis()
    try:
        key = _get_auto_continue_key(session_id)
        data = await redis.get(key)
        
        if data:
            pending = json.loads(data)
            pending["status"] = "confirmed" if action == "continue" else "cancelled"
            await redis.set(key, json.dumps(pending), ex=300)
        
        # 设置确认信号
        confirm_key = f"auto_continue_confirm:{session_id}"
        await redis.set(confirm_key, json.dumps({"action": action}), ex=300)
        
        # 如果用户取消，将未完成的子任务标记为 abandoned（持久化到数据库）
        if action == "cancel":
            await _mark_plan_subtasks_skipped(session_id)
    finally:
        await redis.close()


async def clear_auto_continue_pending(session_id: str) -> None:
    """清除自动继续待确认状态"""
    redis = await _get_redis()
    try:
        key = _get_auto_continue_key(session_id)
        await redis.delete(key)
    finally:
        await redis.close()


async def reset_auto_continue_timer(session_id: str) -> bool:
    """重置自动继续倒计时（用户输入时调用）"""
    import time
    
    redis = await _get_redis()
    try:
        key = _get_auto_continue_key(session_id)
        data = await redis.get(key)
        
        if not data:
            return False
        
        pending = json.loads(data)
        if pending.get("status") != "pending":
            return False
        
        # 重置创建时间，重新开始倒计时
        timeout_seconds = pending.get("timeout_seconds", 180)
        user_id = pending.get("user_id")
        
        # 生成新的 preview_id（使旧的 Celery 任务失效）
        import uuid
        new_preview_id = f"continue_{uuid.uuid4().hex[:8]}"
        
        pending["created_at"] = time.time()
        pending["preview_id"] = new_preview_id
        await redis.set(key, json.dumps(pending), ex=3600)
        
        # 重新调度 Celery 延迟任务
        if user_id:
            from app.tasks import auto_continue_task
            auto_continue_task.apply_async(
                args=[session_id, user_id, new_preview_id],
                countdown=timeout_seconds,
            )
        
        return True
    finally:
        await redis.close()


async def reset_preview_timer(session_id: str) -> bool:
    """重置预览倒计时（用户编辑时调用）- 适用于kuncode/plan/ask_user预览"""
    import time
    
    redis = await _get_redis()
    try:
        # 检查 kuncode pending
        pending_key = _get_pending_key(session_id)
        preview_id = await redis.get(pending_key)
        
        # 如果没有 kuncode pending，检查 plan pending
        if not preview_id:
            plan_pending_key = _get_plan_pending_key(session_id)
            preview_id = await redis.get(plan_pending_key)
            if preview_id:
                preview_id_str = preview_id.decode() if isinstance(preview_id, bytes) else preview_id
                preview_key = _get_plan_preview_key(session_id, preview_id_str)
            else:
                return False
        else:
            preview_id_str = preview_id.decode() if isinstance(preview_id, bytes) else preview_id
            preview_key = _get_preview_key(session_id, preview_id_str)
        
        data = await redis.get(preview_key)
        if not data:
            return False
        
        preview_data = json.loads(data)
        if preview_data.get("status") != "pending":
            return False
        
        # 重置创建时间，重新开始倒计时
        preview_data["created_at"] = time.time()
        await redis.set(preview_key, json.dumps(preview_data), ex=3600)
        
        return True
    finally:
        await redis.close()


async def update_plan_preview_content(
    session_id: str,
    name: Optional[str] = None,
    subtasks: Optional[list[str]] = None,
) -> bool:
    """更新计划预览内容（用户编辑时实时保存）"""
    import time
    
    redis = await _get_redis()
    try:
        # 获取 plan pending
        pending_key = _get_plan_pending_key(session_id)
        preview_id = await redis.get(pending_key)
        
        if not preview_id:
            return False
        
        preview_id_str = preview_id.decode() if isinstance(preview_id, bytes) else preview_id
        preview_key = _get_plan_preview_key(session_id, preview_id_str)
        
        data = await redis.get(preview_key)
        if not data:
            return False
        
        preview_data = json.loads(data)
        if preview_data.get("status") != "pending":
            return False
        
        # 更新内容
        if name is not None:
            preview_data["name"] = name
        if subtasks is not None:
            preview_data["subtasks"] = subtasks
        
        # 同时重置创建时间
        preview_data["created_at"] = time.time()
        await redis.set(preview_key, json.dumps(preview_data), ex=3600)
        
        return True
    finally:
        await redis.close()
