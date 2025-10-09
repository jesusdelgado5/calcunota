# app/services/observations.py
from app.db import SessionLocal
from app.db.models import ObservedEvalScore

def log_observed_score(course_key: str, eval_label: str, score: float):
    """
    Registra una nota real observada para (curso, etiqueta de sección).
    Llamar esto cada vez que el alumno agrega una 'nota_obtenida' nueva.
    """
    db = SessionLocal()
    try:
        row = ObservedEvalScore(course_key=course_key, eval_label=eval_label, score=float(score))
        db.add(row)
        db.commit()
    finally:
        db.close()
