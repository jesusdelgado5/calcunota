from typing import List
import numpy as np
from app.db import SessionLocal
from app.db.models import IsotonicCalibration
from sqlalchemy.exc import SQLAlchemyError

class IdentityCalibrator:
    def __call__(self, p: float) -> float:
        return float(min(1.0, max(0.0, p)))

class IsotonicFromKnots:
    def __init__(self, xs: List[float], ys: List[float]):
        self.x = np.asarray(xs, dtype=float)
        self.y = np.asarray(ys, dtype=float)
        # asegura monotonía y límites
        order = np.argsort(self.x)
        self.x = self.x[order]
        self.y = np.clip(self.y[order], 0.0, 1.0)
    def __call__(self, p: float) -> float:
        p = float(np.clip(p, 0.0, 1.0))
        # interp lineal por tramos
        i = np.searchsorted(self.x, p)
        if i == 0: return float(self.y[0])
        if i >= len(self.x): return float(self.y[-1])
        x0,x1 = self.x[i-1], self.x[i]
        y0,y1 = self.y[i-1], self.y[i]
        t = 0.0 if x1==x0 else (p-x0)/(x1-x0)
        return float((1-t)*y0 + t*y1)

def get_calibrator(course_key: str, eval_label: str):
    """Carga calibrador isotónico si existe; si no, identidad."""
    db = SessionLocal()
    try:
        row = db.query(IsotonicCalibration)\
            .filter(IsotonicCalibration.course_key==course_key,
                    IsotonicCalibration.eval_label==eval_label)\
            .one_or_none()
        if not row:
            return IdentityCalibrator()
        xs = row.x_knots.get("x", [])
        ys = row.y_knots.get("y", [])
        if not xs or not ys or len(xs)!=len(ys):
            return IdentityCalibrator()
        return IsotonicFromKnots(xs, ys)
    except SQLAlchemyError:
        # Primera corrida sin migraciones / DB inconsistente: no debe tumbar la app.
        return IdentityCalibrator()
    finally:
        db.close()
