"""031: release approval, schedule and rollback metadata

Revision ID: 031_release_approval
Revises: 030_release_manifests
Create Date: 2026-11-12

A ready manifest still needs an explicit editor approval.  The signature
binds manifest id, issue, content hash, approver and approval time, so a
manifest cannot be silently re-pointed at different content.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "031_release_approval"
down_revision = "030_release_manifests"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "release_manifests",
        sa.Column("approved_by", sa.Integer(), nullable=True),
    )
    op.add_column(
        "release_manifests",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "release_manifests",
        sa.Column("approval_note", sa.String(500), nullable=True),
    )
    op.add_column(
        "release_manifests",
        sa.Column("approval_signature", sa.String(64), nullable=True),
    )
    op.add_column(
        "release_manifests",
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "release_manifests",
        sa.Column("rollback_of", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_release_manifests_approved_by_users",
        "release_manifests",
        "users",
        ["approved_by"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_release_manifests_approved_by_users",
        "release_manifests",
        type_="foreignkey",
    )
    op.drop_column("release_manifests", "rollback_of")
    op.drop_column("release_manifests", "scheduled_for")
    op.drop_column("release_manifests", "approval_signature")
    op.drop_column("release_manifests", "approval_note")
    op.drop_column("release_manifests", "approved_at")
    op.drop_column("release_manifests", "approved_by")
