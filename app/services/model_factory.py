# -*- coding: utf-8 -*-
"""
模型工厂模块

抽象模型创建逻辑，支持多种模型提供商（DeepSeek、MiniMax 等）的切换。
"""

import re
import logging
from typing import Literal, Optional
from dataclasses import dataclass

from agentscope.model import OpenAIChatModel, AnthropicChatModel
from agentscope.token import TokenCounterBase, OpenAITokenCounter
from agentscope.formatter import FormatterBase

from app.config import settings

logger = logging.getLogger(__name__)


class SimpleTokenCounter(TokenCounterBase):
    """
    简单的 Token 计数器，基于字符估算
    
    支持 Anthropic/MiniMax 的特殊内容类型：tool_use, tool_result, thinking
    
    规则：
    - 1 个中文字符 ≈ 0.7 个 Token
    - 1 个英文字符 ≈ 0.4 个 Token
    """
    
    def __init__(self, chinese_ratio: float = 0.7, english_ratio: float = 0.4):
        self.chinese_ratio = chinese_ratio
        self.english_ratio = english_ratio
        self.chinese_pattern = re.compile(r'[\u4e00-\u9fff\u3400-\u4dbf\u3000-\u303f\uff00-\uffef]')
    
    def _count_text(self, text: str) -> int:
        """估算单个文本的 token 数"""
        if not text:
            return 0
        chinese_chars = len(self.chinese_pattern.findall(text))
        other_chars = len(text) - chinese_chars
        return int(chinese_chars * self.chinese_ratio + other_chars * self.english_ratio)
    
    def _extract_text(self, content) -> str:
        """从各种格式的 content 中提取文本"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            texts = []
            for item in content:
                if isinstance(item, dict):
                    item_type = item.get('type', '')
                    if item_type == 'text':
                        texts.append(item.get('text', ''))
                    elif item_type == 'tool_use':
                        texts.append(str(item.get('input', '')))
                    elif item_type == 'tool_result':
                        texts.append(str(item.get('content', '') or item.get('output', '')))
                    elif item_type == 'thinking':
                        texts.append(item.get('thinking', ''))
                    else:
                        texts.append(str(item))
                elif isinstance(item, str):
                    texts.append(item)
            return ' '.join(texts)
        return str(content) if content else ''
    
    async def count(self, msgs: list, **kwargs) -> int:
        """计算消息列表的 token 总数"""
        total = 0
        for msg in msgs:
            if isinstance(msg, dict):
                total += self._count_text(msg.get('role', ''))
                content = msg.get('content', '')
                total += self._count_text(self._extract_text(content))
            else:
                total += self._count_text(str(msg))
        return total


# ==================== 模型提供商类型 ====================

ModelProvider = Literal["deepseek", "minimax", "openai", "anthropic"]


# ==================== 模型配置数据类 ====================

@dataclass
class ModelConfig:
    """模型配置"""
    provider: ModelProvider
    model_name: str
    api_key: str
    base_url: Optional[str] = None
    max_tokens: int = 200000
    temperature: float = 0.5
    stream: bool = True
    # MiniMax/Anthropic 特有: thinking 配置
    thinking: Optional[dict] = None


# ==================== 模型工厂类 ====================

class ModelFactory:
    """
    模型工厂
    
    根据配置创建对应的模型实例和格式化器。
    支持的模型提供商：
    - deepseek: DeepSeek 系列模型（使用 OpenAI 兼容 API）
    - minimax: MiniMax 系列模型（使用 Anthropic 兼容 API）
    - openai: OpenAI 原生模型
    - anthropic: Anthropic Claude 模型
    """
    
    @staticmethod
    def get_model_config() -> ModelConfig:
        """从 settings 获取当前模型配置"""
        provider = settings.MODEL_PROVIDER.lower()
        
        if provider == "deepseek":
            return ModelConfig(
                provider="deepseek",
                model_name=settings.DEEPSEEK_MODEL_NAME,
                api_key=settings.DEEPSEEK_API_KEY,
                base_url=settings.DEEPSEEK_BASE_URL,
                max_tokens=settings.MAX_TOKENS,
                temperature=settings.MODEL_TEMPERATURE,
                stream=True,
            )
        elif provider == "minimax":
            return ModelConfig(
                provider="minimax",
                model_name=settings.MINIMAX_MODEL_NAME,
                api_key=settings.MINIMAX_API_KEY,
                base_url=settings.MINIMAX_BASE_URL,
                max_tokens=settings.MAX_TOKENS,
                temperature=settings.MODEL_TEMPERATURE,
                stream=True,
                thinking={"type": "enabled", "budget_tokens": 10000},
            )
        elif provider == "openai":
            return ModelConfig(
                provider="openai",
                model_name=settings.OPENAI_MODEL_NAME,
                api_key=settings.OPENAI_API_KEY,
                base_url=settings.OPENAI_BASE_URL if hasattr(settings, 'OPENAI_BASE_URL') else None,
                max_tokens=settings.MAX_TOKENS,
                temperature=settings.MODEL_TEMPERATURE,
                stream=True,
            )
        elif provider == "anthropic":
            return ModelConfig(
                provider="anthropic",
                model_name=settings.ANTHROPIC_MODEL_NAME,
                api_key=settings.ANTHROPIC_API_KEY,
                base_url=settings.ANTHROPIC_BASE_URL if hasattr(settings, 'ANTHROPIC_BASE_URL') else None,
                max_tokens=settings.MAX_TOKENS,
                temperature=settings.MODEL_TEMPERATURE,
                stream=True,
                thinking={"type": "enabled", "budget_tokens": 10000},
            )
        else:
            raise ValueError(f"不支持的模型提供商: {provider}，支持: deepseek, minimax, openai, anthropic")
    
    @staticmethod
    def create_model(config: Optional[ModelConfig] = None):
        """
        根据配置创建模型实例
        
        Args:
            config: 模型配置，为 None 时从 settings 获取
            
        Returns:
            模型实例（OpenAIChatModel 或 AnthropicChatModel）
        """
        if config is None:
            config = ModelFactory.get_model_config()
        
        provider = config.provider
        
        if provider in ("deepseek", "openai"):
            # DeepSeek 和 OpenAI 使用 OpenAI 兼容 API
            client_kwargs = {}
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            
            model = OpenAIChatModel(
                model_name=config.model_name,
                api_key=config.api_key,
                client_kwargs=client_kwargs if client_kwargs else None,
                temperature=config.temperature,
                stream=config.stream,
            )
            logger.info(f"已创建 {provider} 模型: {config.model_name}")
            return model
        
        elif provider in ("minimax", "anthropic"):
            # MiniMax 和 Anthropic 使用 Anthropic 兼容 API
            client_kwargs = {}
            if config.base_url:
                client_kwargs["base_url"] = config.base_url
            
            model = AnthropicChatModel(
                model_name=config.model_name,
                api_key=config.api_key,
                max_tokens=4096,  # Anthropic API 的 max_tokens 是输出限制
                stream=config.stream,
                thinking=config.thinking,
                client_kwargs=client_kwargs if client_kwargs else None,
                generate_kwargs={"temperature": config.temperature},
            )
            logger.info(f"已创建 {provider} 模型: {config.model_name}")
            return model
        
        else:
            raise ValueError(f"不支持的模型提供商: {provider}")
    
    @staticmethod
    def create_formatter(
        config: Optional[ModelConfig] = None,
        token_counter: Optional[TokenCounterBase] = None,
        max_tokens: Optional[int] = None,
        tool_output_max_length: int = 8000,
    ) -> FormatterBase:
        """
        根据配置创建格式化器
        
        Args:
            config: 模型配置，为 None 时从 settings 获取
            token_counter: token 计数器
            max_tokens: 最大 token 数
            tool_output_max_length: 工具输出最大长度
            
        Returns:
            格式化器实例
        """
        if config is None:
            config = ModelFactory.get_model_config()
        
        if max_tokens is None:
            max_tokens = config.max_tokens
        
        provider = config.provider
        
        if provider in ("deepseek", "openai"):
            from app.formatters.truncated_formatter import TruncatedDeepSeekFormatter
            formatter = TruncatedDeepSeekFormatter(
                token_counter=token_counter,
                max_tokens=max_tokens,
                tool_output_max_length=tool_output_max_length,
            )
            logger.debug("已创建 DeepSeek 格式化器")
            return formatter
        
        elif provider in ("minimax", "anthropic"):
            from app.formatters.anthropic_formatter import TruncatedAnthropicFormatter
            formatter = TruncatedAnthropicFormatter(
                token_counter=token_counter,
                max_tokens=max_tokens,
                tool_output_max_length=tool_output_max_length,
            )
            logger.debug("已创建 Anthropic 格式化器")
            return formatter
        
        else:
            raise ValueError(f"不支持的模型提供商: {provider}")
    
    @staticmethod
    def create_token_counter(config: Optional[ModelConfig] = None) -> TokenCounterBase:
        """
        创建 token 计数器
        
        Args:
            config: 模型配置，为 None 时从 settings 获取
            
        Returns:
            token 计数器实例
        """
        if config is None:
            config = ModelFactory.get_model_config()
        
        # Anthropic/MiniMax 使用简单字符计数器（支持 thinking, tool_use 等特殊类型）
        if config.provider in ("anthropic", "minimax"):
            return SimpleTokenCounter()
        
        # DeepSeek/OpenAI 使用 OpenAI token 计数器
        return OpenAITokenCounter(model_name="gpt-4")
    
    @staticmethod
    def create_model_and_formatter(
        tool_output_max_length: int = 8000,
    ) -> tuple:
        """
        一次性创建模型、格式化器和 token 计数器
        
        Args:
            tool_output_max_length: 工具输出最大长度
            
        Returns:
            (model, formatter, token_counter) 元组
        """
        config = ModelFactory.get_model_config()
        
        model = ModelFactory.create_model(config)
        token_counter = ModelFactory.create_token_counter(config)
        formatter = ModelFactory.create_formatter(
            config=config,
            token_counter=token_counter,
            max_tokens=config.max_tokens,
            tool_output_max_length=tool_output_max_length,
        )
        
        return model, formatter, token_counter
