"""邮箱验证码登录的码生成、哈希与窗口计算。

独立成模块是为了可单测：auth.py 只做 HTTP 编排，码的生成/哈希/有效期
全部在这里，纯函数可直接断言。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from app.core.config import settings

CODE_LENGTH = 6
CODE_TTL_MINUTES = 10
MAX_VERIFY_ATTEMPTS = 5
# 每邮箱发送节流
SEND_INTERVAL_SECONDS = 60
DAILY_SEND_LIMIT = 10


def generate_code() -> str:
    """6 位数字码。secrets 保证密码学随机（不要用 random）。"""
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def hash_code(email: str, code: str) -> str:
    """SHA-256(email:code:server_secret)。

    绑定 email 防止把 A 邮箱的码哈希搬到 B 邮箱行上重放；绑定服务端
    secret 防止库泄露后用彩虹表反推 6 位码（空间只有 10^6，无 salting
    时秒破）。
    """
    material = f"{email.strip().lower()}:{code.strip()}:{settings.secret_key}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def codes_match(email: str, code: str, expected_hash: str) -> bool:
    """常数时间比较，避免逐位比对的时序侧信道。"""
    return hmac.compare_digest(hash_code(email, code), expected_hash)


__all__ = [
    "CODE_LENGTH",
    "CODE_TTL_MINUTES",
    "DAILY_SEND_LIMIT",
    "MAX_VERIFY_ATTEMPTS",
    "SEND_INTERVAL_SECONDS",
    "codes_match",
    "generate_code",
    "hash_code",
]
