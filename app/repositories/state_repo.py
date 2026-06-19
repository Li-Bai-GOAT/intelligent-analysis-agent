# -*- coding: utf-8 -*-
"""
智能体状态数据访问层
"""

from typing import Optional, Dict, Any

from app.models.agent_state import AgentState


class StateRepository:
    """智能体状态数据访问"""
    
    @staticmethod
    async def save(
        user_id: str,
        state: Dict[str, Any],
        session_id: str = "default",
        round_id: Optional[int] = None,
    ) -> int:
        """保存状态，返回 round_id"""
        if round_id is None:
            latest = await AgentState.filter(
                user_id=user_id, session_id=session_id
            ).order_by("-round_id").first()
            round_id = (latest.round_id + 1) if latest else 1
        
        await AgentState.update_or_create(
            defaults={"state": state},
            user_id=user_id,
            session_id=session_id,
            round_id=round_id,
        )
        return round_id
    
    @staticmethod
    async def get(
        user_id: str,
        session_id: str = "default",
        round_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """获取状态"""
        query = AgentState.filter(user_id=user_id, session_id=session_id)
        if round_id is not None:
            query = query.filter(round_id=round_id)
        else:
            query = query.order_by("-round_id")
        
        record = await query.first()
        return record.state if record else None
    
    @staticmethod
    async def delete(user_id: str, session_id: str) -> int:
        """删除状态"""
        return await AgentState.filter(user_id=user_id, session_id=session_id).delete()
