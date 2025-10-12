# app/ — Aplicación Flask

Contiene la **web app**: factory de Flask, rutas (UI), API JSON, plantillas y servicios de dominio.

## Archivos clave

- `__init__.py`  
  Define `create_app()` y registra blueprints:
  - `web_bp` (UI en `routes.py`)
  - `api_bp` (API en `api.py`)
  Maneja `SessionLocal.remove()` en `teardown_appcontext`.

- `routes.py`  
  Rutas de interfaz de usuario, manejo de sesión demo y **flujo principal**:
  - Home → Calcular → Configurar → Captura → Resumen → Resultado
  - Planes (manual y automático)
  - En Captura: registra **nuevas** notas como observaciones normalizadas.

- `api.py`  
  Endpoint `POST /api/calc`:
  - Normaliza porcentajes (20⇒0.2)
  - Llama a `services/grades.resumen_desde_secciones`
  - Devuelve JSON `{ok, data|error}`

- `templates/`  
  Vistas HTML (Jinja2) con Tailwind via CDN.  
  Ver `app/templates/README.md` para detalles por página.

- `services/`  
  Lógica de negocio independiente de Flask (pura):  
  cálculo de notas, normalización, optimización de planes, priors, calibración, observaciones, predicciones.  
  Ver `app/services/README.md`.

- `db/`  
  Configuración de engine y **modelos ORM**.  
  Ver `app/db/README.md`.

## Orden de uso en tiempo de ejecución (UI)

1. `create_app()` inicializa Flask y registra blueprints.
2. Usuario navega `/` → `routes.root` → `home.html`.
3. Usuario crea materia → `POST /calcular` → redirige a `configurar_materia`.
4. En `configurar_materia_post` se crea `session["materia_actual"]`.
5. Usuario captura notas por sección → `captura_secciones[_post]`.
   - Aquí, **solo notas nuevas** se loggean en DB como `ObservedEvalScore`.
6. Usuario revisa `resumen` y calcula → `materia_calcular` → `resultado`.
7. Opcional: generar `planes` (manual) u `planes-auto` (automático).
   - En automático, se persisten predicciones (`EvalThresholdPrediction`) para auditoría.

## Motivación (por qué así)

- **Separación de responsabilidades**: UI (routes + templates) vs **servicios** puros.  
- **Trazabilidad**: observaciones y predicciones quedan en DB para **mejora de calibración** con el tiempo.  
- **Compatibilidad**: `api.py` permite integrar un frontend externo (Next.js) sin tocar la lógica.

