# -*- coding: utf-8 -*-
"""
Anthropic/MiniMax 格式化器

继承 AnthropicChatFormatter，实现工具输出截断。
用于 MiniMax（Anthropic API 兼容）和原生 Anthropic Claude 模型。
"""

import logging
from typing import Any

from agentscope.formatter import AnthropicChatFormatter
from agentscope.message import Msg
from agentscope.token import TokenCounterBase

logger = logging.getLogger(__name__)


class TruncatedAnthropicFormatter(AnthropicChatFormatter):
    """
    带工具输出裁剪的 Anthropic 格式化器
    
    功能：
    - 截断过长的工具输出
    - 保留 thinking block 用于推理模型
    
    适用于：
    - MiniMax（Anthropic API 兼容）
    - Anthropic Claude 原生
    """
    
    def __init__(
        self,
        token_counter: TokenCounterBase | None = None,
        max_tokens: int | None = None,
        tool_output_max_length: int = 8000,
    ) -> None:
        super().__init__(token_counter=token_counter, max_tokens=max_tokens)
        self.tool_output_max_length = tool_output_max_length
    
    def _truncate_text(self, text: str) -> str:
        """截断过长的文本"""
        if len(text) <= self.tool_output_max_length:
            return text
        
        head = text[:int(self.tool_output_max_length * 0.4)]
        tail = text[-int(self.tool_output_max_length * 0.6):]
        omitted = len(text) - len(head) - len(tail)
        return f"{head}\n\n[... [过长截断，中间省略 {omitted} 字符] ...]\n\n{tail}"
    
    async def _format(
        self,
        msgs: list[Msg],
    ) -> list[dict[str, Any]]:
        """
        重写父类 _format，添加工具输出截断逻辑
        
        Anthropic API 格式特点：
        - system 消息单独传递，不在 messages 列表中
        - thinking block 保留用于推理模型
        - tool_result 作为 user 消息传递
        """
        self.assert_list_of_msgs(msgs)

        messages: list[dict] = []
        for index, msg in enumerate(msgs):
            content_blocks = []

            for block in msg.get_content_blocks():
                typ = block.get("type")
                
                if typ == "thinking":
                    # 保留 thinking block（含 signature）
                    thinking_block = {"type": "thinking", "thinking": block.get("thinking", "")}
                    if "signature" in block:
                        thinking_block["signature"] = block["signature"]
                    content_blocks.append(thinking_block)
                
                elif typ == "text":
                    content_blocks.append({**block})
                
                elif typ == "image":
                    content_blocks.append({**block})
                
                elif typ == "tool_use":
                    content_blocks.append({
                        "id": block.get("id"),
                        "type": "tool_use",
                        "name": block.get("name"),
                        "input": block.get("input", {}),
                    })

                elif typ == "tool_result":
                    # 处理工具结果，需要截断过长输出
                    output = block.get("output")
                    
                    if output is None:
                        content_value = [{"type": "text", "text": ""}]
                    elif isinstance(output, list):
                        # 输出是列表，逐个处理
                        processed_output = []
                        for item in output:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text = item.get("text", "")
                                truncated = self._truncate_text(str(text))
                                processed_output.append({"type": "text", "text": truncated})
                            else:
                                processed_output.append(item)
                        content_value = processed_output
                    else:
                        # 输出是字符串或其他类型
                        truncated = self._truncate_text(str(output))
                        content_value = [{"type": "text", "text": truncated}]
                    
                    messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": block.get("id"),
                            "content": content_value,
                        }],
                    })
                
                else:
                    logger.warning("Unsupported block type %s in the message, skipped.", typ)

            # Claude 只允许第一条消息是 system
            if msg.role == "system" and index != 0:
                role = "user"
            else:
                role = msg.role

            msg_anthropic = {
                "role": role,
                "content": content_blocks or None,
            }

            # 当 content 和 tool_calls 都为 None 时跳过
            if msg_anthropic["content"] or msg_anthropic.get("tool_calls"):
                messages.append(msg_anthropic)

        return messages
