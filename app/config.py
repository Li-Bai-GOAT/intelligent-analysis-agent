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
    # Schema changes are managed by Aerich. Set this to true only when
    # bootstrapping a disposable development database, never for an existing
    # or production database.
    DB_AUTO_CREATE_SCHEMA: bool = False
    
    @property
    def DATABASE_URL(self) -> str:
        return f"postgres://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
    
    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    
    # Celery
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_BACKEND_URL: str = "redis://localhost:6379/2"
    CELERY_RESULT_EXPIRES: int = 3600  # 任务结果过期时间（秒）
    CELERY_TASK_TIME_LIMIT: int = 1560  # 顶层 deadline 后的进程级硬保险丝
    CELERY_TASK_SOFT_TIME_LIMIT: int = 1530  # 留出 KunCode 终止确认窗口

    # 单一、用户可见的任务 deadline。Celery hard/soft limit 只作为进程级
    # 保险丝，模型、HTTP 与 KunCode 都使用这里生成的同一个绝对时间点。
    TASK_DEADLINE_SECONDS: int = 1500
    KUNCODE_TERMINATION_GRACE_SECONDS: float = 5.0
    KUNCODE_TERMINATION_CONFIRM_SECONDS: float = 10.0
    
    # AI 模型 - 通用配置
    MODEL_PROVIDER: str = "mimo"  # 模型提供商: deepseek, minimax, openai, anthropic, mimo
    MODEL_TEMPERATURE: float = 0.5
    MAX_TOKENS: int = 200000
    TOOL_OUTPUT_MAX_LENGTH: int = 8000
    MODEL_STREAM_MAX_RETRIES: int = 2
    MODEL_STREAM_RETRY_DELAY_SECONDS: float = 0.5
    # Model admission and audit. Empty quota values disable that individual
    # quota; provider/model allowlists remain fail-closed by default.
    MODEL_AUDIT_ENABLED: bool = True
    MODEL_AUDIT_LOG_PATH: str = "logs/model-audit/requests.log"
    MODEL_AUDIT_RETENTION_DAYS: int = 90
    ALLOWED_MODEL_PROVIDERS: str = "mimo"
    ALLOWED_MODEL_NAMES: str = "mimo-v2.6-pro"
    # Optional compatibility override. When empty, KunCode follows the active
    # MODEL_PROVIDER and its corresponding model name automatically.
    KUNCODE_MODEL: str = ""
    ALLOWED_KUNCODE_MODELS: str = ""
    DISABLE_MIMO: bool = False
    MAX_REQUEST_TOKENS: int = 200000
    DAILY_USER_TOKEN_LIMIT: int = 500000
    MODEL_MAX_CONCURRENCY: int = 4

    @property
    def allowed_model_providers(self) -> set[str]:
        configured = {
            item.strip().lower()
            for item in self.ALLOWED_MODEL_PROVIDERS.split(",")
            if item.strip()
        }
        return configured or {self.MODEL_PROVIDER.strip().lower()}

    @property
    def allowed_model_names(self) -> set[str]:
        configured = {
            item.strip()
            for item in self.ALLOWED_MODEL_NAMES.split(",")
            if item.strip()
        }
        return configured or {self.active_model_name}

    @property
    def allowed_kuncode_models(self) -> set[str]:
        configured = {
            item.strip()
            for item in self.ALLOWED_KUNCODE_MODELS.split(",")
            if item.strip()
        }
        return configured or {self.effective_kuncode_model}

    @property
    def active_model_name(self) -> str:
        """Return the model name selected by MODEL_PROVIDER."""
        provider = self.MODEL_PROVIDER.strip().lower()
        model_names = {
            "deepseek": self.DEEPSEEK_MODEL_NAME,
            "minimax": self.MINIMAX_MODEL_NAME,
            "openai": self.OPENAI_MODEL_NAME,
            "anthropic": self.ANTHROPIC_MODEL_NAME,
            "mimo": self.MIMO_MODEL_NAME,
        }
        return model_names.get(provider, "").strip()

    @property
    def active_qualified_model(self) -> str:
        """Return the provider/model form consumed by KunCode."""
        provider = self.MODEL_PROVIDER.strip().lower()
        model_name = self.active_model_name
        if not provider or not model_name:
            return ""
        return model_name if "/" in model_name else f"{provider}/{model_name}"

    @property
    def effective_kuncode_model(self) -> str:
        """Return the one model that the sandbox should use for this process."""
        return self.KUNCODE_MODEL.strip() or self.active_qualified_model
    
    # DeepSeek 配置
    DEEPSEEK_API_KEY: str = ""
    DEEPSEEK_BASE_URL: str = "https://api.deepseek.com"
    # 使用当前 DeepSeek V4 的非思考模式；其 OpenAI 兼容接口支持工具调用。
    DEEPSEEK_MODEL_NAME: str = "deepseek-v4-flash"
    
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
    MIMO_MODEL_NAME: str = "mimo-v2.6-pro"
    
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
    # Persistent sandbox lifecycle settings.  The container manager pool is
    # counted as part of the hard limit; it is not the limit by itself.
    SANDBOX_IDLE_TIMEOUT_SECONDS: int = 7200
    SANDBOX_LEASE_SECONDS: int = 1800
    SANDBOX_CLEANUP_INTERVAL_SECONDS: int = 300
    SANDBOX_MAX_ACTIVE_CONTAINERS: int = 8

    # SSE 心跳间隔。长任务在模型思考/沙箱执行期间可能几十秒没有任何输出，
    # 代理层（nginx 60s、多数网关 90s）会判定连接失联而断开。只要小于最小
    # 代理超时的一半即可；15s 给 90s 网关留了 6 次机会。
    SSE_HEARTBEAT_SECONDS: float = 15.0
    SANDBOX_MAX_RELEASE_ATTEMPTS: int = 3
    SANDBOX_ORPHAN_GRACE_SECONDS: int = 900
    # Default to observation-only for containers that have no database fact.
    # Idle bindings and explicit releases are still released automatically.
    SANDBOX_AUTO_RELEASE_ORPHANS: bool = False
    # The Runtime manager keeps its prewarmed container pool in Redis.  Use a
    # dedicated client for this database so lifecycle checks never issue
    # SELECT against the application's shared Redis connection.
    SANDBOX_MANAGER_REDIS_URL: str = ""
    SANDBOX_MANAGER_REDIS_DB: int = 5
    SANDBOX_MANAGER_POOL_KEY: str = (
        "_runtime_sandbox_container_container_pool:data_analysis"
    )
    SANDBOX_MANAGER_POOL_SIZE: int = 2
    SANDBOX_CONFIG_VERSION: str = "mimo-v2.6"
    # Comma-separated host environment names that MCP configuration is allowed
    # to reference with {{secret:NAME}}.  An empty list fails closed.
    MCP_SECRET_REFERENCE_ALLOWLIST: str = ""

    @property
    def mcp_secret_reference_allowlist(self) -> list[str]:
        return [
            name.strip()
            for name in self.MCP_SECRET_REFERENCE_ALLOWLIST.split(",")
            if name.strip()
        ]
    
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
