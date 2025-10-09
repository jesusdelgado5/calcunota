# app/db/models.py
from __future__ import annotations
from datetime import datetime
from typing import Optional, Dict

from sqlalchemy.orm import declarative_base, Mapped, mapped_column
from sqlalchemy import Integer, String, Float, DateTime, JSON, UniqueConstraint, Boolean, func
from sqlalchemy.sql import expression

Base = declarative_base()

class EvalDifficultyPrior(Base):
    __tablename__ = "eval_difficulty_prior"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    mu_mean: Mapped[float] = mapped_column(Float, nullable=False)      # 0..100
    sigma_mean: Mapped[float] = mapped_column(Float, nullable=False)   # >0
    n: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(), server_default=func.now(), onupdate=func.now()
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
        DateTime(), server_default=func.now(), onupdate=func.now()
    )
    __table_args__ = (UniqueConstraint("course_key", "eval_label", name="uq_iso_key_label"),)

class ObservedEvalScore(Base):
    __tablename__ = "observed_eval_score"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    course_key: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    eval_label: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    score: Mapped[float] = mapped_column(Float, nullable=False)  # 0..100
    created_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())

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
    issued_at: Mapped[datetime] = mapped_column(DateTime(), server_default=func.now())
    resolved: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=expression.false())
    hit: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
