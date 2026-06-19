# -*- coding: utf-8 -*-
"""
修复历史数据中缺少 tool_result 的记录

问题：当用户在工具执行过程中中断对话时，assistant 消息包含 tool_calls，
但没有对应的 tool_result 消息，导致后续对话时 API 报错：
"An assistant message with 'tool_calls' must be followed by tool messages"

解决方案：扫描所有会话消息，找出缺少 tool_result 的 tool_calls，
为它们添加 "[用户中断调用]" 的 tool_result 消息。

使用方法：
    python scripts/fix_missing_tool_results.py [--dry-run]
    
    --dry-run: 只检测不修复，显示需要修复的会话
"""

import asyncio
import argparse
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.models.session import Session, SessionMessage
from app.config import settings


async def init_db():
    """初始化数据库连接"""
    await Tortoise.init(
        db_url=settings.DATABASE_URL,
        modules={"models": ["app.models"]},
    )


async def close_db():
    """关闭数据库连接"""
    await Tortoise.close_connections()


def extract_tool_calls(message: dict) -> list:
    """
    从消息中提取 tool_calls 的 id 和 name
    
    实际数据库格式: type="plugin_call", role="assistant"
    content=[{type: "data", data: {call_id, name, arguments}}]
    """
    tool_calls = []
    msg_type = message.get("type", "")
    
    # 实际数据库格式: type="plugin_call"
    if msg_type == "plugin_call":
        content = message.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "data":
                    data = item.get("data", {})
                    tool_id = data.get("call_id")
                    tool_name = data.get("name", "unknown")
                    if tool_id:
                        tool_calls.append({"id": tool_id, "name": tool_name})
    
    return tool_calls


def extract_tool_results(message: dict) -> set:
    """
    从消息中提取 tool_result 的 id
    
    实际数据库格式: type="plugin_call_output", role="system"
    content=[{type: "data", data: {call_id, name, output}}]
    """
    tool_result_ids = set()
    msg_type = message.get("type", "")
    
    # 实际数据库格式: type="plugin_call_output"
    if msg_type == "plugin_call_output":
        content = message.get("content", [])
        if isinstance(content, list):
            for item in content:
                if isinstance(item, dict) and item.get("type") == "data":
                    data = item.get("data", {})
                    tool_id = data.get("call_id")
                    if tool_id:
                        tool_result_ids.add(tool_id)
    
    return tool_result_ids


async def find_missing_tool_results(session: Session) -> list:
    """
    查找会话中缺少 plugin_call_output 的 plugin_calls
    
    返回: [(tool_id, tool_name, message_id), ...]
    """
    messages = await SessionMessage.filter(session=session).order_by("created_at")
    
    # 收集所有 plugin_calls 和 plugin_call_outputs
    pending_tool_calls = {}  # tool_id -> (tool_name, message_id)
    
    for msg in messages:
        message = msg.message
        msg_type = message.get("type", "")
        
        # plugin_call 消息包含 tool_calls
        if msg_type == "plugin_call":
            for tc in extract_tool_calls(message):
                pending_tool_calls[tc["id"]] = (tc["name"], msg.id)
        
        # plugin_call_output 消息包含 tool_results
        elif msg_type == "plugin_call_output":
            for tool_id in extract_tool_results(message):
                pending_tool_calls.pop(tool_id, None)
    
    # 返回仍然缺少 result 的 tool_calls
    return [(tid, name, mid) for tid, (name, mid) in pending_tool_calls.items()]


async def fix_session(session: Session, missing: list, dry_run: bool) -> int:
    """
    修复单个会话中缺少的 tool_results
    
    返回修复的数量
    """
    if not missing:
        return 0
    
    fixed = 0
    for tool_id, tool_name, after_msg_id in missing:
        if dry_run:
            print(f"    [DRY-RUN] 需要为 tool_call {tool_id} ({tool_name}) 添加 plugin_call_output")
        else:
            # 构建符合实际数据库存储格式的 plugin_call_output
            # 格式来自: scripts/check_message_format.py 检查结果
            interrupted_result = {
                "type": "plugin_call_output",
                "role": "system",
                "object": "message",
                "status": "completed",
                "content": [
                    {
                        "type": "data",
                        "data": {
                            "call_id": tool_id,
                            "name": tool_name,
                            "output": "[{\"type\": \"text\", \"text\": \"[用户中断调用]\"}]",
                        }
                    }
                ],
            }
            await SessionMessage.create(session=session, message=interrupted_result)
            print(f"    已修复 tool_call {tool_id} ({tool_name})")
        fixed += 1
    
    return fixed


async def main(dry_run: bool = False):
    """主函数"""
    print("=" * 60)
    print("修复历史数据中缺少 tool_result 的记录")
    print("=" * 60)
    
    if dry_run:
        print("\n[DRY-RUN 模式] 只检测不修复\n")
    
    await init_db()
    
    try:
        # 获取所有会话
        sessions = await Session.all()
        print(f"共有 {len(sessions)} 个会话需要检查\n")
        
        total_fixed = 0
        sessions_with_issues = 0
        
        for session in sessions:
            missing = await find_missing_tool_results(session)
            
            if missing:
                sessions_with_issues += 1
                print(f"会话 {session.session_id} (用户: {session.user_id}):")
                print(f"  发现 {len(missing)} 个缺少 tool_result 的 tool_calls")
                
                fixed = await fix_session(session, missing, dry_run)
                total_fixed += fixed
                print()
        
        print("=" * 60)
        print("检查完成:")
        print(f"  - 检查会话数: {len(sessions)}")
        print(f"  - 有问题的会话: {sessions_with_issues}")
        print(f"  - {'需要修复' if dry_run else '已修复'}的 tool_calls: {total_fixed}")
        print("=" * 60)
        
        if dry_run and total_fixed > 0:
            print("\n提示: 运行 `python scripts/fix_missing_tool_results.py` (不带 --dry-run) 来执行修复")
    
    finally:
        await close_db()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="修复历史数据中缺少 tool_result 的记录")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只检测不修复，显示需要修复的会话",
    )
    args = parser.parse_args()
    
    asyncio.run(main(dry_run=args.dry_run))
