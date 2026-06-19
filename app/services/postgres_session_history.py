# -*- coding: utf-8 -*-
"""
PostgreSQL 会话历史服务

继承 agentscope-runtime SessionHistoryService 基类，消息格式与 agentscope-runtime 保持一致
"""

import uuid
from typing import Optional, List, Dict, Any, Union

from agentscope_runtime.engine.services.session_history.session_history_service import (
    SessionHistoryService,
)
from agentscope_runtime.engine.schemas.session import Session as RuntimeSession
from agentscope_runtime.engine.schemas.agent_schemas import Message

from app.repositories.session_repo import SessionRepository


class PostgresSessionHistoryService(SessionHistoryService):
    """
    PostgreSQL 会话历史服务
    
    消息格式与 RedisSessionHistoryService 保持一致，使用 agentscope-runtime 的 Message schema
    """
    
    def __init__(self):
        self._started = False
    
    async def start(self) -> None:
        """启动服务（数据库连接由 app 统一管理）"""
        self._started = True
    
    async def stop(self) -> None:
        """停止服务"""
        self._started = False
    
    async def health(self) -> bool:
        """健康检查"""
        return self._started
    
    async def create_session(
        self,
        user_id: str,
        session_id: Optional[str] = None,
    ) -> RuntimeSession:
        """创建会话"""
        if not session_id:
            session_id = f"session_{uuid.uuid4().hex[:12]}"
        
        db_session = await SessionRepository.get_or_create(user_id, session_id)
        return RuntimeSession(
            id=db_session.session_id,
            user_id=db_session.user_id,
            messages=[],
        )
    
    async def get_session(
        self,
        user_id: str,
        session_id: str,
    ) -> Optional[RuntimeSession]:
        """获取会话（含消息列表）"""
        db_session = await SessionRepository.get(user_id, session_id)
        if not db_session:
            return None
        
        # get_messages 已按 call_id 配对重排序
        db_messages = await SessionRepository.get_messages(db_session)
        messages = [Message.model_validate(m.message) for m in db_messages]
        
        return RuntimeSession(
            id=db_session.session_id,
            user_id=db_session.user_id,
            messages=messages,
        )
    
    async def list_sessions(self, user_id: str) -> List[RuntimeSession]:
        """列出用户所有会话"""
        sessions = await SessionRepository.list_by_user(user_id)
        return [
            RuntimeSession(id=s.session_id, user_id=s.user_id, messages=[])
            for s in sessions
        ]
    
    async def delete_session(self, user_id: str, session_id: str) -> None:
        """删除会话"""
        await SessionRepository.delete(user_id, session_id)
    
    async def delete_user_sessions(self, user_id: str) -> None:
        """删除用户所有会话"""
        await SessionRepository.delete_all_by_user(user_id)
    
    async def append_message(
        self,
        session: RuntimeSession,
        message: Union[Message, Dict[str, Any], List[Union[Message, Dict[str, Any]]]],
    ) -> None:
        """
        追加消息到会话
        
        消息会被标准化为 agentscope-runtime Message 格式存储
        """
        db_session = await SessionRepository.get(session.user_id, session.id)
        if not db_session:
            return
        
        messages = message if isinstance(message, list) else [message]
        for msg in messages:
            if msg is None:
                continue
            # 标准化为 Message 格式
            if isinstance(msg, Message):
                msg_dict = msg.model_dump()
            elif isinstance(msg, dict):
                try:
                    # 尝试验证并转换为标准 Message 格式
                    validated = Message.model_validate(msg)
                    msg_dict = validated.model_dump()
                except Exception:
                    # 如果验证失败，保持原格式
                    msg_dict = msg
            else:
                msg_dict = self._msg_to_dict(msg)
            
            await SessionRepository.append_message(db_session, msg_dict)
            # 同步更新内存中的 session
            session.messages.append(msg_dict)
            
            # 如果会话没有名称且是用户消息，用第一条用户消息作为会话名称
            if not db_session.name and msg_dict.get("role") == "user":
                content = msg_dict.get("content", "")
                # 提取文本内容
                if isinstance(content, list):
                    text_parts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"]
                    name = " ".join(text_parts)
                else:
                    name = str(content)
                # 清理并截取
                name = name.replace("[系统提示]", "").strip()
                if name:
                    await SessionRepository.update_name(db_session, name[:100])
    
    @staticmethod
    def _msg_to_dict(msg) -> dict:
        """将 Message 对象转为字典"""
        if hasattr(msg, "model_dump"):
            return msg.model_dump()
        if hasattr(msg, "to_dict"):
            return msg.to_dict()
        if hasattr(msg, "__dict__"):
            return {k: v for k, v in msg.__dict__.items() if not k.startswith("_")}
        return {"content": str(msg)}
