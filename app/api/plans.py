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


# ==================== API Endpoints ====================

@router.get("/{session_id}", response_model=Optional[PlanSchema], summary="获取当前计划")
async def get_plan(session_id: str, user: User = Depends(get_current_user)):
    """获取指定会话的当前计划"""
    state = await StateRepository.get(str(user.id), session_id)
    if not state:
        return None
    
    plan = extract_plan_from_state(state)
    if not plan:
        return None
    
    # 检查 Redis 中是否有用户编辑的计划内容
    edited_plan_key = f"edited_plan:{session_id}"
    try:
        r = redis.from_url(settings.REDIS_URL, decode_responses=True)
        edited_data_str = r.get(edited_plan_key)
        r.close()
        
        if edited_data_str:
            edited_data = json.loads(edited_data_str)
            edited_subtask_names = edited_data.get("subtasks", [])
            edited_name = edited_data.get("name", plan.get("name", ""))
            
            # 合并子任务：用户编辑的名称 + AI 更新的状态
            original_subtasks = plan.get("subtasks", [])
            merged_subtasks = []
            
            # 先处理用户编辑的子任务
            for i, edited_name_item in enumerate(edited_subtask_names):
                # 尝试匹配原始子任务获取状态
                if i < len(original_subtasks):
                    orig = original_subtasks[i]
                    merged_subtasks.append(SubtaskSchema(
                        name=edited_name_item,
                        description=orig.get("description"),
                        expected_outcome=orig.get("expected_outcome"),
                        state=orig.get("state", "todo"),
                    ))
                else:
                    # 新增的子任务
                    merged_subtasks.append(SubtaskSchema(
                        name=edited_name_item,
                        state="todo",
                    ))
            
            return PlanSchema(
                name=edited_name,
                description=plan.get("description"),
                expected_outcome=plan.get("expected_outcome"),
                state=plan.get("state", "todo"),
                subtasks=merged_subtasks,
            )
    except Exception:
        pass
    
    # 转换为响应格式（无编辑数据时使用原始内容）
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
