# `/README.md` (raíz del repositorio)


# CalcuNota — Documentación de Arquitectura y Operación

CalcuNota estima tu **nota final** y genera **planes de estudio** con probabilidades realistas de éxito.  
Stack: **Flask (Python 3.12) + Jinja2 + Tailwind (CDN)** y **SQLAlchemy** con **Alembic**.  
Base de datos por defecto: **SQLite** (archivo local). Producción: **MariaDB** o **PostgreSQL**.

> Este repositorio fue iniciado en Windows. Si trabajas en macOS (Apple Silicon/M-series) **no uses la carpeta `.venv` del repo**; crea tu entorno local nuevo (ver más abajo).


## 1) Estructura de carpetas

```markdown

calcunota/
├─ .venv/                ← entorno virtual local (NO usar de otro OS)
├─ app/                  ← aplicación Flask: blueprints, servicios, plantillas
│  ├─ db/                ← engine y modelos SQLAlchemy
│  ├─ services/          ← lógica de dominio (notas, priors, optimización, etc.)
│  ├─ templates/         ← vistas Jinja2 (HTML + Tailwind CDN)
│  ├─ **init**.py        ← factory create_app()
│  ├─ routes.py          ← rutas web (UI)
│  └─ api.py             ← API JSON /api/calc
├─ migrations/           ← Alembic (esquema y versiones)
├─ scripts/              ← utilidades offline (reentrenos)
├─ alembic.ini
├─ requirements.txt
├─ run.py                ← app mínima (legacy); usar wsgi.py
└─ wsgi.py               ← entrypoint recomendado

```


## 2) Flujo funcional (de extremo a extremo)

### 2.1 Flujo básico (happy path)

1. **Home** (`/`)  
   Muestra CTA para “Calcular”.  
   Render: `templates/home.html` por `routes.root`.

2. **Crear materia** (`/calcular`)  
   Form para nombre de la materia.  
   POST redirige a **Configurar**.  
   Render: `templates/calcular.html`.

3. **Configurar secciones** (`/calcular/<nombre>/configurar`)  
   Se agregan secciones con **% sección** y **# notas**.  
   Al guardar, se persiste en `session["materia_actual"]` con:
   ```python
   {
     "nombre": slug, "labels": ["Parciales",...],
     "secciones": [{"porcentaje":0.2,"num_notas":4,"notas_obtenidas":[]}, ...],
     "objetivo": None
   }
   ```

Render: `templates/configurar_materia.html`.

4. **Captura de notas** (`/materia/<nombre>/captura`)
   Por cada sección, se ingresan **pares (obtenida/base)**.
   Cada nueva nota se **normaliza** y se **loggea** en DB para mejorar priors/calibración:

   * `observations.log_observed_score(...)`
   * `predictions.resolve_predictions_with_new_score(...)`
     Render: `templates/captura.html`.

5. **Resumen** (`/materia/<nombre>/resumen`)
   Vista previa general antes del cálculo.
   Render: `templates/resumen.html`.

6. **Cálculo** (`POST /materia/<nombre>/calcular`)
   Usa `services/grades.resumen_desde_secciones`:

   * `nota_actual` (0..100)
   * `porcentaje_restante` (0..1)
   * `nota_necesaria_promedio_restante` (si se dio objetivo)
     Render: `templates/resultado.html`.

7. **Planes** (opcional)

   * **Manual**: `/materia/<nombre>/planes` (permite ajustar μ/σ y grids)
     `services/optimizer_beam` con Beam + MC (Normal).
   * **Automático**: `/materia/<nombre>/planes-auto` (sin hiperparámetros)
     `services/optimizer_beam_auto` (Beta + calibración + cópula).
     En ambos, se muestran combinaciones de metas por sección, su **aporte** y **probabilidades**.

### 2.2 Flujos alternativos

* **API JSON directa**: `POST /api/calc` con:

  ```json
  {
    "secciones": [{"porcentaje":20,"num_notas":4,"notas_obtenidas":[80,90]}, ...],
    "objetivo": 81
  }
  ```

  El endpoint **normaliza** porcentaje 20⇒0.2 y llama a `grades.resumen_desde_secciones`.

* **Edición iterativa de notas**: desde `resumen.html` se puede saltar a `captura` para ajustar, repitiendo cálculo.

* **Optimización automática** con registro de predicciones: al generar planes auto se registran umbrales y `p_pred` en `eval_threshold_prediction` para evaluar “hit” luego.

### 2.3 Excepciones y mensajes esperados

* **Sin evaluaciones pendientes**:
  Devuelve `{"message": "No hay evaluaciones pendientes."}`.

* **Objetivo inalcanzable**:

  * En `resultado.html`: mensaje de “inalcanzable” si el promedio requerido > 100.
  * En planes-auto: `"Objetivo inalcanzable aún con máximos teóricos."`.

