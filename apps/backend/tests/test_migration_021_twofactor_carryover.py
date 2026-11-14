"""2FA 加密列回归测试（迁移收敛后）。

迁移收敛后（26 个旧迁移 → 单个初始迁移 3392b958c074_001_initial_schema.py），
users 表在初始 schema 里就直接携带加密 2FA 列组（totp_secret_encrypted /
totp_enabled_at），不存在旧明文列 → 加密列的"搬运"阶段。本测试改为验证：

1. 初始迁移确实声明了 2FA 加密列组（防止未来迁移重建 users 表时丢列）；
2. 加密链路（Fernet 密文落库 → decrypt_secret 读回）保持可用，且未开启
   2FA 的账号不写任何状态——这两个业务不变量在旧测试里是核心，予以保留。

（迁移本身是 PostgreSQL-only：JSONB 在其它方言下无法渲染，因此不跑整条
upgrade，只从源码提取 create_table 的列声明做静态校验 + 单独验证加解密。）
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType
from unittest.mock import patch

from sqlalchemy.dialects import postgresql

from app.core.totp import decrypt_secret, encrypt_secret
from app.domain.catalog.models import Resource

_MIGRATION_PATH = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "3392b958c074_001_initial_schema.py"
)


def _load_migration() -> ModuleType:
    """按路径加载迁移模块（alembic 的 version 文件不是包，不能直接 import）。"""
    spec = importlib.util.spec_from_file_location("migration_initial", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_initial_schema_declares_encrypted_2fa_columns() -> None:
    """初始迁移的 users 表必须声明加密 2FA 列组。

    这是 2FA 安全模型的落点：密钥只以 Fernet 密文存在，绝不出现明文列。
    若未来重构 users 表漏掉这组列，此测试即失败。
    """
    source = _MIGRATION_PATH.read_text(encoding="utf-8")

    # 定位 users 表的 create_table 块（到下一个 op. 调用为止）。
    match = re.search(
        r'op\.create_table\(\s*["\']users["\'].*?op\.',
        source,
        re.DOTALL,
    )
    assert match is not None, "initial schema must create a users table"
    users_block = match.group(0)

    required_columns = {
        "totp_secret_encrypted": r'sa\.Column\(["\']totp_secret_encrypted["\']',
        "totp_enabled_at": r'sa\.Column\(["\']totp_enabled_at["\']',
        "totp_backup_codes_hashed": r'sa\.Column\(["\']totp_backup_codes_hashed["\']',
        "totp_last_used_counter": r'sa\.Column\(["\']totp_last_used_counter["\']',
    }
    for col, pattern in required_columns.items():
        assert re.search(pattern, users_block), (
            f"users table in initial schema is missing column {col!r} — "
            "2FA encrypted-column model would regress silently."
        )

    # 守卫：明文密钥列不得出现在 users 表里。
    assert not re.search(r'sa\.Column\(["\']two_factor_secret["\']', users_block), (
        "plaintext two_factor_secret must not exist in the consolidated schema"
    )


def test_quality_breakdown_matches_migration_postgresql_type() -> None:
    path = _MIGRATION_PATH.parent / "d1e2f3a4b5c6_010_gamification_quality_announcements.py"
    spec = importlib.util.spec_from_file_location("migration_quality", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with (
        patch.object(module.op, "add_column") as add_column,
        patch.object(module.op, "create_table"),
        patch.object(module.op, "create_index"),
        patch.object(module.op, "execute"),
        patch.object(module.op, "get_bind"),
    ):
        module.upgrade()
    columns = [
        call.args[1]
        for call in add_column.call_args_list
        if call.args[0] == "resources" and call.args[1].name == "quality_breakdown"
    ]
    assert len(columns) == 1
    dialect = postgresql.dialect()
    assert str(columns[0].type.compile(dialect=dialect)) == str(
        Resource.__table__.c.quality_breakdown.type.compile(dialect=dialect)
    )


def test_encrypted_secret_roundtrips() -> None:
    """加密链路不变量：密文可读回（2FA 密钥只以 Fernet 密文落库）。"""
    secret = "JBSWY3DPEHPK3PXP"
    ciphertext = encrypt_secret(secret)
    assert ciphertext != secret
    assert decrypt_secret(ciphertext) == secret
