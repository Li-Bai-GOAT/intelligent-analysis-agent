# -*- coding: utf-8 -*-
"""
检查数据库中消息的实际存储格式
"""

import asyncio
import json
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from tortoise import Tortoise
from app.models.session import SessionMessage
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


async def main():
    """检查消息格式"""
    print("=" * 60)
    print("检查数据库中消息的实际存储格式")
    print("=" * 60)
    
    await init_db()
    
    try:
        # 获取最近的一些消息
        messages = await SessionMessage.all().order_by("-created_at").limit(50)
        
        # 统计各种消息类型
        type_counts = {}
        role_counts = {}
        
        print(f"\n共检查 {len(messages)} 条最近的消息\n")
        
        for msg in messages:
            message = msg.message
            
            # 统计 type
            msg_type = message.get("type", "无type字段")
            type_counts[msg_type] = type_counts.get(msg_type, 0) + 1
            
            # 统计 role
            role = message.get("role", "无role字段")
            role_counts[role] = role_counts.get(role, 0) + 1
        
        print("=== 按 type 字段统计 ===")
        for t, count in sorted(type_counts.items(), key=lambda x: -x[1]):
            print(f"  {t}: {count}")
        
        print("\n=== 按 role 字段统计 ===")
        for r, count in sorted(role_counts.items(), key=lambda x: -x[1]):
            print(f"  {r}: {count}")
        
        # 找几条典型消息展示格式
        print("\n" + "=" * 60)
        print("典型消息格式示例")
        print("=" * 60)
        
        shown_types = set()
        for msg in messages:
            message = msg.message
            msg_type = message.get("type", "unknown")
            role = message.get("role", "unknown")
            key = f"{msg_type}_{role}"
            
            if key not in shown_types:
                shown_types.add(key)
                print(f"\n--- type={msg_type}, role={role} ---")
                # 只打印前1000字符避免太长
                msg_str = json.dumps(message, indent=2, ensure_ascii=False)
                if len(msg_str) > 1000:
                    msg_str = msg_str[:1000] + "\n... (truncated)"
                print(msg_str)
        
        # 特别查找 plugin_call 和 plugin_call_output 类型
        print("\n" + "=" * 60)
        print("查找 plugin_call 相关消息 (手动遍历)")
        print("=" * 60)
        
        all_messages = await SessionMessage.all().order_by("-created_at").limit(200)
        
        plugin_calls = []
        plugin_outputs = []
        
        for msg in all_messages:
            msg_type = msg.message.get("type", "")
            if msg_type == "plugin_call":
                plugin_calls.append(msg.message)
            elif msg_type == "plugin_call_output":
                plugin_outputs.append(msg.message)
        
        print(f"\n找到 {len(plugin_calls)} 条 plugin_call 消息")
        if plugin_calls:
            print("示例:")
            print(json.dumps(plugin_calls[0], indent=2, ensure_ascii=False)[:1200])
        
        print(f"\n找到 {len(plugin_outputs)} 条 plugin_call_output 消息")
        if plugin_outputs:
            print("示例:")
            print(json.dumps(plugin_outputs[0], indent=2, ensure_ascii=False)[:1200])
    
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
