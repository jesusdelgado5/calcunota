"""
Seed de catálogo + data histórica sintética para el tronco de ingeniería.

Qué hace:
1) Upsert de materias en tabla `subject` (code, name, credits, mu_mean, sigma_mean)
2) Inserta ObservedEvalScore sintéticas por (subj:<code>, tipo_sección)
3) Recalcula priors (EvalDifficultyPrior) desde observaciones

Uso:
  python scripts/seed_engineering_trunk.py --n-per-type 400 --seed 123
"""

from __future__ import annotations

import argparse
import os
import sys
from typing import List

# Asegura que `import app` funcione al ejecutar `python scripts/...`
_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from app.db import SessionLocal
from app.db.models import Subject, ObservedEvalScore
from app.services.sections import SECTION_TYPES
from app.services.trunk_probabilities import TRUNK_SUBJECTS, sample_score


def upsert_subjects() -> None:
    db = SessionLocal()
    try:
        # Si no se han corrido migraciones, la tabla `subject` no existe.
        # Mostramos un error amigable con el comando correcto.
        try:
            _ = db.query(Subject).limit(1).all()
        except Exception as e:
            msg = str(e).lower()
            # SQLite: "no such table: subject"
            # Postgres: 'relation "subject" does not exist'
            if (("no such table" in msg and "subject" in msg) or ("relation" in msg and "does not exist" in msg and "subject" in msg)):
                raise RuntimeError(
                    "No existe la tabla 'subject'. Primero ejecuta migraciones:\n"
                    "  python -m alembic upgrade head\n"
                    "y luego vuelve a correr este seed."
                ) from e
            raise
        for s in TRUNK_SUBJECTS:
            row = db.query(Subject).filter(Subject.code == s.code).one_or_none()
            if not row:
                row = Subject(code=s.code, name=s.name)
                db.add(row)
                db.flush()
            row.name = s.name
            row.credits = int(s.credits)
            row.mu_mean = float(s.mu_mean)
            row.sigma_mean = float(s.sigma_mean)
        db.commit()
    finally:
        db.close()


def seed_observations(*, n_per_type: int, seed: int) -> int:
    """
    Inserta observaciones sintéticas. Devuelve cantidad insertada.
    """
    section_types: List[str] = [t for t in SECTION_TYPES if t]  # incluye Otros
    db = SessionLocal()
    inserted = 0
    try:
        batch: List[ObservedEvalScore] = []
        for subj in TRUNK_SUBJECTS:
            model_key = f"subj:{subj.code}"
            for sec_type in section_types:
                # evita crear muchos "Otros" si no se usa; pero igual sirve como fallback
                for i in range(int(n_per_type)):
                    score = float(sample_score(subj.group, sec_type, seed=seed, i=i))
                    batch.append(ObservedEvalScore(course_key=model_key, eval_label=sec_type, score=score))
                    inserted += 1
                    if len(batch) >= 2500:
                        db.add_all(batch)
                        db.commit()
                        batch = []
        if batch:
            db.add_all(batch)
            db.commit()
        return inserted
    finally:
        db.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-type", type=int, default=400)
    ap.add_argument("--seed", type=int, default=123)
    ap.add_argument("--skip-observations", action="store_true")
    args = ap.parse_args()

    upsert_subjects()
    if not args.skip_observations:
        n = seed_observations(n_per_type=max(0, int(args.n_per_type)), seed=int(args.seed))
        print(f"Inserted ObservedEvalScore: {n}")

    # Recompute priors from observations
    from scripts.recompute_priors import recompute_priors

    recompute_priors()


if __name__ == "__main__":
    main()

