"""030: release manifests

Revision ID: 030_release_manifests
Revises: 029_resource_reviewed_at
Create Date: 2026-11-12

Issue-level release gate snapshots.  The payload contains the full check
result and every resource/file hash; a manifest is only publishable while
its content hash still matches the live issue.
"""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "030_release_manifests"
down_revision = "029_resource_reviewed_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "release_manifests",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("volume", sa.String(50), nullable=False),
        sa.Column("issue", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("resource_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_release_manifests_tenant_id", "release_manifests", ["tenant_id"])
    op.create_index(
        "ix_release_manifests_tenant_issue",
        "release_manifests",
        ["tenant_id", "volume", "issue"],
    )
    op.create_index(
        "ix_release_manifests_tenant_status",
        "release_manifests",
        ["tenant_id", "status"],
    )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE release_manifests ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE release_manifests FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON release_manifests
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON release_manifests")
        op.execute("ALTER TABLE release_manifests NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE release_manifests DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_release_manifests_tenant_status", table_name="release_manifests")
    op.drop_index("ix_release_manifests_tenant_issue", table_name="release_manifests")
    op.drop_index("ix_release_manifests_tenant_id", table_name="release_manifests")
    op.drop_table("release_manifests")
