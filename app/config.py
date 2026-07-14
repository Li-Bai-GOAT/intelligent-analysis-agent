# -*- coding: utf-8 -*-
"""
统一配置管理

所有配置从 .env 文件读取，使用 pydantic_settings 自动加载
"""

from functools import lru_cache
from typing import Any

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置 - 从 .env 自动读取"""
    
    # 应用
    APP_NAME: str = "RootCauseAnalysis"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8090
    ENVIRONMENT: str = "development"
    DEBUG: bool = False
    CORS_ORIGINS: str = "http://localhost:8090,http://127.0.0.1:8090,http://localhost:5173,http://127.0.0.1:5173"

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug_flag(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"release", "prod", "production"}:
                return False
            if normalized in {"debug", "dev", "development"}:
                return True
        return value

    @property
    def cors_origins(self) -> list[str]:
        return [origin.strip() for origin in self.CORS_ORIGINS.split(",") if origin.strip()]

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.ENVIRONMENT.strip().lower() in {"production", "prod"}:
            if self.JWT_SECRET == "change-this-in-production":
                raise ValueError("JWT_SECRET must be configured outside development")
            if self.DB_AUTO_CREATE_SCHEMA:
                raise ValueError("DB_AUTO_CREATE_SCHEMA must be false in production; use Aerich migrations")
        return self
    
    # PostgreSQL
    DB_ENGINE: str = "postgres"
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = ""
    DB_NAME: str = "rca_agent"
    DB_AUTO_CREATE_SCHEMA: bool = True
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgres://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_BACKEND_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_EXPIRES: int = 3600  # 任务结果过期时间（秒）
    CELERY_TASK_TIME_LIMIT: int = 1800  # 任务硬超时（30分钟）
    CELERY_TASK_SOFT_TIME_LIMIT: int = 1500  # 任务软超时（25分钟，触发异常）
    
    # AI 模型 - 通用配置
    MODEL_PROVIDER: str = "deepseek"  # 模型提供商: deepseek, minimax, openai, anthropic
    MODEL_TEMPERATURE: float = 0.5
    MAX_TOKENS: int = 200000
    TOOL_OUTPUT_MAX_LENGTH: int = 8000
    
    # DeepSeek 配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    DEEPSEEK_MODEL_NAME: str = "deepseek-reasoner"
    
    # MiniMax 配置 (Anthropic API 兼容)
    MINIMAX_API_KEY: str = ""
    MINIMAX_BASE_URL: str = "https://api.minimaxi.com/anthropic"
    MINIMAX_MODEL_NAME: str = "MiniMax-M2.5"
    
    # OpenAI 配置
    OPENAI_API_KEY: str = ""
    OPENAI_BASE_URL: str = "https://api.openai.com/v1"
    OPENAI_MODEL_NAME: str = "gpt-4o"
    
    # Anthropic 配置
    ANTHROPIC_API_KEY: str = ""
    ANTHROPIC_BASE_URL: str = ""  # 留空使用默认
    ANTHROPIC_MODEL_NAME: str = "claude-sonnet-4-20250514"

    # Mimo 配置 (OpenAI 兼容)
    MIMO_API_KEY: str = ""
    MIMO_BASE_URL: str = "https://api.xiaomimimo.com/v1"
    MIMO_MODEL_NAME: str = "mimo-v2.5-pro"
    
    # 上下文压缩
    COMPRESS_THRESHOLD_PERCENT: int = 70  # 超过此百分比触发压缩
    COMPRESS_KEEP_RECENT: int = 10  # 保留最近多少条消息不被压缩
    
    # 压缩模型配置（可选，默认使用主模型配置）
    # 如果希望压缩使用不同的模型（如更便宜的模型），可以单独配置
    COMPRESS_MODEL_PROVIDER: str = ""  # 留空则使用 MODEL_PROVIDER
    COMPRESS_MODEL_NAME: str = ""  # 留空则使用对应 provider 的默认模型
    
    # 沙箱
    SANDBOX_BASE_URL: str = "http://localhost:10001"
    SANDBOX_BEARER_TOKEN: str = ""
    
    # JWT
    JWT_SECRET: str = "change-this-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_HOURS: int = 24
    
    # 文件上传
    UPLOAD_DIR: str = "/data/uploads"
    MAX_UPLOAD_SIZE: int = 100 * 1024 * 1024  # 100MB
    
    # Milvus 向量数据库
    MILVUS_URI: str = "http://localhost:19530"
    MILVUS_TOKEN: str = "root:Milvus"
    MILVUS_DATABASE: str = "rca_agent"
    MILVUS_DIM: int = 1024
    MILVUS_COLLECTION: str = "rca_knowledge_base"
    
    # Embedding 服务
    EMBEDDING_BASE_URL: str = "http://localhost:9997/v1"
    EMBEDDING_MODEL: str = "qwen3-embedding:0.6b"
    EMBEDDING_API_KEY: str = "none"
    EMBEDDING_ENABLED: bool = True
    EMBEDDING_TIMEOUT_SECONDS: float = 120.0
    
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()


settings = get_settings()


# 压缩提示词 - 用于生成对话历史摘要（放在类外部，作为模块常量）
COMPRESSION_PROMPT = '''请分析以下对话历史，提取关键信息并生成结构化摘要。

## 对话历史
{conversation}

## 要求
请用中文生成摘要，包含以下4个部分（每部分100-300字）：

1. **任务概述**: 用户的核心请求和成功标准是什么？
2. **当前状态**: 到目前为止已完成了哪些工作？包括修改的文件、执行的命令、产生的输出等。
3. **重要发现**: 发现了哪些技术约束、做出了哪些决策、遇到了哪些错误、尝试过哪些失败的方法？
4. **下一步计划**: 完成任务还需要哪些具体操作？

直接用 markdown 格式输出，用 ## 作为标题。'''
