# app/services — Lógica de dominio

Servicios **puros** (sin dependencia de Flask) para reutilizar en otros frontends.

## Módulos

### 1) `grades.py`
- `normalize_nota(n)`  
  - Si `n` es `{score, base}` → `(score/base)*100` (clamp 0..100)  
  - Si `n` es número → se asume 0..100 (clamp)
- `calcular_nota_actual(secciones)`  
  - Suma ponderada por sección: si faltan notas, esas contribuciones valen 0.
- `calcular_porcentaje_restante(secciones)`  
  - Porcentaje aún no evaluado (fracción 0..1).
- `calcular_nota_necesaria(nota_actual, porcentaje_restante, objetivo)`  
  - Promedio mínimo requerido sobre lo que queda (puede ser `inf`).
- `resumen_desde_secciones(secciones, objetivo?)`  
  - Orquestador: devuelve **nota_actual**, **porcentaje_restante** y, si aplica, **nota_necesaria_promedio_restante** con mensajes interpretables.

**Por qué**: se concentra el cálculo determinista de “dónde estoy” y “qué necesito”, reutilizable desde la UI o la API.


### 2) `optimizer_beam.py` (Manual / legado)
- Convierte secciones en **evaluaciones pendientes** (`build_evals_from_secciones`), asigna **μ/σ** (shrink con priors opcionales) y define un **grid** `[min..100]`.
- **Beam Search** con probas de cola Normal (con SciPy si está) y **Monte Carlo** para baseline y verificación.
- La vista `planes_beam.html` permite **editar μ/σ y grid** antes de optimizar.
- Devuelve `plans` con:
  - `targets` por evaluación,
  - `sum_contrib` (aporte total si cumples metas),
  - `prod_prob` (aprox independencia),
  - `mc_prob` (estimación empírica),
  - `details` por evaluación (peso, μ/σ, `P(Y≥s)`).

**Nota**: la UI principal ya no lo expone; se mantiene como utilidad/legado.


### 3) `optimizer_beam_auto.py` (Proyectar materia)
- Estima **μ/σ** por alumno con **shrinkage** hacia priors (`priors.get_eval_prior`).
- Usa **Beta(α,β)** (0..100) con calibración por sección (`calibration.get_calibrator`).
- **Grids adaptativos** por μ/σ (más amplios en finales).
- Si el objetivo parece fuera de grid, usa **supergrid** (95/100 explícitos, poda con 100 teórico).
- Selecciona candidatos por:
  - razón costo/punto,
  - cuantiles de cola,
  - y metas especiales 95/100.
- **Cópula gaussiana** (ρ≈0.35) para muestrear variables Beta correlacionadas → baseline y `mc_prob`.
- Filtro de **diversidad** (distancia L1) + etiquetas: **Conservador**, **Balanceado**, **Ambicioso**.

**Por qué**: quita fricción de configurar hiperparámetros, evitando falsos “no hay plan” y mejorando interpretabilidad.


### 4) `priors.py`
- `get_eval_prior(course_key, eval_label)`  
  Recupera (μ_prior, σ_prior) o defaults.
- `upsert_eval_prior(...)`  
  Actualiza suavemente los priors (EMA) con nuevas observaciones.

**Motivo**: con el tiempo, cada `(materia, sección)` converge a priors realistas.


### 5) `calibration.py`
- `IdentityCalibrator`: identidad.
- `IsotonicFromKnots(xs, ys)`: interpolación por tramos en [0,1].
- `get_calibrator(course_key, eval_label)`  
  Carga nudos de `IsotonicCalibration` si existen; si no, identidad.

**Motivo**: convertir probabilidades “modeladas” en probabilidades “bien calibradas”.


### 6) `observations.py`
- `log_observed_score(course_key, eval_label, score)`  
  Guarda **notas reales** (normalizadas a 0..100) cuando el alumno añade una nota.


### 7) `predictions.py`
- `log_plan_predictions(course_key, plan_style, details)`  
  Guarda **predicciones mostradas** (umbral objetivo y `p_pred`).
- `resolve_predictions_with_new_score(course_key, eval_label, score)`  
  Marca `hit` cuando llegue una **nota real** para esa sección.

**Motivo**: cerrar el ciclo de **accountability** del modelo y poder recalibrar.
