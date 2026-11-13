"""033 — public profile customization + R coin wallet.

Adds the minimum fields needed for a public, customizable profile and a
spendable community currency.  Coin balance is a hot-path snapshot; the
append-only ledger is ``point_events.identity='coin'`` (same idempotency
constraint as other point rows).

Revision ID: 033_profile_currency
Revises: 032_forum_reactions
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "033_profile_currency"
down_revision = "032_forum_reactions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar_url", sa.String(length=500), nullable=True))
    op.add_column("users", sa.Column("banner_url", sa.String(length=500), nullable=True))
    op.add_column(
        "users",
        sa.Column("accent_color", sa.String(length=7), nullable=False, server_default="#2f5d46"),
    )
    op.add_column("users", sa.Column("contact_email", sa.String(length=255), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "profile_visibility", sa.String(length=16), nullable=False, server_default="public"
        ),
    )
    op.add_column(
        "users",
        sa.Column("coin_balance", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("accent_unlocked", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("users", "accent_unlocked")
    op.drop_column("users", "coin_balance")
    op.drop_column("users", "profile_visibility")
    op.drop_column("users", "contact_email")
    op.drop_column("users", "accent_color")
    op.drop_column("users", "banner_url")
    op.drop_column("users", "avatar_url")
