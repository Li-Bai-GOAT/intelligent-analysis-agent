# -*- coding: utf-8 -*-
"""
格式化器模块

提供不同模型提供商的格式化器：
- TruncatedDeepSeekFormatter: DeepSeek/OpenAI 兼容格式
- TruncatedAnthropicFormatter: Anthropic/MiniMax 兼容格式

注意：COMPRESSION_PROMPT 已移到 app.config 模块
"""

from .truncated_formatter import TruncatedDeepSeekFormatter
from .anthropic_formatter import TruncatedAnthropicFormatter

__all__ = [
    "TruncatedDeepSeekFormatter",
    "TruncatedAnthropicFormatter",
]
