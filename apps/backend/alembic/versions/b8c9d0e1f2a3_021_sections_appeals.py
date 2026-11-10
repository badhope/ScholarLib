"""021: article sections, issue parts, author appeals

Revision ID: b8c9d0e1f2a3
Revises: c1d2e3f4a5b6
Create Date: 2026-11-08
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "c1d2e3f4a5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("resources", sa.Column("article_section", sa.String(40), nullable=True))
    op.add_column("resources", sa.Column("issue_part", sa.String(40), nullable=True))
    op.create_index("ix_resources_article_section", "resources", ["article_section"])
    op.create_index("ix_resources_issue_part", "resources", ["issue_part"])

    op.create_table(
        "appeals",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("submission_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("editor_note", sa.Text(), nullable=True),
        sa.Column("decided_by", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["resource_id"], ["resources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submission_id"], ["submissions.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["decided_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_appeals_tenant_status", "appeals", ["tenant_id", "status"])
    op.create_index("ix_appeals_resource", "appeals", ["resource_id"])


def downgrade() -> None:
    op.drop_table("appeals")
    op.drop_index("ix_resources_issue_part", table_name="resources")
    op.drop_index("ix_resources_article_section", table_name="resources")
    op.drop_column("resources", "issue_part")
    op.drop_column("resources", "article_section")
