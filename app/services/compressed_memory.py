# -*- coding: utf-8 -*-
"""
带压缩支持的会话历史内存

继承 AgentScopeSessionHistoryMemory，支持跳过被摘要覆盖的消息。
"""
from typing import List

from agentscope.message import Msg

from agentscope_runtime.adapters.agentscope.memory import AgentScopeSessionHistoryMemory
from agentscope_runtime.adapters.agentscope.message import message_to_agentscope_msg


def find_safe_cut_point(msgs: List[Msg], target_index: int) -> int:
    """
    找到安全的截断点，确保不会切断 tool_call/tool_result 对
    
    规则：如果 target_index 指向的消息是 tool_result，则向后移动到下一条非 tool_result 消息
    
    Args:
        msgs: 消息列表
        target_index: 目标截断索引
        
    Returns:
        安全的截断索引（从该索引开始的消息不会缺少配对的 tool_call）
    """
    if target_index <= 0:
        return 0
    if target_index >= len(msgs):
        return len(msgs)
    
    # 检查 target_index 位置的消息是否是 tool_result
    # 如果是，需要向后移动直到找到非 tool_result 的消息
    while target_index < len(msgs):
        msg = msgs[target_index]
        blocks = msg.get_content_blocks()
        has_tool_result = any(b.get("type") == "tool_result" for b in blocks)
        if not has_tool_result:
            break
        target_index += 1
    
    return target_index


class CompressedSessionMemory(AgentScopeSessionHistoryMemory):
    """
    支持压缩的会话历史内存
    
    通过 skip_count 参数跳过被摘要覆盖的消息，
    只返回未被覆盖的消息给 Agent。
    """
    
    def __init__(
        self,
        service,
        user_id: str,
        session_id: str,
        skip_count: int = 0,
    ):
        """
        Args:
            service: 会话历史服务
            user_id: 用户 ID
            session_id: 会话 ID
            skip_count: 跳过的消息数量（被摘要覆盖的消息）
        """
        super().__init__(service=service, user_id=user_id, session_id=session_id)
        self.skip_count = skip_count
    
    async def get_memory(self) -> list[Msg]:
        """
        获取内存内容，跳过被摘要覆盖的消息
        """
        await self._check_session()
        current_message = self._session.messages
        agentscope_msgs = message_to_agentscope_msg(current_message)
        
        # 跳过被摘要覆盖的消息，确保不切断 tool_call/tool_result 对
        if self.skip_count > 0 and len(agentscope_msgs) > self.skip_count:
            safe_skip = find_safe_cut_point(agentscope_msgs, self.skip_count)
            return agentscope_msgs[safe_skip:]
        
        return agentscope_msgs
    
    async def size(self) -> int:
        """返回未被覆盖的消息数量"""
        await self._check_session()
        current_message = self._session.messages
        agentscope_msgs = message_to_agentscope_msg(current_message)
        
        if self.skip_count > 0:
            return max(0, len(agentscope_msgs) - self.skip_count)
        
        return len(agentscope_msgs)
