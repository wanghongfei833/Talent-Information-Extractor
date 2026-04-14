#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
用户管理系统 - 数据库模型
"""

from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin, LoginManager
from werkzeug.security import generate_password_hash, check_password_hash

# 延迟初始化 db
db = SQLAlchemy()
login_manager = LoginManager()

class User(UserMixin, db.Model):
    """用户模型"""
    __tablename__ = 'users'
    
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(64), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # 用户信息
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_login = db.Column(db.DateTime)
    is_active = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)  # 是否为超级管理员
    
    # 用户等级系统
    level = db.Column(db.Integer, default=1)  # 1-普通会员，2-高级会员，3-VIP，4-超级 VIP，5-管理员
    experience = db.Column(db.Integer, default=0)  # 经验值
    credits = db.Column(db.Integer, default=100)  # 积分/点数
    
    # API 配置（管理员为每个用户设置）
    api_key = db.Column(db.String(256))  # 阿里云 API Key
    base_url = db.Column(db.String(500), default='https://dashscope.aliyuncs.com/compatible-mode/v1')
    model_name = db.Column(db.String(100), default='qwen-vl-max')
    
    def set_password(self, password):
        """设置密码"""
        self.password_hash = generate_password_hash(password)
    
    def check_password(self, password):
        """验证密码"""
        return check_password_hash(self.password_hash, password)
    
    def update_last_login(self):
        """更新最后登录时间"""
        self.last_login = datetime.now()
        db.session.commit()
    
    def check_level_up(self):
        """检查是否可以升级"""
        level_thresholds = {
            1: 0,      # 普通会员
            2: 100,    # 高级会员：100 经验
            3: 500,    # VIP: 500 经验
            4: 2000,   # 超级 VIP: 2000 经验
            5: 10000   # 管理员：10000 经验
        }
        
        next_level = self.level + 1
        
        if next_level in level_thresholds:
            if self.experience >= level_thresholds[next_level]:
                self.level = next_level
                self.credits += 100 * next_level
                return True
        
        return False
    
    def get_level_name(self):
        """获取等级名称"""
        level_names = {
            1: '普通会员',
            2: '高级会员',
            3: 'VIP 会员',
            4: '超级 VIP',
            5: '管理员'
        }
        return level_names.get(self.level, '普通会员')
    
    def is_super_admin(self):
        """检查是否为超级管理员"""
        return self.is_admin and self.level == 5
    
    def __repr__(self):
        return f'<User {self.username}>'