* **Sesión inconsistente** (no hay `materia_actual` o slug distinto):
  Redirección a `/calcular` con `flash("No hay materia en progreso.", "error")`.


## 3) Instalación y ejecución (macOS Apple Silicon)

> Recomendado: **Python 3.12.x** nativo ARM y **MariaDB** local (o usar SQLite por defecto).

```bash
# 0) Clonar
git clone <repo-url>
cd calcunota

# 1) Crear entorno local (NO reutilizar .venv del repo)
python3.12 -m venv .venv
source .venv/bin/activate

# 2) Instalar dependencias
pip install --upgrade pip
pip install -r requirements.txt

# 3) Configurar .env (crea archivo en la raíz)
cat > .env << 'EOF'
# SQLite (por defecto): archivo local
DATABASE_URL=sqlite:///calcu.db

# Ejemplo MariaDB (usa uno):
# DATABASE_URL=mysql+pymysql://user:pass@127.0.0.1:3306/calcunota?charset=utf8mb4
# DATABASE_URL=mariadb+mariadbconnector://user:pass@127.0.0.1:3306/calcunota
EOF

# 4) Migraciones
alembic upgrade head

# 5) Ejecutar
python wsgi.py
# → http://127.0.0.1:5000
```

**Notas MariaDB**

* Si usas `mysql+pymysql`, añade `pymysql` al `requirements.txt`.
* Si usas `mariadb+mariadbconnector`, instala `mariadb` (wheel para ARM).
* Alembic usa `DATABASE_URL` del `.env` (ver `migrations/env.py`).

**Windows → macOS**

* La carpeta `.venv/Scripts` y binarios `.exe` son de Windows; **ignóralos**.
* En macOS tus binarios están en `.venv/bin`.


## 4) Mapa de módulos críticos

* `app/services/grades.py`
  Cálculo determinista de nota actual y promedio necesario. Normaliza notas (número o `{score,base}`).

* `app/services/optimizer_beam.py`
  Beam + Monte Carlo (Normal) configurable desde UI.

* `app/services/optimizer_beam_auto.py`
  Optimización “auto”: prior por materia/sección, **Beta** con calibración isotónica por nudos, cópula gaussiana, diversidad, etiquetado Conservador/Balanceado/Ambicioso.

* `app/services/priors.py`, `observations.py`, `calibration.py`, `predictions.py`
  Ciclo de **mejora continua** de probabilidades: guardar observaciones, actualizar priors/calibraciones y evaluar exactitud de predicciones mostradas.


## 5) Endpoints (resumen)

| Ruta                            | Método   | Descripción            | Vista                     |
| ------------------------------- | -------- | ---------------------- | ------------------------- |
| `/`                             | GET      | Home                   | `home.html`               |
| `/dashboard`                    | GET      | Placeholder de usuario | `dashboard.html`          |
| `/ajustes`                      | GET      | Placeholder de ajustes | `ajustes.html`            |
| `/perfil`                       | GET      | Perfil demo            | `perfil.html`             |
| `/calcular`                     | GET/POST | Crear materia          | `calcular.html`           |
| `/calcular/<nombre>/configurar` | GET/POST | Secciones              | `configurar_materia.html` |
| `/materia/<nombre>/captura`     | GET/POST | Notas                  | `captura.html`            |
| `/materia/<nombre>/resumen`     | GET      | Resumen                | `resumen.html`            |
| `/materia/<nombre>/calcular`    | POST     | Resultado              | `resultado.html`          |
| `/materia/<nombre>/planes`      | GET/POST | Planes (manual)        | `planes_beam.html`        |
| `/materia/<nombre>/planes-auto` | GET/POST | Planes (auto)          | `planes_beam_auto.html`   |
| `/api/calc`                     | POST     | API JSON               | JSON                      |


## 6) Entrada/salida de datos (convenciones)

* **Porcentajes**: en UI el usuario ingresa `%`. En backend se guarda **fracción (0..1)**.
* **Notas**:

  * Número: ya está en 0..100.
  * Objeto `{score, base}` → se normaliza a `(score/base)*100`, con límites [0,100].
* **Probabilidades**: se muestran en [0,1] o porcentaje, redondeadas, con mensajes amigables.
* **Objetivo**: si no hay porcentaje restante, `nota_necesaria_promedio_restante = inf`.


## 7) Calidad, extensiones y escalabilidad

* **Priors** por `course_key` y `eval_label` para inicializar μ/σ.
* **Calibración isotónica** por sección para corregir sesgos de probas.
* **Registro de predicciones**: permite medir “hit rate” y recalibrar.
* **Grids adaptativos** (auto) y **supergrid** (95/100 reales) para evitar falsas imposibilidades.
* **Separación por capas** (servicios, rutas, DB) para migrar futuro **Next.js + API Java** si se desea.

