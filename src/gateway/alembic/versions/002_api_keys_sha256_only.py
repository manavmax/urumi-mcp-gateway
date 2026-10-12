"""api_keys store only the sha256 digest of the raw key (ADR-025)

The argon2 `hash` column is dropped: keys are 256-bit random, so the slow KDF added
nothing to their security and cost latency on every /mcp call. Existing dev keys keep
their sha256 column and stay valid; they can be revoked and recreated at will.
argon2id remains for user passwords only (auth/rbac.py).

Revision ID: 002_api_keys_sha256_only
Revises: 001_initial
Create Date: 2026-10-12
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "002_api_keys_sha256_only"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("api_keys", "hash")


def downgrade() -> None:
    # the old argon2 hashes cannot be recovered: keys minted after 002 must be
    # re-created (they are shown once and their digest column is unchanged)
    op.add_column("api_keys", sa.Column("hash", sa.Text, nullable=False, server_default="superseded-by-002"))
