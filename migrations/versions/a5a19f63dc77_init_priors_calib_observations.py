"""init priors calib observations

Revision ID: a5a19f63dc77
Revises: 
Create Date: 2025-09-22 03:24:06.943450

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

from sqlalchemy import Table, Column, Integer, String, Float, DateTime, JSON, UniqueConstraint
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = 'a5a19f63dc77'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade():
    op.create_table(
        'eval_difficulty_prior',
        Column('id', Integer, primary_key=True),
        Column('course_key', String(128), index=True, nullable=False),
        Column('eval_label', String(128), index=True, nullable=False),
        Column('mu_mean', Float, nullable=False),
        Column('sigma_mean', Float, nullable=False),
        Column('n', Integer, nullable=False, server_default="0"),
        Column('updated_at', DateTime, server_default=func.now()),
        UniqueConstraint('course_key','eval_label', name='uq_prior_key_label')
    )
    op.create_table(
        'isotonic_calibration',
        Column('id', Integer, primary_key=True),
        Column('course_key', String(128), index=True, nullable=False),
        Column('eval_label', String(128), index=True, nullable=False),
        Column('x_knots', JSON, nullable=False),
        Column('y_knots', JSON, nullable=False),
        Column('updated_at', DateTime, server_default=func.now()),
        UniqueConstraint('course_key','eval_label', name='uq_iso_key_label')
    )
    op.create_table(
        'observed_eval_score',
        Column('id', Integer, primary_key=True),
        Column('course_key', String(128), index=True, nullable=False),
        Column('eval_label', String(128), index=True, nullable=False),
        Column('score', Float, nullable=False),
        Column('created_at', DateTime, server_default=func.now())
    )

def downgrade():
    op.drop_table('observed_eval_score')
    op.drop_table('isotonic_calibration')
    op.drop_table('eval_difficulty_prior')