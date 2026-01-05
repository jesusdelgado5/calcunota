"""add subjects/professors + password reset + link to user_course

Revision ID: 0c7a9b3aa7d1
Revises: 2c0f2a6d7c10
Create Date: 2026-01-05

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import func


# revision identifiers, used by Alembic.
revision: str = "0c7a9b3aa7d1"
down_revision: Union[str, Sequence[str], None] = "2c0f2a6d7c10"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- subject ---
    op.create_table(
        "subject",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("recommended_config", sa.JSON(), nullable=True),
        sa.UniqueConstraint("code", name="uq_subject_code"),
        sa.UniqueConstraint("name", name="uq_subject_name"),
    )
    op.create_index(op.f("ix_subject_code"), "subject", ["code"], unique=True)
    op.create_index(op.f("ix_subject_name"), "subject", ["name"], unique=True)

    # --- professor ---
    op.create_table(
        "professor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.UniqueConstraint("name", name="uq_professor_name"),
    )
    op.create_index(op.f("ix_professor_name"), "professor", ["name"], unique=True)

    # --- subject_professor ---
    op.create_table(
        "subject_professor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subject.id", ondelete="CASCADE"), nullable=False),
        sa.Column("professor_id", sa.Integer(), sa.ForeignKey("professor.id", ondelete="CASCADE"), nullable=False),
        sa.UniqueConstraint("subject_id", "professor_id", name="uq_subject_professor"),
    )
    op.create_index(op.f("ix_subject_professor_subject_id"), "subject_professor", ["subject_id"], unique=False)
    op.create_index(op.f("ix_subject_professor_professor_id"), "subject_professor", ["professor_id"], unique=False)

    # --- password reset token ---
    op.create_table(
        "password_reset_token",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(length=255), nullable=False),
        sa.Column("issued_at", sa.DateTime(), nullable=False, server_default=func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
    )
    op.create_index(op.f("ix_password_reset_token_user_id"), "password_reset_token", ["user_id"], unique=False)
    op.create_index(op.f("ix_password_reset_token_token_hash"), "password_reset_token", ["token_hash"], unique=False)

    # --- link user_course to subject/professor ---
    op.add_column("user_course", sa.Column("subject_id", sa.Integer(), nullable=True))
    op.add_column("user_course", sa.Column("professor_id", sa.Integer(), nullable=True))
    op.create_index(op.f("ix_user_course_subject_id"), "user_course", ["subject_id"], unique=False)
    op.create_index(op.f("ix_user_course_professor_id"), "user_course", ["professor_id"], unique=False)
    # SQLite no soporta ALTER TABLE para agregar constraints; evitamos romper el setup por defecto.
    bind = op.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "sqlite":
        op.create_foreign_key("fk_user_course_subject_id", "user_course", "subject", ["subject_id"], ["id"], ondelete="SET NULL")
        op.create_foreign_key("fk_user_course_professor_id", "user_course", "professor", ["professor_id"], ["id"], ondelete="SET NULL")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect != "sqlite":
        op.drop_constraint("fk_user_course_professor_id", "user_course", type_="foreignkey")
        op.drop_constraint("fk_user_course_subject_id", "user_course", type_="foreignkey")
    op.drop_index(op.f("ix_user_course_professor_id"), table_name="user_course")
    op.drop_index(op.f("ix_user_course_subject_id"), table_name="user_course")
    op.drop_column("user_course", "professor_id")
    op.drop_column("user_course", "subject_id")

    op.drop_index(op.f("ix_password_reset_token_token_hash"), table_name="password_reset_token")
    op.drop_index(op.f("ix_password_reset_token_user_id"), table_name="password_reset_token")
    op.drop_table("password_reset_token")

    op.drop_index(op.f("ix_subject_professor_professor_id"), table_name="subject_professor")
    op.drop_index(op.f("ix_subject_professor_subject_id"), table_name="subject_professor")
    op.drop_table("subject_professor")

    op.drop_index(op.f("ix_professor_name"), table_name="professor")
    op.drop_table("professor")

    op.drop_index(op.f("ix_subject_name"), table_name="subject")
    op.drop_index(op.f("ix_subject_code"), table_name="subject")
    op.drop_table("subject")

