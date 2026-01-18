from __future__ import annotations

from typing import Optional


GRADE_TO_MIN_SCORE = {
    "A": 91.0,
    "B": 81.0,
    "C": 71.0,
    "D": 61.0,
    # F = 60 o menos. Si el objetivo es "obtener al menos F", es trivial → 0.
    "F": 0.0,
}


def grade_to_objective(grade: str) -> Optional[float]:
    g = (grade or "").strip().upper()
    if not g:
        return None
    return GRADE_TO_MIN_SCORE.get(g)


def objective_to_grade_hint(score: float) -> str:
    """Convierte un score a letra aproximada (para mostrar)."""
    s = float(score)
    if s >= 91:
        return "A"
    if s >= 81:
        return "B"
    if s >= 71:
        return "C"
    if s >= 61:
        return "D"
    return "F"

