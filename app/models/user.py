# -*- coding: utf-8 -*-
"""
用户模型
"""

from tortoise import fields
from tortoise.models import Model


class User(Model):
    """用户表"""
    
    id = fields.UUIDField(pk=True)
    username = fields.CharField(max_length=64, unique=True, index=True)
    password_hash = fields.CharField(max_length=256)
    is_admin = fields.BooleanField(default=False)
    created_at = fields.DatetimeField(auto_now_add=True)
    
    class Meta:
        table = "users"
    
    def __str__(self):
        return self.username
