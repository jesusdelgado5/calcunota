from typing import Optional, Tuple
from app.db import SessionLocal
from app.db.models import EvalDifficultyPrior

DEFAULT_MU = 70.0
DEFAULT_SIGMA = 12.0

def get_eval_prior(course_key: str, eval_label: str) -> Tuple[float, float]:
    """Devuelve (mu_prior, sigma_prior). Fallback a defaults si no hay fila."""
    db = SessionLocal()
    try:
        row = db.query(EvalDifficultyPrior)\
                .filter(EvalDifficultyPrior.course_key==course_key,
                        EvalDifficultyPrior.eval_label==eval_label)\
                .one_or_none()
        if row:
            return float(row.mu_mean), float(row.sigma_mean)
        return DEFAULT_MU, DEFAULT_SIGMA
    finally:
        db.close()

def upsert_eval_prior(course_key: str, eval_label: str, mu: float, sigma: float):
    """EMA simple para ir actualizando priors con nuevas observaciones agregadas."""
    db = SessionLocal()
    try:
        row = db.query(EvalDifficultyPrior)\
                .filter(EvalDifficultyPrior.course_key==course_key,
                        EvalDifficultyPrior.eval_label==eval_label)\
                .one_or_none()
        if not row:
            row = EvalDifficultyPrior(course_key=course_key, eval_label=eval_label,
                                      mu_mean=mu, sigma_mean=sigma, n=1)
            db.add(row)
        else:
            n = max(1, row.n)
            alpha = 1.0 / min(20, n + 1)     # amortigua a medida que crece n
            row.mu_mean = (1-alpha)*row.mu_mean + alpha*mu
            row.sigma_mean = (1-alpha)*row.sigma_mean + alpha*sigma
            row.n = n + 1
        db.commit()
    finally:
        db.close()
