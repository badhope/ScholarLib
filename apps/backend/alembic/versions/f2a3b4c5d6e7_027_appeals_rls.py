"""027: enable tenant RLS on appeals

Revision ID: d0e1f2a3b4c5
Revises: b8c9d0e1f2a4
Create Date: 2026-11-11
"""

from alembic import op

revision = "f2a3b4c5d6e7"
down_revision = "b8c9d0e1f2a4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("ALTER TABLE appeals ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE appeals FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY tenant_isolation ON appeals
            USING (tenant_id::text = current_setting('app.current_tenant_id', true))
            WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON appeals")
    op.execute("ALTER TABLE appeals NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE appeals DISABLE ROW LEVEL SECURITY")
