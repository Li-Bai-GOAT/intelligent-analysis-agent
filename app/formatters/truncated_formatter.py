# -*- coding: utf-8 -*-
"""
自定义截断格式化器

继承 DeepSeekChatFormatter，实现工具输出截断。
压缩逻辑由 sessions.py 的预压缩处理，摘要注入到系统提示词。
"""

import json
import logging
from typing import Any

from agentscope.formatter import DeepSeekChatFormatter
from agentscope.message import Msg
from agentscope.token import TokenCounterBase

logger = logging.getLogger(__name__)

class TruncatedDeepSeekFormatter(DeepSeekChatFormatter):
    """
    带工具输出裁剪的 DeepSeek 格式化器
    
    功能：截断过长的工具输出
    注意：压缩逻辑由 sessions.py 预压缩处理，摘要注入到系统提示词
    """
    
    def __init__(
        self,
        token_counter: TokenCounterBase | None = None,
        max_tokens: int | None = None,
        tool_output_max_length: int = 8000,
    ) -> None:
        super().__init__(token_counter=token_counter, max_tokens=max_tokens)
        self.tool_output_max_length = tool_output_max_length
    
    async def _format(self, msgs: list[Msg]) -> list[dict[str, Any]]:
        """重写父类 _format，只修改 tool_result 截断逻辑"""
        self.assert_list_of_msgs(msgs)

        messages: list[dict] = []
        for msg in msgs:
            content_blocks: list = []
            reasoning_content_blocks: list = []
            tool_calls = []

            for block in msg.get_content_blocks():
                typ = block.get("type")
                if typ == "text":
                    content_blocks.append({**block})
                elif typ == "thinking":
                    reasoning_content_blocks.append({**block})
                elif typ == "tool_use":
                    tool_calls.append({
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(
                                block.get("input", {}),
                                ensure_ascii=False,
                            ),
                        },
                    })
                elif typ == "tool_result":
                    textual_output, _ = self.convert_tool_result_to_string(
                        block.get("output"),
                    )
                    # 截断过长输出
                    if len(textual_output) > self.tool_output_max_length:
                        head = textual_output[:int(self.tool_output_max_length * 0.4)]
                        tail = textual_output[-int(self.tool_output_max_length * 0.6):]
                        textual_output = f"{head}\n\n[... [过长截断，中间省略 {len(textual_output) - len(head) - len(tail)} 字符] ...]\n\n{tail}"
                    messages.append({
                        "role": "tool",
                        "tool_call_id": block.get("id"),
                        "content": textual_output,
                        "name": block.get("name"),
                    })
                else:
                    logger.warning("Unsupported block type %s, skipped.", typ)

            content_msg = "\n".join(c.get("text", "") for c in content_blocks)
            reasoning_msg = "\n".join(r.get("thinking", "") for r in reasoning_content_blocks)

            msg_deepseek = {"role": msg.role, "content": content_msg or None}
            if reasoning_msg:
                msg_deepseek["reasoning_content"] = reasoning_msg
            if tool_calls:
                msg_deepseek["tool_calls"] = tool_calls
            if msg_deepseek["content"] or msg_deepseek.get("tool_calls"):
                messages.append(msg_deepseek)

        return messages
