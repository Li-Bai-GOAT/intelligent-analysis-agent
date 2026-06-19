#!/usr/bin/env python
"""临时脚本：修复会话中缺失的 plugin_call_output（按正确顺序）"""

import asyncio
from datetime import timedelta
from app.models.session import Session, SessionMessage
from app.database import init_db

async def fix_session(session_id: str):
    await init_db()
    
    session = await Session.filter(session_id=session_id).first()
    if not session:
        print(f"Session {session_id} not found")
        return
    
    print(f"Fixing session: {session_id}")
    print(f"User ID: {session.user_id}")
    
    messages = list(await SessionMessage.filter(session=session).order_by("created_at"))
    
    # 收集 plugin_call 的位置和信息
    call_info = {}  # call_id -> (index, name, created_at)
    result_ids = set()
    
    for idx, m in enumerate(messages):
        msg = m.message
        msg_type = msg.get("type", "")
        content = msg.get("content", [])
        if not isinstance(content, list):
            continue
        
        if msg_type == "plugin_call":
            for item in content:
                if isinstance(item, dict) and item.get("type") == "data":
                    data = item.get("data", {})
                    call_id = data.get("call_id", "")
                    name = data.get("name", "unknown")
                    if call_id:
                        call_info[call_id] = (idx, name, m.created_at)
        
        elif msg_type == "plugin_call_output":
            for item in content:
                if isinstance(item, dict) and item.get("type") == "data":
                    data = item.get("data", {})
                    call_id = data.get("call_id", "")
                    if call_id:
                        result_ids.add(call_id)
    
    # 找出缺失的
    pending = {k: v for k, v in call_info.items() if k not in result_ids}
    
    print(f"Total plugin_calls: {len(call_info)}")
    print(f"Total plugin_call_outputs: {len(result_ids)}")
    print(f"Missing results: {len(pending)}")
    
    if not pending:
        print("No missing results, nothing to fix!")
        return
    
    print("\nMissing call_ids:")
    for call_id, (idx, name, created_at) in pending.items():
        print(f"  - {call_id}: {name} (index={idx}, time={created_at})")
    
    # 先删除末尾错误位置的 plugin_call_output（如果有）
    print("\nRemoving wrongly positioned plugin_call_outputs...")
    for m in messages:
        msg = m.message
        if msg.get("type") == "plugin_call_output":
            content = msg.get("content", [])
            for item in content:
                if isinstance(item, dict) and item.get("type") == "data":
                    data = item.get("data", {})
                    call_id = data.get("call_id", "")
                    if call_id in pending:
                        print(f"  Deleting wrongly positioned result for {call_id}")
                        await m.delete()
    
    # 在正确位置插入（设置 created_at 为对应 plugin_call 之后 1 毫秒）
    print("\nInserting plugin_call_outputs at correct positions...")
    for call_id, (idx, name, created_at) in pending.items():
        result = {
            "type": "plugin_call_output",
            "role": "system",
            "object": "message",
            "status": "completed",
            "content": [
                {
                    "type": "data",
                    "data": {
                        "call_id": call_id,
                        "name": name,
                        "output": "[{\"type\": \"text\", \"text\": \"[用户中断调用]\"}]",
                    }
                }
            ],
        }
        # 创建并手动设置 created_at
        new_msg = await SessionMessage.create(session=session, message=result)
        new_msg.created_at = created_at + timedelta(milliseconds=1)
        await new_msg.save()
        print(f"  Inserted result for {call_id} ({name}) at {new_msg.created_at}")
    
    print(f"\nDone! Fixed {len(pending)} missing results.")

if __name__ == "__main__":
    import sys
    session_id = sys.argv[1] if len(sys.argv) > 1 else "session_617378dfedf9"
    asyncio.run(fix_session(session_id))
