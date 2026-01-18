
# app/db — Conexión y Modelos

## Conexión

- `__init__.py` define:
  - `DATABASE_URL` desde entorno (`.env`) o defecto `sqlite:///calcu.db`.
  - `engine = create_engine(...)` con `pool_pre_ping=True`.
  - `SessionLocal = scoped_session(sessionmaker(...))`.

> En producción usa MariaDB/PostgreSQL y ajusta `DATABASE_URL`.

## Modelos (SQLAlchemy ORM)

- `models.py` define `Base = declarative_base()` y tablas:

1) `EvalDifficultyPrior`  
   Priors por *(course_key, eval_label)* para estimar **μ/σ** iniciales.  
   - `mu_mean`, `sigma_mean`, `n`, `updated_at`  
   - `UniqueConstraint("course_key","eval_label")`

2) `IsotonicCalibration`  
   Nudos `x_knots / y_knots` para **calibración isotónica** por sección.  
   - Mejora la calidad de probabilidades (`calibration.get_calibrator`).

3) `ObservedEvalScore`  
   Registro de **notas reales observadas** (0..100 normalizado) para análisis y recalibración.

4) `EvalThresholdPrediction`  
   Registro de predicciones mostradas al usuario (umbral `target`, `p_pred`, `plan_style`), luego marcadas `resolved/hit` cuando llega una nueva nota real en esa sección.

## Orden de escritura/lectura

- Al **capturar notas**: `ObservedEvalScore` (nuevo registro por nota).  
- Al **mostrar Proyectar materia**: `EvalThresholdPrediction` (una fila por meta sección).  
- Al **recibir nueva nota**: se resuelven predicciones pendientes (`hit = score >= target`).

## Drivers y URLs

- **SQLite**: `sqlite:///calcu.db`  
- **MariaDB (PyMySQL)**: `mysql+pymysql://user:pass@host:3306/db`  
- **MariaDB (Connector)**: `mariadb+mariadbconnector://user:pass@host:3306/db`  
- **PostgreSQL**: `postgresql+psycopg2://user:pass@host:5432/db`

> Ajusta `requirements.txt` según el driver elegido.
