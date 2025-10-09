from app.db import SessionLocal
from app.db.models import EvalThresholdPrediction

def log_plan_predictions(course_key: str, plan_style: str, details: list):
    """
    Guarda cada (sección, meta s, p_pred) del plan mostrado al usuario.
    'details' es la lista que te devuelve el optimizador (p.details).
    """
    db = SessionLocal()
    try:
        for d in details:
            row = EvalThresholdPrediction(
                course_key=course_key,
                eval_label=d["name"].split(" - ")[0],  # "Parciales" a partir de "Parciales - Nota 2"
                eval_name=d["name"],
                target=float(d["target"]),
                p_pred=float(d["p_tail"]),    # usa la prob. que estás mostrando
                plan_style=plan_style,
            )
            db.add(row)
        db.commit()
    finally:
        db.close()

from sqlalchemy import and_

def resolve_predictions_with_new_score(course_key: str, eval_label: str, score: float):
    """
    Si había predicciones pendientes para (course_key, eval_label), las resolvemos
    con la nueva nota real: hit = 1 si score >= target.
    """
    db = SessionLocal()
    try:
        q = db.query(EvalThresholdPrediction).filter(
            and_(
                EvalThresholdPrediction.course_key == course_key,
                EvalThresholdPrediction.eval_label == eval_label,
                EvalThresholdPrediction.resolved == False
            )
        )
        for row in q.all():
            row.hit = bool(score >= row.target)
            row.resolved = True
        db.commit()
    finally:
        db.close()