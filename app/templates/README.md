
# app/templates — Vistas Jinja2 (Tailwind CDN)

Plantillas orientadas a un **flujo guiado** y a resultados legibles.

## Base y navegación
- `base.html`  
  Layout con Topbar (Home/Calcular/Ajustes, Perfil demo), mensajes `flash`, y configuración Tailwind (CDN).  
  Las vistas extienden este layout.

## Páginas de flujo principal
1. `home.html`  
   Landing con CTA “Comenzar”.

2. `calcular.html`  
   Form para **nombre de la materia** → redirige a **configurar**.

3. `configurar_materia.html`  
   - Añadir secciones: **Nombre**, **Porcentaje %**, **# de notas**.  
   - Suma de porcentajes en vivo; el botón “Continuar” **solo se habilita si total = 100%**.  
   - Guarda `session["materia_actual"]`.

4. `captura.html`  
   - Para la sección actual: **total de elementos** y **modal de notas (score/base)**.  
   - Previsualiza notas guardadas y **progreso** entre secciones.  
   - `Anterior/Siguiente/Terminar` controlan la navegación.  
   - Los pares `(score, base)` se envían como arreglos y se **normalizan** en backend.

5. `resumen.html`  
   - Tabla consolidada con etiquetas, % por sección, total, realizados y notas registradas.  
   - Si la configuración está completa, habilita **Calcular**.

6. `resultado.html`  
   - Muestra: **Nota actual**, **Porcentaje restante**, **Promedio necesario (restante)**.  
   - Mensaje contextual: alcanzado, inalcanzable o guía.  
   - Enlaces a **Planes** (manual y auto) y JSON crudo.

## Planes
- `planes_beam.html` (manual)  
  Muestra y permite **editar** μ/σ y grids por evaluación antes de optimizar.  
  Resultados con **Prob. MC**, **aportes** y tabla de metas por evaluación.

- `planes_beam_auto.html` (automático)  
  Solo pide el **objetivo**.  
  Muestra baseline, **top planes** con etiquetas y detalles (`P(Y≥s)` por sección).

## Otras
- `dashboard.html`, `ajustes.html`, `perfil.html`  
  Placeholders de navegación/estado de usuario demo.

