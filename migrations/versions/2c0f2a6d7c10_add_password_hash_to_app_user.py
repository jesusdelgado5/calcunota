"""add password_hash to app_user

Revision ID: 2c0f2a6d7c10
Revises: 7b3c2f1a8c21
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2c0f2a6d7c10"
down_revision: Union[str, Sequence[str], None] = "7b3c2f1a8c21"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("password_hash", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "password_hash")

