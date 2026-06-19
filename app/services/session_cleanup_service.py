# -*- coding: utf-8 -*-
"""
会话清理服务

删除会话时清理所有关联数据：
- 会话消息表 (session_messages) - CASCADE 自动删除
- 会话表 (sessions)
- Agent 状态表 (agent_states)
- 用户文件表 (user_files)
- 沙箱绑定表 (sandbox_bindings)
- Redis 相关键
- Celery 任务（如果有）
"""

import logging
import redis.asyncio as aioredis

from app.config import settings
from app.models.session import Session
from app.models.agent_state import AgentState
from app.models.file import UserFile, SandboxBinding

logger = logging.getLogger(__name__)


class SessionCleanupService:
    """会话清理服务"""
    
    def __init__(self):
        self._redis = None
    
    async def _get_redis(self) -> aioredis.Redis:
        """获取 Redis 连接"""
        if self._redis is None:
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._redis
    
    async def cleanup_session(self, user_id: str, session_id: str) -> dict:
        """
        完整清理会话及其所有关联数据
        
        Args:
            user_id: 用户 ID
            session_id: 会话 ID
            
        Returns:
            清理结果统计
        """
        result = {
            "session_id": session_id,
            "success": True,
            "deleted": {},
            "errors": [],
        }
        
        logger.info(f"开始清理会话: {session_id} (用户: {user_id})")
        
        # 1. 删除会话（SessionMessage 会通过 CASCADE 自动删除）
        try:
            session_count = await Session.filter(
                user_id=user_id, session_id=session_id
            ).delete()
            result["deleted"]["sessions"] = session_count
            logger.info(f"  删除会话表记录: {session_count}")
        except Exception as e:
            result["errors"].append(f"删除会话失败: {e}")
            logger.error(f"  删除会话失败: {e}")
        
        # 2. 删除 Agent 状态
        try:
            state_count = await AgentState.filter(
                user_id=user_id, session_id=session_id
            ).delete()
            result["deleted"]["agent_states"] = state_count
            logger.info(f"  删除 Agent 状态: {state_count}")
        except Exception as e:
            result["errors"].append(f"删除 Agent 状态失败: {e}")
            logger.error(f"  删除 Agent 状态失败: {e}")
        
        # 3. 删除用户文件（注意：这里只删除数据库记录，不删除实际文件）
        try:
            file_count = await UserFile.filter(
                user_id=user_id, session_id=session_id
            ).delete()
            result["deleted"]["user_files"] = file_count
            logger.info(f"  删除用户文件记录: {file_count}")
        except Exception as e:
            result["errors"].append(f"删除用户文件失败: {e}")
            logger.error(f"  删除用户文件失败: {e}")
        
        # 4. 删除沙箱绑定
        try:
            binding_count = await SandboxBinding.filter(
                user_id=user_id, session_id=session_id
            ).delete()
            result["deleted"]["sandbox_bindings"] = binding_count
            logger.info(f"  删除沙箱绑定: {binding_count}")
        except Exception as e:
            result["errors"].append(f"删除沙箱绑定失败: {e}")
            logger.error(f"  删除沙箱绑定失败: {e}")
        
        # 5. 清理 Redis 相关键
        try:
            redis = await self._get_redis()
            
            # 先获取 task_id（在删除 session_task 键之前）
            task_id = await redis.get(f"session_task:{session_id}")
            
            # 删除任务流
            if task_id:
                task_stream_key = f"task_stream:{task_id}"
                deleted = await redis.delete(task_stream_key)
                result["deleted"]["task_streams"] = deleted
                logger.info(f"  删除任务流: {task_stream_key}")
            else:
                result["deleted"]["task_streams"] = 0
            
            # 删除其他会话相关键
            redis_keys = [
                f"session_task:{session_id}",
                f"agent_interrupt:{session_id}",
                f"auto_continue:{session_id}",
                f"plan_pending:{session_id}",
                f"kuncode_pending:{session_id}",
            ]
            
            # 使用 SCAN 查找所有与会话相关的键
            pattern_keys = []
            async for key in redis.scan_iter(f"*:{session_id}:*"):
                pattern_keys.append(key)
            async for key in redis.scan_iter(f"*:{session_id}"):
                if key not in redis_keys:
                    pattern_keys.append(key)
            
            all_keys = redis_keys + pattern_keys
            deleted_count = 0
            for key in all_keys:
                try:
                    deleted = await redis.delete(key)
                    deleted_count += deleted
                except Exception:
                    pass
            
            result["deleted"]["redis_keys"] = deleted_count
            logger.info(f"  删除 Redis 键: {deleted_count}")
        except Exception as e:
            result["errors"].append(f"清理 Redis 失败: {e}")
            logger.error(f"  清理 Redis 失败: {e}")
        
        if result["errors"]:
            result["success"] = False
        
        logger.info(f"会话清理完成: {session_id}, 结果: {result}")
        return result
    
    async def close(self):
        """关闭连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None


# 单例
_cleanup_service: SessionCleanupService = None


async def get_cleanup_service() -> SessionCleanupService:
    """获取清理服务实例"""
    global _cleanup_service
    if _cleanup_service is None:
        _cleanup_service = SessionCleanupService()
    return _cleanup_service
