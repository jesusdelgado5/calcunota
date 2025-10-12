# migrations — Esquema y Versionado (Alembic)

## Archivos

- `alembic.ini` (raíz)  
  Configuración. `migrations/env.py` lee `.env` y, si existe `DATABASE_URL`, **pisa** `sqlalchemy.url`.

- `env.py`  
  Inyecta `BASE_DIR` al `sys.path`, carga `.env`, imprime la URL activa y expone `target_metadata` desde `app.db.models.Base`.

- `versions/*.py`  
  - `a5a19f63dc77_init_priors_calib_observations.py`  
    Crea `eval_difficulty_prior`, `isotonic_calibration`, `observed_eval_score`.  
  - `e3fe3d12f96e_add_eval_threshold_prediction.py`  
    Agrega `eval_threshold_prediction` y endurece `NOT NULL` en timestamps con `server_default`.

## Comandos típicos

```bash
# Crear/actualizar BD al último esquema
alembic upgrade head

# Migración nueva (editarla a mano si es necesario)
alembic revision -m "mensaje"

# Generar a partir de cambios en modelos (revisar dif!)
alembic revision --autogenerate -m "autosync"

# Volver una versión
alembic downgrade -1
````

**Por qué Alembic**: control de versiones del esquema, despliegues repetibles y rollback seguro.
