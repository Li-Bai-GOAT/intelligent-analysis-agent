# -*- coding: utf-8 -*-
"""
PostgreSQL 智能体状态服务

继承 agentscope-runtime StateService 基类
"""

from typing import Optional, Dict, Any

from agentscope_runtime.engine.services.agent_state.state_service import StateService

from app.repositories.state_repo import StateRepository


class PostgresStateService(StateService):
    """
    PostgreSQL 状态服务
    
    继承 StateService 基类，使用 PostgreSQL 持久化
    """
    
    def __init__(self):
        self._started = False
    
    async def start(self) -> None:
        """启动服务"""
        self._started = True
    
    async def stop(self) -> None:
        """停止服务"""
        self._started = False
    
    async def health(self) -> bool:
        """健康检查"""
        return self._started
    
    async def save_state(
        self,
        user_id: str,
        state: Dict[str, Any],
        session_id: Optional[str] = None,
        round_id: Optional[int] = None,
    ) -> int:
        """保存状态，返回 round_id"""
        session_id = session_id or "default"
        return await StateRepository.save(user_id, state, session_id, round_id)
    
    async def export_state(
        self,
        user_id: str,
        session_id: Optional[str] = None,
        round_id: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """导出状态，不存在则返回 None"""
        session_id = session_id or "default"
        return await StateRepository.get(user_id, session_id, round_id)
    
    async def delete_state(self, user_id: str, session_id: str) -> None:
        """删除状态"""
        await StateRepository.delete(user_id, session_id)
