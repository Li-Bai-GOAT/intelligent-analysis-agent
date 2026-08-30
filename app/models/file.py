# -*- coding: utf-8 -*-
"""
用户文件模型
"""

from tortoise import fields
from tortoise.models import Model


class UserFile(Model):
    """用户上传的文件"""
    
    id = fields.UUIDField(pk=True)
    user_id = fields.CharField(max_length=100, index=True)
    
    # 文件信息
    filename = fields.CharField(max_length=255)
    original_name = fields.CharField(max_length=255)
    content_type = fields.CharField(max_length=100, null=True)
    size = fields.BigIntField(default=0)
    
    # 本地存储路径
    local_path = fields.CharField(max_length=512)
    
    # 关联的会话（可选）
    session_id = fields.CharField(max_length=100, null=True, index=True)
    
    created_at = fields.DatetimeField(auto_now_add=True)
    
    class Meta:
        table = "user_files"
        ordering = ["-created_at"]


class SandboxBinding(Model):
    """会话与沙箱的绑定关系"""
    
    id = fields.UUIDField(pk=True)
    user_id = fields.CharField(max_length=100, index=True)
    session_id = fields.CharField(max_length=100, index=True, unique=True)
    
    # 沙箱信息
    sandbox_id = fields.CharField(max_length=100)
    sandbox_type = fields.CharField(max_length=50, default="data_analysis")
    
    # 挂载路径（沙箱内的工作目录）
    workspace_path = fields.CharField(max_length=512, default="/workspace")
    
    # 沙箱的本地挂载目录（用于沙箱重建时迁移文件）
    mount_dir = fields.CharField(max_length=512, null=True)
    
    # 兼容旧客户端的状态位。它始终与 status 保持一致：
    # ACTIVE / IDLE / RELEASING 为 True，其余状态为 False。
    is_active = fields.BooleanField(default=True)

    # 持久化生命周期事实。不能再只依赖进程内的空闲时间字典，因为
    # 服务重启和多 worker 时该字典会发生漂移。
    status = fields.CharField(max_length=16, default="ACTIVE", index=True)
    last_activity_at = fields.DatetimeField(null=True)
    lease_expires_at = fields.DatetimeField(null=True)
    released_at = fields.DatetimeField(null=True)
    release_attempts = fields.IntField(default=0)
    # 只保存经过脱敏和长度限制的运行时错误；绝不写入环境变量或密钥。
    last_error = fields.TextField(null=True)
    runtime_seen_at = fields.DatetimeField(null=True)
    config_version = fields.CharField(max_length=100, default="v1")
    
    # 已同步的文件 ID 列表（JSON）
    synced_file_ids = fields.JSONField(default=list)
    
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)
    
    class Meta:
        table = "sandbox_bindings"
