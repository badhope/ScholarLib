"""037 — R coin exchange / collection settings.

Adds editor-configurable payout/collection fields to coin_policy:
method label, QR image, account/contact, public instructions and a minimum
coin amount. The platform does not move money automatically; the copy tells
users to follow whatever the editor configured.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "037_coin_exchange_settings"
down_revision = "036_coin_scarcity_shop"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coin_policy",
        sa.Column("exchange_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "coin_policy",
        sa.Column("exchange_method", sa.String(length=80), nullable=False, server_default=""),
    )
    op.add_column(
        "coin_policy",
        sa.Column("exchange_qr_url", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "coin_policy",
        sa.Column("exchange_account", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "coin_policy",
        sa.Column("exchange_note", sa.Text(), nullable=True),
    )
    op.add_column(
        "coin_policy",
        sa.Column("exchange_min_coin", sa.Integer(), nullable=False, server_default="100"),
    )


def downgrade() -> None:
    op.drop_column("coin_policy", "exchange_min_coin")
    op.drop_column("coin_policy", "exchange_note")
    op.drop_column("coin_policy", "exchange_account")
    op.drop_column("coin_policy", "exchange_qr_url")
    op.drop_column("coin_policy", "exchange_method")
    op.drop_column("coin_policy", "exchange_enabled")
