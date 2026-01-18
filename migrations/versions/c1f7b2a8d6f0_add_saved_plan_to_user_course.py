"""add saved_plan to user_course

Revision ID: c1f7b2a8d6f0
Revises: b8f2c4d1a9ab
Create Date: 2026-01-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c1f7b2a8d6f0"
down_revision: Union[str, Sequence[str], None] = "b8f2c4d1a9ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("user_course", sa.Column("saved_plan", sa.JSON(), nullable=True))
    op.add_column("user_course", sa.Column("saved_plan_updated_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("user_course", "saved_plan_updated_at")
    op.drop_column("user_course", "saved_plan")

