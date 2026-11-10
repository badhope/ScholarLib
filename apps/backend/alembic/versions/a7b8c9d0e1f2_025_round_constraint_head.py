"""025 — compatibility head after round constraint migration.

This no-op node keeps the migration graph single-headed on deployments that
already stamped 024 manually. It intentionally has no schema operations.
"""

from __future__ import annotations

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
