"""026 — extend editable user profile fields.

All columns are nullable so existing users keep working unchanged.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "b8c9d0e1f2a4"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


PROFILE_COLUMNS = (
    ("display_name", 100),
    ("real_name", 100),
    ("affiliation", 300),
    ("department", 200),
    ("academic_title", 100),
    ("research_interests", 500),
    ("website", 300),
    ("google_scholar", 300),
    ("location", 100),
)


def upgrade() -> None:
    for name, length in PROFILE_COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    for name, _ in reversed(PROFILE_COLUMNS):
        op.drop_column("users", name)
