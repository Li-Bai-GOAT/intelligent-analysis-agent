# -*- coding: utf-8 -*-
"""
计划管理 API

允许用户查看和修改 AI 创建的计划
"""

import json
from typing import List, Optional
from pydantic import BaseModel
import redis

from fastapi import APIRouter, Depends, HTTPException, status

from app.models.user import User
from app.api.deps import get_current_user
from app.repositories.state_repo import StateRepository
from app.repositories.session_repo import SessionRepository
from app.config import settings

router = APIRouter(prefix="/plans", tags=["计划管理"])


# ==================== Schema ====================

class SubtaskSchema(BaseModel):
    """子任务"""
    name: str
    description: Optional[str] = None
    expected_outcome: Optional[str] = None
    state: str = "todo"  # todo, in_progress, done, failed


class PlanSchema(BaseModel):
    """计划"""
    name: str
    description: Optional[str] = None
    expected_outcome: Optional[str] = None
    state: str = "todo"
    subtasks: List[SubtaskSchema] = []


class PlanUpdateRequest(BaseModel):
    """计划更新请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    expected_outcome: Optional[str] = None
    subtasks: Optional[List[SubtaskSchema]] = None


class SubtaskUpdateRequest(BaseModel):
    """子任务更新请求"""
    name: Optional[str] = None
    description: Optional[str] = None
    expected_outcome: Optional[str] = None
    state: Optional[str] = None


# ==================== Helper Functions ====================

def extract_plan_from_state(state: dict) -> Optional[dict]:
    """从 agent 状态中提取计划信息"""
    if not state:
        return None
    
    # AgentScope ReActAgent 状态结构中，plan_notebook 在 state["plan_notebook"]
    plan_notebook_state = state.get("plan_notebook", {})
    current_plan = plan_notebook_state.get("current_plan")
    
    if not current_plan:
        return None
    
    return current_plan


def update_plan_in_state(state: dict, plan_updates: dict) -> dict:
    """更新状态中的计划信息"""
    if "plan_notebook" not in state:
        state["plan_notebook"] = {}

    current_plan = state["plan_notebook"].get("current_plan", {})

    # 更新计划字段
    if plan_updates.get("name") is not None:
        current_plan["name"] = plan_updates["name"]
    if plan_updates.get("description") is not None:
        current_plan["description"] = plan_updates["description"]
    if plan_updates.get("expected_outcome") is not None:
        current_plan["expected_outcome"] = plan_updates["expected_outcome"]
    if plan_updates.get("subtasks") is not None:
        current_plan["subtasks"] = plan_updates["subtasks"]

    state["plan_notebook"]["current_plan"] = current_plan
    return state


def _parse_tool_arguments(message: dict) -> tuple[str, dict] | tuple[None, None]:
    """从历史 plugin_call 中提取工具名和参数。"""
    msg_type = message.get("type") or message.get("msg_type")
    if msg_type != "plugin_call":
        return None, None

    for item in message.get("content", []):
        if not isinstance(item, dict) or item.get("type") != "data":
            continue
        data = item.get("data", {})
        if not isinstance(data, dict):
            continue
        tool_name = data.get("name")
        raw_arguments = data.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
        except json.JSONDecodeError:
            arguments = {}
        if isinstance(tool_name, str) and isinstance(arguments, dict):
            return tool_name, arguments
    return None, None


def _normalize_subtask(raw: dict | str) -> dict:
    if isinstance(raw, str):
        return {"name": raw, "description": None, "expected_outcome": None, "state": "todo"}
    return {
        "name": str(raw.get("name") or "未命名子任务"),
        "description": raw.get("description"),
        "expected_outcome": raw.get("expected_outcome"),
        "state": str(raw.get("state") or "todo"),
    }


async def reconstruct_plan_from_history(user_id: str, session_id: str) -> Optional[dict]:
    """从历史计划工具调用中重建计划，兼容旧会话和未落库状态。"""
    session = await SessionRepository.get(user_id, session_id)
    if not session:
        return None

    messages = await SessionRepository.get_messages(session)
    plan: Optional[dict] = None
    for msg_record in messages:
        tool_name, arguments = _parse_tool_arguments(msg_record.message)
        if not tool_name:
            continue

        if tool_name in {"create_plan", "preview_plan"}:
            raw_subtasks = arguments.get("subtasks") or []
            if not isinstance(raw_subtasks, list):
                raw_subtasks = []
            plan = {
                "name": str(arguments.get("name") or "分析计划"),
                "description": arguments.get("description"),
                "expected_outcome": arguments.get("expected_outcome"),
                "state": "todo",
                "subtasks": [_normalize_subtask(item) for item in raw_subtasks],
            }
            continue

        if not plan:
            continue

        if tool_name == "update_subtask_state":
            idx = arguments.get("subtask_idx")
            state = arguments.get("state")
            if isinstance(idx, int) and 0 <= idx < len(plan["subtasks"]) and state:
                plan["subtasks"][idx]["state"] = str(state)
                if str(state) == "in_progress":
                    plan["state"] = "in_progress"
        elif tool_name == "finish_subtask":
            idx = arguments.get("subtask_idx")
            if isinstance(idx, int) and 0 <= idx < len(plan["subtasks"]):
                plan["subtasks"][idx]["state"] = "done"
                outcome = arguments.get("subtask_outcome")
                if outcome and not plan["subtasks"][idx].get("expected_outcome"):
                    plan["subtasks"][idx]["expected_outcome"] = str(outcome)
                next_idx = idx + 1
                if next_idx < len(plan["subtasks"]):
                    plan["subtasks"][next_idx]["state"] = "in_progress"
                    plan["state"] = "in_progress"
        elif tool_name == "finish_plan":
            plan["state"] = str(arguments.get("state") or "done")
            outcome = arguments.get("outcome")
            if outcome:
                plan["expected_outcome"] = str(outcome)

    if plan and plan.get("subtasks") and all(st.get("state") == "done" for st in plan["subtasks"]):
        plan["state"] = "done"
    return plan


def plan_to_schema(plan: dict) -> PlanSchema:
    subtasks = []
    for st in plan.get("subtasks", []):
        subtasks.append(SubtaskSchema(
            name=st.get("name", ""),
            description=st.get("description"),
            expected_outcome=st.get("expected_outcome"),
            state=st.get("state", "todo"),
        ))
    return PlanSchema(
        name=plan.get("name", ""),
        description=plan.get("description"),
        expected_outcome=plan.get("expected_outcome"),
        state=plan.get("state", "todo"),
        subtasks=subtasks,
    )


# ==================== API Endpoints ====================

@router.get("/{session_id}", response_model=Optional[PlanSchema], summary="获取当前计划")
async def get_plan(session_id: str, user: User = Depends(get_current_user)):
    """获取指定会话的当前计划"""
    user_id = str(user.id)
    state = await StateRepository.get(user_id, session_id) or {}

    plan = extract_plan_from_state(state)
    if not plan:
        plan = await reconstruct_plan_from_history(user_id, session_id)
        if not plan:
            return None
        state.setdefault("plan_notebook", {})["current_plan"] = plan
        await StateRepository.save(user_id, state, session_id)

    return plan_to_schema(plan)


@router.put("/{session_id}", response_model=PlanSchema, summary="更新计划")
async def update_plan(
    session_id: str,
    request: PlanUpdateRequest,
    user: User = Depends(get_current_user),
):
    """更新指定会话的计划（可修改名称、描述、子任务等）"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话状态不存在")
    
    plan = extract_plan_from_state(state)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该会话没有计划")
    
    # 构建更新数据
    updates = {}
    if request.name is not None:
        updates["name"] = request.name
    if request.description is not None:
        updates["description"] = request.description
    if request.expected_outcome is not None:
        updates["expected_outcome"] = request.expected_outcome
    if request.subtasks is not None:
        updates["subtasks"] = [st.model_dump() for st in request.subtasks]
    
    # 更新状态
    updated_state = update_plan_in_state(state, updates)
    await StateRepository.save(str(user.id), updated_state, session_id)
    
    # 返回更新后的计划
    return await get_plan(session_id, user)


