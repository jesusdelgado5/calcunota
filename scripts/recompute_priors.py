# scripts/recompute_priors.py
import statistics as stats
from collections import defaultdict
from app.db import SessionLocal
from app.db.models import ObservedEvalScore, EvalDifficultyPrior

def recompute_priors():
    db = SessionLocal()
    try:
        # 1) carga todas las observaciones
        rows = db.query(ObservedEvalScore).all()
        by_key = defaultdict(list)
        for r in rows:
            by_key[(r.course_key, r.eval_label)].append(float(r.score))

        # 2) calcula (mu, sigma) y guarda/actualiza
        for (course_key, eval_label), scores in by_key.items():
            if len(scores) < 5:
                continue  # mínimo de datos para que sea estable
            mu = stats.fmean(scores)
            sigma = stats.pstdev(scores) or 12.0  # pstdev población; fallback

            row = db.query(EvalDifficultyPrior)\
                .filter(EvalDifficultyPrior.course_key==course_key,
                        EvalDifficultyPrior.eval_label==eval_label)\
                .one_or_none()
            if not row:
                row = EvalDifficultyPrior(course_key=course_key, eval_label=eval_label,
                                          mu_mean=mu, sigma_mean=sigma, n=len(scores))
                db.add(row)
            else:
                row.mu_mean = mu
                row.sigma_mean = sigma
                row.n = len(scores)
        db.commit()
        print("Priors recomputados.")
    finally:
        db.close()

if __name__ == "__main__":
    recompute_priors()
