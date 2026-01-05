# app/db/models.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime, JSON, UniqueConstraint, Boolean, func, ForeignKey, Text
from sqlalchemy.sql import expression

Base = declarative_base()

#
# --- Usuarios + progreso (paso 3) ---
#

class AppUser(Base):
    __tablename__ = "app_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    # Nullable para compatibilidad con usuarios demo existentes; en registro real se exige.
    password_hash: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())

class PasswordResetToken(Base):
    __tablename__ = "password_reset_token"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)
    token_hash: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())


class Subject(Base):
    """
    Catálogo de materias. `recommended_config` guarda una plantilla sugerida:
    {"sections":[{"label":"Parciales","porcentaje":0.4,"num_notas":2}, ...]}
    """
    __tablename__ = "subject"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)
    recommended_config: Mapped[Optional[Dict]] = mapped_column(JSON, nullable=True)


class Professor(Base):
    __tablename__ = "professor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True, index=True)


class SubjectProfessor(Base):
    __tablename__ = "subject_professor"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    subject_id: Mapped[int] = mapped_column(ForeignKey("subject.id", ondelete="CASCADE"), nullable=False, index=True)
    professor_id: Mapped[int] = mapped_column(ForeignKey("professor.id", ondelete="CASCADE"), nullable=False, index=True)

    __table_args__ = (
        UniqueConstraint("subject_id", "professor_id", name="uq_subject_professor"),
    )


class UserCourse(Base):
    """
    Una materia "en progreso" por usuario.
    `course_key` coincide con el slug (p.ej. "fisica").
    """
    __tablename__ = "user_course"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("app_user.id", ondelete="CASCADE"), nullable=False, index=True)

    course_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    course_name: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    subject_id: Mapped[Optional[int]] = mapped_column(ForeignKey("subject.id", ondelete="SET NULL"), nullable=True, index=True)
    professor_id: Mapped[Optional[int]] = mapped_column(ForeignKey("professor.id", ondelete="SET NULL"), nullable=True, index=True)
    term: Mapped[str] = mapped_column(String(32), nullable=False, server_default="default")

    objetivo: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("user_id", "course_key", "term", name="uq_user_course_key_term"),
    )


class UserCourseSection(Base):
    __tablename__ = "user_course_section"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_course_id: Mapped[int] = mapped_column(ForeignKey("user_course.id", ondelete="CASCADE"), nullable=False, index=True)

    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..n-1
    label: Mapped[str] = mapped_column(String(128), nullable=False)
    porcentaje: Mapped[float] = mapped_column(Float, nullable=False)  # fracción 0..1
    num_notas: Mapped[int] = mapped_column(Integer, nullable=False)

    __table_args__ = (
        UniqueConstraint("user_course_id", "position", name="uq_user_course_section_pos"),
    )


class UserCourseNote(Base):
    __tablename__ = "user_course_note"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    section_id: Mapped[int] = mapped_column(ForeignKey("user_course_section.id", ondelete="CASCADE"), nullable=False, index=True)

    note_index: Mapped[int] = mapped_column(Integer, nullable=False)  # 0..num_notas-1
    score: Mapped[float] = mapped_column(Float, nullable=False)       # lo que obtuvo (raw)
    base: Mapped[float] = mapped_column(Float, nullable=False)        # base (raw)
    normalized: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("section_id", "note_index", name="uq_user_course_note_idx"),
    )


class EvalDifficultyPrior(Base):
    __tablename__ = "eval_difficulty_prior"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    mu_mean: Mapped[float] = mapped_column(Float, nullable=False)      # 0..100
    sigma_mean: Mapped[float] = mapped_column(Float, nullable=False)   # >0
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (UniqueConstraint("course_key", "eval_label", name="uq_prior_key_label"),)

class IsotonicCalibration(Base):
    __tablename__ = "isotonic_calibration"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    x_knots: Mapped[Dict] = mapped_column(JSON, nullable=False)   # {"x":[...]}
    y_knots: Mapped[Dict] = mapped_column(JSON, nullable=False)   # {"y":[...]}
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (UniqueConstraint("course_key", "eval_label", name="uq_iso_key_label"),)

class ObservedEvalScore(Base):
    __tablename__ = "observed_eval_score"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    created_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())

# (Opcional) si estás registrando pronósticos para calibración
class EvalThresholdPrediction(Base):
    __tablename__ = "eval_threshold_prediction"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_name: Mapped[str] = mapped_column(String(256), nullable=False)  # "Parciales - Nota 2"
    target: Mapped[float] = mapped_column(Float, nullable=False)         # s sugerido (0..100)
    p_pred: Mapped[float] = mapped_column(Float, nullable=False)         # prob mostrada (0..1)
    plan_style: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    issued_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False, server_default=func.now())
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
