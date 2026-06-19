# -*- coding: utf-8 -*-
"""
会话数据访问层
"""

import logging
from typing import Optional, List, Dict

from app.models.session import Session, SessionMessage

logger = logging.getLogger(__name__)


async def _reorder_by_call_id(messages: List[SessionMessage]) -> List[SessionMessage]:
    """
    重排序消息，确保 plugin_call 后面紧跟对应的 plugin_call_output
    
    解决 HITL 工具等待用户确认期间，其他工具执行导致的消息乱序问题。
    孤立的 plugin_call_output 会从数据库中删除。
    """
    if not messages:
        return messages
    
    # 提取 call_id -> SessionMessage 的映射
    call_id_to_output: Dict[str, SessionMessage] = {}
    output_indices = set()
    
    for i, msg in enumerate(messages):
        msg_dict = msg.message
        msg_type = msg_dict.get("type") or msg_dict.get("msg_type")
        if msg_type in ("plugin_call_output", "plugin_call_result"):
            for item in msg_dict.get("content", []):
                if isinstance(item, dict) and item.get("type") == "data":
                    call_id = item.get("data", {}).get("call_id")
                    if call_id:
                        call_id_to_output[call_id] = msg
                        output_indices.add(i)
    
    if not call_id_to_output:
        return messages
    
    # 重排序：plugin_call 后紧跟其 plugin_call_output
    result = []
    used_call_ids = set()
    
    for i, msg in enumerate(messages):
        if i in output_indices:
            continue  # 跳过，稍后插入
        
        result.append(msg)
        
        msg_dict = msg.message
        msg_type = msg_dict.get("type") or msg_dict.get("msg_type")
        if msg_type == "plugin_call":
            for item in msg_dict.get("content", []):
                if isinstance(item, dict) and item.get("type") == "data":
                    call_id = item.get("data", {}).get("call_id")
                    if call_id and call_id in call_id_to_output and call_id not in used_call_ids:
                        result.append(call_id_to_output[call_id])
                        used_call_ids.add(call_id)
    
    # 孤立的 plugin_call_output 从数据库中删除
    for call_id, output_msg in call_id_to_output.items():
        if call_id not in used_call_ids:
            logger.warning(f"删除孤立的 plugin_call_output，call_id={call_id}, msg_id={output_msg.id}")
            await output_msg.delete()
    
    return result


class SessionRepository:
    """会话数据访问"""
    
    @staticmethod
    async def create(user_id: str, session_id: str) -> Session:
        return await Session.create(user_id=user_id, session_id=session_id)
    
    @staticmethod
    async def get(user_id: str, session_id: str) -> Optional[Session]:
        return await Session.filter(user_id=user_id, session_id=session_id).first()
    
    @staticmethod
    async def get_or_create(user_id: str, session_id: str) -> Session:
        session = await Session.filter(user_id=user_id, session_id=session_id).first()
        if not session:
            session = await Session.create(user_id=user_id, session_id=session_id)
        return session
    
    @staticmethod
    async def list_by_user(user_id: str) -> List[Session]:
        return await Session.filter(user_id=user_id).order_by("-updated_at")
    
    @staticmethod
    async def delete(user_id: str, session_id: str) -> int:
        return await Session.filter(user_id=user_id, session_id=session_id).delete()
    
    @staticmethod
    async def delete_all_by_user(user_id: str) -> int:
        return await Session.filter(user_id=user_id).delete()
    
    @staticmethod
    async def append_message(session: Session, message: dict) -> SessionMessage:
        session.updated_at = None  # 触发 auto_now
        await session.save()
        return await SessionMessage.create(session=session, message=message)
    
    @staticmethod
    async def get_messages(session: Session) -> List[SessionMessage]:
        """获取会话消息，已按 call_id 配对重排序"""
        messages = await SessionMessage.filter(session=session).order_by("created_at")
        return await _reorder_by_call_id(messages)
    
    @staticmethod
    async def update_name(session: Session, name: str) -> None:
        """更新会话名称"""
        session.name = name[:200] if name else None  # 限制长度
        await session.save()
    
    @staticmethod
    async def insert_after_plugin_call(session: Session, call_id: str, message: dict) -> Optional[SessionMessage]:
        """
        在指定 call_id 的 plugin_call 消息后插入 plugin_call_output
        
        通过设置 created_at 为 plugin_call 的 created_at + 1微秒 来保证顺序
        """
        from datetime import timedelta
        
        # 找到包含此 call_id 的 plugin_call 消息
        messages = await SessionMessage.filter(session=session).order_by("created_at")
        target_msg = None
        for msg in messages:
            msg_type = msg.message.get("type") or msg.message.get("msg_type")
            if msg_type == "plugin_call":
                content = msg.message.get("content", [])
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "data":
                        if item.get("data", {}).get("call_id") == call_id:
                            target_msg = msg
                            break
                if target_msg:
                    break
        
        if not target_msg:
            # 找不到对应的 plugin_call，直接追加到末尾
            return await SessionMessage.create(session=session, message=message)
        
        # 在 plugin_call 后插入，created_at 设为 plugin_call 的 created_at + 1微秒
        new_created_at = target_msg.created_at + timedelta(microseconds=1)
        new_msg = SessionMessage(session=session, message=message)
        new_msg.created_at = new_created_at
        await new_msg.save()
        
        # 更新会话时间
        session.updated_at = None
        await session.save()
        
        return new_msg
