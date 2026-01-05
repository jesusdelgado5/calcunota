"""add user progress tables

Revision ID: 7b3c2f1a8c21
Revises: e3fe3d12f96e
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = "7b3c2f1a8c21"
down_revision: Union[str, Sequence[str], None] = "e3fe3d12f96e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- app_user ---
    op.create_table(
        "app_user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("username", name="uq_app_user_username"),
    )
    op.create_index(op.f("ix_app_user_username"), "app_user", ["username"], unique=True)

    # --- user_course ---
    op.create_table(
        "user_course",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("course_key", sa.String(length=128), nullable=False),
        sa.Column("course_name", sa.String(length=256), nullable=True),
        sa.Column("term", sa.String(length=32), nullable=False, server_default="default"),
        sa.Column("objetivo", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("user_id", "course_key", "term", name="uq_user_course_key_term"),
    )
    op.create_index(op.f("ix_user_course_user_id"), "user_course", ["user_id"], unique=False)
    op.create_index(op.f("ix_user_course_course_key"), "user_course", ["course_key"], unique=False)

    # --- user_course_section ---
    op.create_table(
        "user_course_section",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_course_id", sa.Integer(), sa.ForeignKey("user_course.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("porcentaje", sa.Float(), nullable=False),
        sa.Column("num_notas", sa.Integer(), nullable=False),
        sa.UniqueConstraint("user_course_id", "position", name="uq_user_course_section_pos"),
    )
    op.create_index(op.f("ix_user_course_section_user_course_id"), "user_course_section", ["user_course_id"], unique=False)

    # --- user_course_note ---
    op.create_table(
        "user_course_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("section_id", sa.Integer(), sa.ForeignKey("user_course_section.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note_index", sa.Integer(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("base", sa.Float(), nullable=False),
        sa.Column("normalized", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.UniqueConstraint("section_id", "note_index", name="uq_user_course_note_idx"),
    )
    op.create_index(op.f("ix_user_course_note_section_id"), "user_course_note", ["section_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_user_course_note_section_id"), table_name="user_course_note")
    op.drop_table("user_course_note")

    op.drop_index(op.f("ix_user_course_section_user_course_id"), table_name="user_course_section")
    op.drop_table("user_course_section")

    op.drop_index(op.f("ix_user_course_course_key"), table_name="user_course")
    op.drop_index(op.f("ix_user_course_user_id"), table_name="user_course")
    op.drop_table("user_course")

    op.drop_index(op.f("ix_app_user_username"), table_name="app_user")
    op.drop_table("app_user")

