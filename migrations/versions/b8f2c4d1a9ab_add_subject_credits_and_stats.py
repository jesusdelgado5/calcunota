"""add credits + mu/sigma to subject

Revision ID: b8f2c4d1a9ab
Revises: 0c7a9b3aa7d1
Create Date: 2026-01-14

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b8f2c4d1a9ab"
down_revision: Union[str, Sequence[str], None] = "0c7a9b3aa7d1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Catálogo de materias: metadatos para índice y priors iniciales de materia
    op.add_column("subject", sa.Column("credits", sa.Integer(), nullable=True))
    op.add_column("subject", sa.Column("mu_mean", sa.Float(), nullable=True))
    op.add_column("subject", sa.Column("sigma_mean", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("subject", "sigma_mean")
    op.drop_column("subject", "mu_mean")
    op.drop_column("subject", "credits")

