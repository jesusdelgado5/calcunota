"""add profile fields to app_user

Revision ID: d9a1c2e4f123
Revises: c1f7b2a8d6f0
Create Date: 2026-01-18

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d9a1c2e4f123"
down_revision: Union[str, Sequence[str], None] = "c1f7b2a8d6f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("app_user", sa.Column("first_name", sa.String(length=128), nullable=True))
    op.add_column("app_user", sa.Column("last_name", sa.String(length=128), nullable=True))
    op.add_column("app_user", sa.Column("email", sa.String(length=256), nullable=True))
    # Para mantener consistencia con otros modelos
    op.add_column("app_user", sa.Column("updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("app_user", "updated_at")
    op.drop_column("app_user", "email")
    op.drop_column("app_user", "last_name")
    op.drop_column("app_user", "first_name")

