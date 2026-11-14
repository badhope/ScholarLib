"""041 — 通用举报队列与 AI 投稿 Token

- ``content_reports``：评论/投稿举报，和论坛举报在后台合并展示。
- ``api_tokens``：个人 API Token，哈希存储、可撤销，供 MCP/脚本投稿。
- ``submissions.source`` / ``client_ref``：区分 web/AI 来源并支持幂等重放。

Revision ID: 041_content_reports_api_tokens
Revises: 040_user_notification_prefs
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "041_content_reports_api_tokens"
down_revision = "040_user_notification_prefs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "submissions",
        sa.Column("source", sa.String(length=20), nullable=False, server_default="web"),
    )
    op.add_column("submissions", sa.Column("client_ref", sa.String(length=100), nullable=True))
    op.create_index(
        "ix_submissions_ai_ref",
        "submissions",
        ["tenant_id", "submitted_by", "client_ref"],
    )

    op.create_table(
        "content_reports",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "reporter_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.String(length=20), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("reason", sa.String(length=200), nullable=False, server_default=""),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_content_reports_tenant_id", "content_reports", ["tenant_id"])
    op.create_index("ix_content_reports_reporter_id", "content_reports", ["reporter_id"])
    op.create_index(
        "ix_content_reports_tenant_status",
        "content_reports",
        ["tenant_id", "status", "created_at"],
    )
    op.create_index(
        "ix_content_reports_target",
        "content_reports",
        ["tenant_id", "target_type", "target_id"],
    )

    op.create_table(
        "api_tokens",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("token_prefix", sa.String(length=16), nullable=False),
        sa.Column(
            "scopes",
            sa.String(length=200),
            nullable=False,
            server_default="submission:write profile:read",
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("request_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_api_tokens_hash"),
    )
    op.create_index("ix_api_tokens_tenant_id", "api_tokens", ["tenant_id"])
    op.create_index("ix_api_tokens_user_id", "api_tokens", ["user_id"])
    op.create_index(
        "ix_api_tokens_tenant_user", "api_tokens", ["tenant_id", "user_id", "created_at"]
    )

    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE content_reports ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE content_reports FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON content_reports
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )
        op.execute("ALTER TABLE api_tokens ENABLE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE api_tokens FORCE ROW LEVEL SECURITY")
        op.execute(
            """
            CREATE POLICY tenant_isolation ON api_tokens
                USING (tenant_id::text = current_setting('app.current_tenant_id', true))
                WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
            """
        )


def downgrade() -> None:
    op.drop_table("api_tokens")
    op.drop_table("content_reports")
    op.drop_index("ix_submissions_ai_ref", table_name="submissions")
    op.drop_column("submissions", "client_ref")
    op.drop_column("submissions", "source")
