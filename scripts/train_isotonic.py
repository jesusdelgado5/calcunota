# scripts/train_isotonic.py
import numpy as np
from collections import defaultdict
from sklearn.isotonic import IsotonicRegression
from app.db import SessionLocal
from app.db.models import EvalThresholdPrediction, IsotonicCalibration

def train_isotonic():
    db = SessionLocal()
    try:
        # 1) junta (p_pred, hit) por (course_key, eval_label)
        rows = db.query(EvalThresholdPrediction)\
                 .filter(EvalThresholdPrediction.resolved == True,
                         EvalThresholdPrediction.hit != None).all()
        by_key = defaultdict(lambda: {"p":[], "y":[]})
        for r in rows:
            by_key[(r.course_key, r.eval_label)]["p"].append(float(r.p_pred))
            by_key[(r.course_key, r.eval_label)]["y"].append(1.0 if r.hit else 0.0)

        # 2) entrena isotónica y guarda nudos (xs, ys)
        for (course_key, eval_label), d in by_key.items():
            p = np.asarray(d["p"], dtype=float)
            y = np.asarray(d["y"], dtype=float)
            if len(p) < 100:   # umbral mínimo razonable
                continue
            iso = IsotonicRegression(out_of_bounds="clip")
            f = iso.fit(p, y)
            # discretiza [0,1] en 21 puntos para guardar nudos
            xs = np.linspace(0, 1, 21)
            ys = f.predict(xs)

            row = db.query(IsotonicCalibration)\
                    .filter(IsotonicCalibration.course_key==course_key,
                            IsotonicCalibration.eval_label==eval_label)\
                    .one_or_none()
            if not row:
                row = IsotonicCalibration(course_key=course_key, eval_label=eval_label,
                                          x_knots={"x": xs.tolist()}, y_knots={"y": ys.tolist()})
                db.add(row)
            else:
                row.x_knots = {"x": xs.tolist()}
                row.y_knots = {"y": ys.tolist()}
        db.commit()
        print("Calibraciones isotónicas entrenadas/actualizadas.")
    finally:
        db.close()

if __name__ == "__main__":
    train_isotonic()