@router.put("/{session_id}/subtasks/{subtask_idx}", summary="更新子任务")
async def update_subtask(
    session_id: str,
    subtask_idx: int,
    request: SubtaskUpdateRequest,
    user: User = Depends(get_current_user),
):
    """更新指定子任务"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话状态不存在")
    
    plan = extract_plan_from_state(state)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该会话没有计划")
    
    subtasks = plan.get("subtasks", [])
    if subtask_idx < 0 or subtask_idx >= len(subtasks):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="子任务索引无效")
    
    # 更新子任务
    if request.name is not None:
        subtasks[subtask_idx]["name"] = request.name
    if request.description is not None:
        subtasks[subtask_idx]["description"] = request.description
    if request.expected_outcome is not None:
        subtasks[subtask_idx]["expected_outcome"] = request.expected_outcome
    if request.state is not None:
        subtasks[subtask_idx]["state"] = request.state
    
    # 保存
    plan["subtasks"] = subtasks
    state["plan_notebook"]["current_plan"] = plan
    await StateRepository.save(str(user.id), state, session_id)
    
    return {"success": True, "subtask": subtasks[subtask_idx]}


@router.post("/{session_id}/subtasks", summary="添加子任务")
async def add_subtask(
    session_id: str,
    request: SubtaskSchema,
    user: User = Depends(get_current_user),
):
    """添加新子任务"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话状态不存在")
    
    plan = extract_plan_from_state(state)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该会话没有计划")
    
    subtasks = plan.get("subtasks", [])
    subtasks.append(request.model_dump())
    
    plan["subtasks"] = subtasks
    state["plan_notebook"]["current_plan"] = plan
    await StateRepository.save(str(user.id), state, session_id)
    
    return {"success": True, "subtask_idx": len(subtasks) - 1}


@router.delete("/{session_id}", summary="清空计划")
async def clear_plan(
    session_id: str,
    user: User = Depends(get_current_user),
):
    """清空指定会话的计划（用于中断执行时）"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        return {"success": True, "message": "会话状态不存在"}
    
    # 清空计划
    if "plan_notebook" in state:
        state["plan_notebook"]["current_plan"] = None
    
    await StateRepository.save(str(user.id), state, session_id)
    
    # 同时清理 Redis 中的编辑数据
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.delete(f"edited_plan:{session_id}")
        r.close()
    except Exception:
        pass
    
    return {"success": True, "message": "计划已清空"}


@router.delete("/{session_id}/subtasks/{subtask_idx}", summary="删除子任务")
async def delete_subtask(
    session_id: str,
    subtask_idx: int,
    user: User = Depends(get_current_user),
):
    """删除指定子任务"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话状态不存在")
    
    plan = extract_plan_from_state(state)
    if not plan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="该会话没有计划")
    
    subtasks = plan.get("subtasks", [])
    if subtask_idx < 0 or subtask_idx >= len(subtasks):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="子任务索引无效")
    
    deleted = subtasks.pop(subtask_idx)
    
    plan["subtasks"] = subtasks
    state["plan_notebook"]["current_plan"] = plan
    await StateRepository.save(str(user.id), state, session_id)
    
    return {"success": True, "deleted": deleted}
