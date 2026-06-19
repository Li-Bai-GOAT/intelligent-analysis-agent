# -*- coding: utf-8 -*-
"""
会话 API
"""

import asyncio
import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks

from agentscope_runtime.engine.schemas.agent_schemas import Message
from agentscope_runtime.adapters.agentscope.message import message_to_agentscope_msg

from app.models.user import User
from app.api.deps import get_current_user
from app.schemas.session import SessionResponse, SessionDetailResponse, MessageResponse, ContextInfo
from app.config import settings
from app.repositories.session_repo import SessionRepository
from app.services.session_cleanup_service import get_cleanup_service
from app.services.model_factory import ModelFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["会话"])

# 压缩锁：记录正在压缩的会话
_compressing_sessions: dict[str, asyncio.Event] = {}


async def is_compressing(session_id: str) -> bool:
    """检查会话是否正在压缩"""
    return session_id in _compressing_sessions


async def wait_for_compression(session_id: str, timeout: float = 60.0) -> bool:
    """等待压缩完成，返回是否成功等待"""
    if session_id not in _compressing_sessions:
        return True
    
    event = _compressing_sessions[session_id]
    try:
        await asyncio.wait_for(event.wait(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        logger.warning(f"等待压缩超时: {session_id}")
        return False


def _msgs_to_text(msgs) -> str:
    """将消息列表转换为文本，用于压缩"""
    import json
    lines = []
    for msg in msgs:
        role = msg.role.upper()
        content_parts = []
        for block in msg.get_content_blocks():
            typ = block.get("type")
            if typ == "text":
                content_parts.append(block.get("text", ""))
            elif typ == "tool_use":
                name = block.get("name", "unknown")
                inp = json.dumps(block.get("input", {}), ensure_ascii=False)[:500]
                content_parts.append(f"[调用工具: {name}] {inp}")
            elif typ == "tool_result":
                name = block.get("name", "unknown")
                output = str(block.get("output", ""))[:1000]
                content_parts.append(f"[工具结果: {name}] {output}")
        content = "\n".join(content_parts)
        if content.strip():
            lines.append(f"[{role}]: {content[:2000]}")
    return "\n\n".join(lines)


async def _do_preemptive_compression(user_id: str, session_id: str) -> None:
    """
    执行预压缩
    
    逻辑：
    1. 获取历史摘要（如有），摘要覆盖了 covered_count 条消息
    2. 计算 "摘要 + 未覆盖消息" 的 token 数
    3. 如果超过阈值，压缩 "摘要 + 待压缩消息"（保留最近 N 条不压缩）
    4. 新摘要覆盖 = 原覆盖 + 新压缩的消息数
    """
    from app.services.agent_service import get_agent_service
    from app.services.compressed_memory import find_safe_cut_point
    from agentscope.message import Msg
    
    # 设置压缩锁
    event = asyncio.Event()
    _compressing_sessions[session_id] = event
    
    try:
        agent_service = await get_agent_service()
        
        # 获取会话消息
        session = await SessionRepository.get(user_id, session_id)
        if not session:
            return
        
        # get_messages 已按 call_id 配对重排序
        messages = await SessionRepository.get_messages(session)
        if not messages:
            return
        
        runtime_messages = [Message(**m.message) for m in messages]
        agentscope_msgs = message_to_agentscope_msg(runtime_messages)
        
        # 获取历史摘要
        previous_summary = await agent_service._get_session_summary(session_id)
        covered_count = previous_summary.get("covered_count", 0) if previous_summary else 0
        
        # 计算未被摘要覆盖的消息
        uncovered_msgs = agentscope_msgs[covered_count:]
        
        if not uncovered_msgs:
            logger.debug(f"会话 {session_id} 没有未覆盖消息")
            return
        
        # 计算 "摘要 + 未覆盖消息" 的 token 数
        msgs_to_count = []
        if previous_summary:
            summary_text = previous_summary.get("text", "")
            if summary_text:
                summary_msg = Msg(name="system", role="system", content=summary_text)
                msgs_to_count.append(summary_msg)
        msgs_to_count.extend(uncovered_msgs)
        
        _formatter = _get_formatter()
        formatted = await _formatter.format(msgs_to_count)
        current_tokens = await _formatter.token_counter.count(formatted)
        threshold = int(settings.MAX_TOKENS * settings.COMPRESS_THRESHOLD_PERCENT / 100)
        
        if current_tokens <= threshold:
            logger.debug(f"会话 {session_id} 未超阈值 ({current_tokens} <= {threshold})，跳过预压缩")
            return
        
        logger.info(f"开始预压缩会话 {session_id}: {current_tokens} tokens > {threshold}")
        
        # 计算保留的最近消息数
        keep_recent = min(settings.COMPRESS_KEEP_RECENT, len(uncovered_msgs))
        if keep_recent <= 0:
            return
        
        # 待压缩的消息 = 未覆盖消息中除了最近 N 条
        # 需要确保截断点不会切断 tool_call/tool_result 对
        compress_end_idx = len(uncovered_msgs) - keep_recent
        if compress_end_idx > 0:
            # 找到安全的截断点（向前移动，确保不切断配对）
            safe_end_idx = find_safe_cut_point(uncovered_msgs, compress_end_idx)
            # 如果安全点超过了原始点，说明需要少压缩一些
            if safe_end_idx > compress_end_idx:
                compress_end_idx = safe_end_idx
                # 但如果调整后没有可压缩的消息了，跳过
                if compress_end_idx >= len(uncovered_msgs):
                    logger.debug(f"会话 {session_id} 调整后没有需要压缩的消息")
                    return
        
        to_compress_msgs = uncovered_msgs[:compress_end_idx] if compress_end_idx > 0 else []
        
        if not to_compress_msgs:
            logger.debug(f"会话 {session_id} 没有需要压缩的消息")
            return
        
        # 构建压缩输入
        compress_input_parts = []
        if previous_summary:
            prev_text = previous_summary.get("text", "")
            if prev_text:
                compress_input_parts.append("【历史摘要】\n" + prev_text)
        
        compress_input_parts.append("【新对话内容】\n" + _msgs_to_text(to_compress_msgs))
        compress_input = "\n\n".join(compress_input_parts)
        
        # 调用压缩
        new_summary = await agent_service._compress_context(compress_input)
        
        # 计算新的覆盖数量 = 原覆盖 + 本次压缩的消息数
        new_covered_count = covered_count + len(to_compress_msgs)
        
        # 保存摘要
        await agent_service._set_session_summary(session_id, new_summary, new_covered_count)
        
        logger.info(f"预压缩完成: 会话 {session_id}, 新压缩 {len(to_compress_msgs)} 条, 总覆盖 {new_covered_count} 条")
        
    except Exception as e:
        logger.error(f"预压缩失败: {session_id}, {e}")
    finally:
        # 释放锁
        event.set()
        _compressing_sessions.pop(session_id, None)


@router.get("", response_model=List[SessionResponse], summary="获取会话列表")
async def list_sessions(user: User = Depends(get_current_user)):
    """列出当前用户的所有会话（仅元数据，不含消息内容）"""
    sessions = await SessionRepository.list_by_user(str(user.id))
    result = []
    for s in sessions:
        messages = await SessionRepository.get_messages(s)
        result.append(SessionResponse(
            id=s.id,
            session_id=s.session_id,
            user_id=s.user_id,
            name=s.name,  # 会话名称（用户第一条消息）
            created_at=s.created_at,
            updated_at=s.updated_at,
            message_count=len(messages),
        ))
    return result


def _get_formatter():
    """获取格式化器（动态创建，支持多模型切换）"""
    _, formatter, _ = ModelFactory.create_model_and_formatter(
        tool_output_max_length=settings.TOOL_OUTPUT_MAX_LENGTH,
    )
    return formatter


@router.get("/{session_id}", response_model=SessionDetailResponse, summary="获取会话详情")
async def get_session(
    session_id: str, 
    background_tasks: BackgroundTasks,
    user: User = Depends(get_current_user),
):
    """获取指定会话的完整信息，包含所有历史消息"""
    user_id = str(user.id)
    session = await SessionRepository.get(user_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    
    # get_messages 已按 call_id 配对重排序
    db_messages = await SessionRepository.get_messages(session)
    
    # 计算实际 token 使用量（考虑摘要覆盖）
    # 如果有摘要，计算: 摘要 + 未覆盖消息
    # 如果没有摘要，计算: 全部消息
    total_tokens = 0
    if db_messages:
        try:
            from app.services.agent_service import get_agent_service
            from agentscope.message import Msg
            
            agent_service = await get_agent_service()
            summary = await agent_service._get_session_summary(session_id)
            covered_count = summary.get("covered_count", 0) if summary else 0
            
            # 1. DB dict -> Message 对象
            runtime_messages = [Message(**m.message) for m in db_messages]
            # 2. Message -> AgentScope Msg 对象
            agentscope_msgs = message_to_agentscope_msg(runtime_messages)
            
            # 3. 构建实际发送给 Agent 的消息（摘要 + 未覆盖消息）
            msgs_to_count = []
            if summary and covered_count > 0:
                summary_text = summary.get("text", "")
                if summary_text:
                    summary_msg = Msg(name="system", role="system", content=summary_text)
                    msgs_to_count.append(summary_msg)
                # 只计算未覆盖的消息
                msgs_to_count.extend(agentscope_msgs[covered_count:])
            else:
                msgs_to_count = agentscope_msgs
            
            # 4. 格式化并计数
            _formatter = _get_formatter()
            formatted = await _formatter.format(msgs_to_count)
            total_tokens = await _formatter.token_counter.count(formatted)
        except Exception as e:
            logger.warning(f"Token counting failed: {e}, using 0")
            total_tokens = 0
    
    max_tokens = settings.MAX_TOKENS
    usage_percent = round(total_tokens / max_tokens * 100, 1) if max_tokens > 0 else 0
    
    # 检查是否需要预压缩（超过阈值且未在压缩中）
    threshold_percent = settings.COMPRESS_THRESHOLD_PERCENT
    if usage_percent >= threshold_percent and not await is_compressing(session_id):
        logger.info(f"触发预压缩: 会话 {session_id}, 使用率 {usage_percent}% >= {threshold_percent}%")
        # 后台执行压缩，不阻塞返回
        background_tasks.add_task(_do_preemptive_compression, user_id, session_id)
    
    return SessionDetailResponse(
        id=session.id,
        session_id=session.session_id,
        user_id=session.user_id,
        created_at=session.created_at,
        updated_at=session.updated_at,
        messages=[
            MessageResponse(
                id=m.id,
                role=m.message.get("role", "unknown"),
                msg_type=m.message.get("type", "message"),  # 保留消息类型：message, reasoning, plugin_call等
                content=m.message.get("content", ""),
                file_ids=m.message.get("metadata", {}).get("file_ids") if m.message.get("metadata") else None,
                file_paths=m.message.get("metadata", {}).get("file_paths") if m.message.get("metadata") else None,
                created_at=m.created_at,
            )
            for m in db_messages
        ],
        context_info=ContextInfo(
            estimated_tokens=total_tokens,
            max_tokens=max_tokens,
            usage_percent=usage_percent,
        ),
    )


@router.delete("/{session_id}", summary="删除会话")
async def delete_session(session_id: str, user: User = Depends(get_current_user)):
    """
    删除指定会话及其所有关联数据
    
    清理内容：
    - 会话消息表 (session_messages)
    - 会话表 (sessions)
    - Agent 状态表 (agent_states)
    - 用户文件表 (user_files)
    - 沙箱绑定表 (sandbox_bindings)
    - Redis 相关键
    """
    user_id = str(user.id)
    
    # 先检查会话是否存在
    session = await SessionRepository.get(user_id, session_id)
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    
    # 使用清理服务完整清理
    cleanup_service = await get_cleanup_service()
    result = await cleanup_service.cleanup_session(user_id, session_id)
    
    if not result["success"]:
        logger.warning(f"会话 {session_id} 清理部分失败: {result['errors']}")
    
    logger.info(f"会话 {session_id} 删除完成: {result['deleted']}")
    
    return {
        "success": True, 
        "message": f"会话 {session_id} 已删除",
        "deleted": result["deleted"],
    }
