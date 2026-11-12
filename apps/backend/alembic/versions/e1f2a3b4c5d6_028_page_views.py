"""028: first-party anonymous page views

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-11-11
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "f2a3b4c5d6e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "page_views",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("path", sa.String(300), nullable=False),
        sa.Column("referrer", sa.String(500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_page_views_tenant_created", "page_views", ["tenant_id", "created_at"])
    op.create_index("ix_page_views_path", "page_views", ["path"])

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE page_views ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE page_views FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON page_views
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation ON page_views")
        op.execute("ALTER TABLE page_views NO FORCE ROW LEVEL SECURITY")
        op.execute("ALTER TABLE page_views DISABLE ROW LEVEL SECURITY")
    op.drop_table("page_views")
