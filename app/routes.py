# app/routes.py
from flask import Blueprint, render_template, request, redirect, url_for, session, flash, jsonify
from .services import grades
import re
from datetime import datetime
from .services.observations import log_observed_score
from .services.predictions import log_plan_predictions
from .services.predictions import resolve_predictions_with_new_score
from .services.user_progress import (
    ensure_user,
    load_course_state,
    list_user_courses,
    save_section_notes,
    set_course_objetivo,
    upsert_course_config,
)
from .services.auth import authenticate_user, register_user, change_password, issue_reset_token, reset_password
from app.db import SessionLocal
from app.db.models import Subject, Professor, SubjectProfessor
from .services.goal_grades import grade_to_objective
from .services.sections import SECTION_TYPES, normalize_section_label



web_bp = Blueprint("web", __name__)

def is_auth():
    return bool(session.get("user_id"))

def _current_user_pk():
    """
    Devuelve el id (PK) del usuario en DB si existe.
    Con auth demo, crea el usuario si falta.
    """
    if not is_auth():
        return None
    if session.get("user_pk"):
        return int(session["user_pk"])
    username = str(session.get("user_id"))
    pk = ensure_user(username)
    if pk is not None:
        session["user_pk"] = pk
        session.modified = True
    return pk

def _ensure_session_course(nombre: str) -> bool:
    """
    Si no hay materia en sesión y el usuario está autenticado,
    intenta cargarla desde DB para permitir "retomar" desde dashboard.
    """
    data = session.get("materia_actual")
    if data and data.get("nombre") == nombre:
        return True
    pk = _current_user_pk()
    if not pk:
        return False
    loaded = load_course_state(user_id=pk, course_key=nombre)
    if not loaded:
        return False
    session["materia_actual"] = loaded
    session.modified = True
    return True

@web_bp.get("/")
def root():
    # Opción A: renderizar Home con botón "Calcular"
    return render_template("home.html", active="home", is_auth=is_auth())

# ✅ dashboard para el botón "Home"
@web_bp.get("/dashboard")
def dashboard():
    courses = []
    if is_auth():
        pk = _current_user_pk()
        if pk:
            courses = list_user_courses(user_id=pk)
    return render_template("dashboard.html", active="home", is_auth=is_auth(), courses=courses)

# ✅ ajustes para el botón "Ajustes"
@web_bp.get("/ajustes")
def ajustes():
    return render_template("ajustes.html", active="ajustes", is_auth=is_auth())

# ✅ perfil + acciones (los usa el menú Perfil)
@web_bp.get("/perfil")
def perfil():
    return render_template("perfil.html", active="perfil", is_auth=is_auth())

@web_bp.post("/login")
def login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    pk = authenticate_user(username, password)
    if not pk:
        flash("Usuario o contraseña inválidos.", "error")
        return redirect(url_for("web.perfil"))
    session["user_id"] = username
    session["user_pk"] = pk
    session.modified = True
    flash("Sesión iniciada.", "ok")
    return redirect(url_for("web.dashboard"))

@web_bp.post("/logout")
def logout():
    session.pop("user_id", None)
    session.pop("user_pk", None)
    flash("Sesión cerrada.", "ok")
    return redirect(url_for("web.perfil"))


@web_bp.post("/change-password")
def change_password_route():
    if not is_auth():
        flash("Debes iniciar sesión.", "error")
        return redirect(url_for("web.perfil"))
    pk = _current_user_pk()
    if not pk:
        flash("No se pudo identificar el usuario.", "error")
        return redirect(url_for("web.perfil"))
    ok = change_password(pk, request.form.get("current_password") or "", request.form.get("new_password") or "")
    if ok:
        flash("Contraseña actualizada.", "ok")
    else:
        flash("No se pudo actualizar la contraseña (verifica la actual y que la nueva tenga 6+ caracteres).", "error")
    return redirect(url_for("web.perfil"))


@web_bp.post("/forgot-password")
def forgot_password():
    token = issue_reset_token(request.form.get("username") or "")
    if not token:
        flash("No se pudo generar token (usuario inexistente).", "error")
    else:
        flash(f"Token generado (modo dev): {token}", "ok")
    return redirect(url_for("web.perfil"))


@web_bp.post("/reset-password")
def reset_password_route():
    ok = reset_password(
        request.form.get("username") or "",
        request.form.get("token") or "",
        request.form.get("new_password") or "",
    )
    if ok:
        flash("Contraseña restablecida. Ya puedes iniciar sesión.", "ok")
    else:
        flash("No se pudo restablecer (token inválido/expirado o contraseña corta).", "error")
    return redirect(url_for("web.perfil"))

@web_bp.post("/register")
def register():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    if len(username) < 3:
        flash("El usuario debe tener al menos 3 caracteres.", "error")
        return redirect(url_for("web.perfil"))
    if len(password) < 6:
        flash("La contraseña debe tener al menos 6 caracteres.", "error")
        return redirect(url_for("web.perfil"))
    pk = register_user(username, password)
    if not pk:
        flash("No se pudo registrar (quizás el usuario ya existe).", "error")
        return redirect(url_for("web.perfil"))
    session["user_id"] = username
    session["user_pk"] = pk
    session.modified = True
    flash("Usuario creado e iniciado.", "ok")
    return redirect(url_for("web.dashboard"))

def slugify(name: str):
    s = re.sub(r'\s+', '-', name.strip().lower())
    s = re.sub(r'[^a-z0-9\-]', '', s)
    return s or "materia"


def _model_key_from_meta(course_key: str, meta: dict) -> str:
    """
    "Key" para aprendizaje del modelo (priors/observaciones) que no se fragmente por término/usuario.
    - Si la materia viene del catálogo y tiene `code`: usa subj:<code>
    - Si no: fallback al course_key (mejor que nada)
    """
    subject_id = meta.get("subject_id")
    if subject_id:
        db = SessionLocal()
        try:
            subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
            if subj and subj.code:
                return f"subj:{str(subj.code)}"
        finally:
            db.close()
    return str(course_key)

def _period_label(sem_code: str) -> str:
    sem_code = (sem_code or "").strip().upper()
    if sem_code == "S2":
        return "Segundo semestre"
    if sem_code == "V":
        return "Verano"
    return "Primer semestre"

def _period_code(sem_code: str, year: int) -> str:
    sem_code = (sem_code or "").strip().upper()
    if sem_code not in ("S1", "S2", "V"):
        sem_code = "S1"
    return f"{int(year)}-{sem_code}"

@web_bp.route("/calcular", methods=["GET", "POST"])
def calcular():
    now_year = datetime.now().year
    years = list(range(now_year - 1, now_year + 6))
    default_semestre = "S1"
    default_anio = now_year

    if request.method == "POST":
        sem = (request.form.get("periodo_semestre") or default_semestre).strip().upper()
        try:
            anio = int((request.form.get("periodo_anio") or default_anio))
        except Exception:
            anio = default_anio

        term_code = _period_code(sem, anio)  # ej: 2026-S1
        term_label = f"{_period_label(sem)} {anio}"

        subject_id = (request.form.get("subject_id") or "").strip()
        custom_name = (request.form.get("materia_custom") or "").strip()
        prof_id = (request.form.get("professor_id") or "").strip()

        chosen_name = ""
        chosen_subject_id = None
        chosen_professor_id = None

        if subject_id and subject_id != "custom":
            db = SessionLocal()
            try:
                subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
                if subj:
                    chosen_name = subj.name
                    chosen_subject_id = int(subj.id)
            finally:
                db.close()
        else:
            chosen_name = custom_name

        if not chosen_name:
            flash("Elige una materia o escribe una.", "error")
            return redirect(url_for("web.calcular"))

        if prof_id:
            try:
                chosen_professor_id = int(prof_id)
            except Exception:
                chosen_professor_id = None

        # course_key incorpora term para evitar colisiones en URLs
        base_key = slugify(chosen_name)
        term_key = slugify(term_code)
        course_key = f"{base_key}-{term_key}"

        session["course_meta"] = {
            "course_name": chosen_name,
            "term": term_code,
            "term_label": term_label,
            "subject_id": chosen_subject_id,
            "professor_id": chosen_professor_id,
        }
        session.modified = True

        return redirect(url_for("web.configurar_materia", nombre=course_key))

    # GET: cargar catálogo
    subjects = []
    prof_map = {}
    db = SessionLocal()
    try:
        subjects = db.query(Subject).order_by(Subject.name.asc()).all()
        links = db.query(SubjectProfessor).all()
        # subject_id -> [professor_id,...]
        for l in links:
            prof_map.setdefault(int(l.subject_id), []).append(int(l.professor_id))
        professors = db.query(Professor).order_by(Professor.name.asc()).all()
    finally:
        db.close()

    return render_template(
        "calcular.html",
        active="calcular",
        is_auth=is_auth(),
        subjects=subjects,
        professors=professors,
        prof_map=prof_map,
        years=years,
        default_semestre=default_semestre,
        default_anio=default_anio,
    )

@web_bp.get("/calcular/<nombre>/configurar")
def configurar_materia(nombre):
    # plantilla recomendada según subject seleccionado
    meta = session.get("course_meta") or {}
    recommended = []
    subject_id = meta.get("subject_id")
    if subject_id:
        db = SessionLocal()
        try:
            subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
            if subj and subj.recommended_config and isinstance(subj.recommended_config, dict):
                recommended = subj.recommended_config.get("sections") or []
        finally:
            db.close()
    return render_template(
        "configurar_materia.html",
        active="calcular",
        nombre=nombre,
        is_auth=is_auth(),
        recommended=recommended,
        section_types=SECTION_TYPES,
        term=(meta.get("term") or "default"),
    )

@web_bp.post("/calcular/<nombre>/configurar")
def configurar_materia_post(nombre):
    """
    Construye session['materia_actual'] con:
    - labels: nombres de sección (para UI)
    - secciones: lista de dicts EXACTAMENTE como tu .py:
        {'porcentaje': 0..1, 'num_notas': int, 'notas_obtenidas': []}
    """
    labels = request.form.getlist("sec_tipo[]")             # p.ej. ["Parciales","Semestral",...]
    porcentajes = request.form.getlist("sec_porcentaje[]")  # p.ej. ["20","30","50"] o "0.2"...
    totales = request.form.getlist("sec_num_notas[]")       # p.ej. ["4","1","5"]

    secciones = []
    labels_clean = []
    for lbl, p, t in zip(labels, porcentajes, totales):
        lbl = normalize_section_label(lbl)
        if not lbl:
            continue
        try:
            p_val = float(p)
        except:
            p_val = 0.0
        # Conversión a fracción AQUÍ (si teclearon 20, guardamos 0.2)
        if p_val > 1.0:
            p_val = p_val / 100.0

        try:
            t_val = int(t)
        except:
            t_val = 0

        secciones.append({
            "porcentaje": p_val,         # FRACCIÓN 0..1 (como tu .py)
            "num_notas": t_val,
            "notas_obtenidas": []        # se llenará en captura
        })
        labels_clean.append(lbl)

    if not secciones:
        flash("Agrega al menos una sección válida.", "error")
        return redirect(url_for("web.configurar_materia", nombre=nombre))

    session["materia_actual"] = {
        "nombre": nombre,
        "labels": labels_clean,   # sólo UI
        "secciones": secciones,   # <-- lo que consumen tus funciones
        "objetivo": None
    }
    # Persistir config si hay auth
    if is_auth():
        pk = _current_user_pk()
        if pk:
            meta = session.get("course_meta") or {}
            ok = upsert_course_config(
                user_id=pk,
                course_key=nombre,
                course_name=meta.get("course_name") or nombre,
                subject_id=meta.get("subject_id"),
                professor_id=meta.get("professor_id"),
                labels=labels_clean,
                secciones=secciones,
                term=meta.get("term") or "default",
            )
            if not ok:
                flash("Aviso: no se pudo guardar la materia en la base de datos.", "error")
    return redirect(url_for("web.captura_secciones", nombre=nombre, idx=0))

@web_bp.get("/materia/<nombre>/captura")
def captura_secciones(nombre):
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    idx = max(0, min(int(request.args.get("idx", 0)), len(data["secciones"])-1))
    return render_template(
        "captura.html",
        active="calcular",
        nombre=nombre,
        idx=idx,
        label=data["labels"][idx],
        secciones=data["secciones"],
        labels=data["labels"],
        is_auth=is_auth(),
        open_popup=(request.args.get("autopopup") == "1"),
    )

@web_bp.post("/materia/<nombre>/captura")
def captura_secciones_post(nombre):
    data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    secciones = data["secciones"]
    labels = data["labels"]
    idx = max(0, min(int(request.form.get("idx", 0)), len(secciones)-1))

    # 1) Actualiza el total (aún no persistimos hasta validar)
    try:
        total = int(request.form.get("total", secciones[idx]["num_notas"] or 0))
    except:
        total = secciones[idx]["num_notas"] or 0
    total = max(0, total)
    old_notas = list(secciones[idx].get("notas_obtenidas", []))


    # 2) Lee todas las notas ingresadas en el popup (dentro del form)
    #    Nuevo formato: pares (score/base)
    scores_in = request.form.getlist("notas_score[]")
    bases_in  = request.form.getlist("notas_base[]")
    legacy_in = request.form.getlist("notas[]")

    # Si no vinieron campos de notas, NO sobrescribimos las ya guardadas.
    if not (scores_in or bases_in or legacy_in):
        notas_vals = old_notas
    else:
        notas_vals = []
    if (scores_in or bases_in) and notas_vals is not old_notas:
        # usar el nuevo formato
        for sc, bs in zip(scores_in, bases_in):
            sc = (sc or "").strip()
            bs = (bs or "").strip()
            if sc != "":
                try:
                    scf = float(sc)
                except:
                    scf = 0.0
                try:
                    bsf = float(bs) if bs != "" else 100.0
                except:
                    bsf = 100.0
                if bsf <= 0:
                    bsf = 100.0
                # Validación: no permitir score > base
                if scf > bsf:
                    flash("Error: la nota obtenida no puede ser mayor que la base.", "error")
                    return render_template(
                        "captura.html",
                        active="calcular",
                        nombre=nombre,
                        idx=idx,
                        label=labels[idx],
                        secciones=secciones,
                        labels=labels,
                        is_auth=is_auth(),
                        open_popup=True,
                        draft_total=total,
                        draft_notes=notas_vals + [{"score": scf, "base": bsf}],
                    )
                notas_vals.append({"score": scf, "base": bsf})
    elif legacy_in and notas_vals is not old_notas:
        # fallback: compatibilidad con el viejo formato "notas[]"
        for v in legacy_in:
            v = (v or "").strip()
            if v != "":
                try:
                    scf = float(v)
                except:
                    scf = 0.0
                if scf > 100.0:
                    flash("Error: la nota no puede ser mayor que la base (100).", "error")
                    return render_template(
                        "captura.html",
                        active="calcular",
                        nombre=nombre,
                        idx=idx,
                        label=labels[idx],
                        secciones=secciones,
                        labels=labels,
                        is_auth=is_auth(),
                        open_popup=True,
                        draft_total=total,
                        draft_notes=notas_vals + [{"score": scf, "base": 100.0}],
                    )
                notas_vals.append({"score": scf, "base": 100.0})

    # recorta si excede el total
    if total > 0 and len(notas_vals) > total:
        notas_vals = notas_vals[:total]

    # Ahora sí, persistimos en sesión
    secciones[idx]["num_notas"] = total
    secciones[idx]["notas_obtenidas"] = notas_vals

    # 3) Persistir en sesión
    session["materia_actual"]["secciones"] = secciones
    session.modified = True

    # 3.1) Persistir en BD (progreso del usuario) si hay auth
    if is_auth():
        pk = _current_user_pk()
        if pk:
            save_section_notes(
                user_id=pk,
                course_key=nombre,
                section_position=idx,
                num_notas=secciones[idx]["num_notas"],
                notas_obtenidas=secciones[idx]["notas_obtenidas"],
            )

    # 4) *** registra SOLO las notas NUEVAS como observadas ***
    from .services.grades import normalize_nota  # importa aquí para evitar ciclos
    meta = session.get("course_meta") or {}
    model_key = _model_key_from_meta(nombre, meta)
    old_len = len(old_notas)
    new_len = len(notas_vals)
    if new_len > old_len:
        course_key = nombre
        eval_label = labels[idx]
        for k in range(old_len, new_len):
            try:
                s_val_norm = normalize_nota(notas_vals[k])  # 0..100
                # Observaciones para priors/calibración: agregadas por materia (código), no por término
                log_observed_score(model_key, eval_label, s_val_norm)
                resolve_predictions_with_new_score(course_key, eval_label, s_val_norm)
            except Exception as e:
                print("log_observed_score error:", e)


    # 4) Navegación
    action = request.form.get("action", "siguiente")
    if action == "anterior" and idx > 0:
        return redirect(url_for("web.captura_secciones", nombre=nombre, idx=idx-1))
    elif action == "guardar":
        flash("Notas guardadas.", "ok")
        return redirect(url_for("web.captura_secciones", nombre=nombre, idx=idx))
    elif action == "popup_revisar":
        flash("Notas guardadas.", "ok")
        return redirect(url_for("web.captura_secciones", nombre=nombre, idx=idx))
    elif action == "popup_siguiente" and idx < len(secciones)-1:
        flash("Notas guardadas.", "ok")
        return redirect(url_for("web.captura_secciones", nombre=nombre, idx=idx+1, autopopup=1))
    elif action in ("siguiente", "continuar") and idx < len(secciones)-1:
        flash("Notas guardadas.", "ok")
        return redirect(url_for("web.captura_secciones", nombre=nombre, idx=idx+1))
    else:
        return redirect(url_for("web.resumen_materia", nombre=nombre))


@web_bp.get("/materia/<nombre>/resumen")
def resumen_materia(nombre):
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    secs = data["secciones"]
    labels = data["labels"]
    completo = all(s["num_notas"] >= len(s["notas_obtenidas"]) for s in secs)
    return render_template(
        "resumen.html",
        active="calcular",
        nombre=nombre,
        secciones=secs,
        labels=labels,
        completo=completo,
        is_auth=is_auth()
    )

@web_bp.post("/materia/<nombre>/calcular")
def materia_calcular(nombre):
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    objetivo_val = None
    if request.form.get("objetivo_grade"):
        objetivo_val = grade_to_objective(request.form.get("objetivo_grade") or "")
    else:
        objetivo = request.form.get("objetivo")
        objetivo_val = float(objetivo) if objetivo else None
    if is_auth():
        pk = _current_user_pk()
        if pk:
            set_course_objetivo(user_id=pk, course_key=nombre, objetivo=objetivo_val)

    # Aquí consumimos EXACTAMENTE la misma estructura que tu .py
    resultado = grades.resumen_desde_secciones(data["secciones"], objetivo_val)

    # (Opcional) Aquí disparas tu TRANSACCIÓN externa (DB) con data["secciones"] + resultado
    # if request.form.get("guardar") == "1":
    #     guardar_en_db(data["nombre"], data["labels"], data["secciones"], resultado)

    return render_template(
        "resultado.html",
        active="calcular",
        nombre=nombre,
        resultado=resultado,
        is_auth=is_auth()
    )

# --- Proyección (única opción) ---
from .services.grades import calcular_nota_actual
from .services.optimizer_beam_auto import optimize_auto_backend, evaluate_plan_auto

@web_bp.get("/materia/<nombre>/proyectar")
def materia_proyectar(nombre):
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    nota_actual = calcular_nota_actual(data["secciones"])
    return render_template(
        "planes_beam_auto.html",
        active="calcular",
        nombre=nombre,
        nota_actual=round(nota_actual, 2),
        objetivo=data.get("objetivo") or "",
        result=None,
        is_auth=is_auth(),
    )

@web_bp.post("/materia/<nombre>/proyectar")
def materia_proyectar_post(nombre):
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        flash("No hay materia en progreso.", "error")
        return redirect(url_for("web.calcular"))

    objetivo = grade_to_objective(request.form.get("objetivo_grade") or "")
    if objetivo is None:
        flash("Objetivo inválido.", "error")
        return redirect(url_for("web.materia_proyectar", nombre=nombre))

    session["materia_actual"]["objetivo"] = objetivo
    session.modified = True
    if is_auth():
        pk = _current_user_pk()
        if pk:
            set_course_objetivo(user_id=pk, course_key=nombre, objetivo=float(objetivo))

    secciones = data["secciones"]
    labels = data["labels"]
    nota_actual = calcular_nota_actual(secciones)

    meta = session.get("course_meta") or {}
    model_key = _model_key_from_meta(nombre, meta)
    res = optimize_auto_backend(
        secciones=secciones,
        labels=labels,
        course_key=nombre,          # instancia (por usuario/term) para logging UI
        model_key=model_key,        # key agregado para priors/calibración
        nota_actual=nota_actual,
        objetivo=objetivo
    )
    
    try:
        for p in (res.get("highlighted_plans") or res.get("plans") or [])[:3]:
            style = p.get("style") or ""  # Conservador/Balanceado/Ambicioso si lo devuelves
            log_plan_predictions(course_key=nombre, plan_style=style, details=p["details"])
    except Exception as e:
        print("log_plan_predictions error:", e)
    
    return render_template(
        "planes_beam_auto.html",
        active="calcular",
        nombre=nombre,
        nota_actual=round(nota_actual,2),
        objetivo=objetivo,
        result=res,
        is_auth=is_auth()
    )


# --- Compatibilidad: rutas antiguas → Proyectar Materia ---
@web_bp.get("/materia/<nombre>/planes")
def materia_planes(nombre):
    return redirect(url_for("web.materia_proyectar", nombre=nombre), code=302)


@web_bp.post("/materia/<nombre>/planes")
def materia_planes_post(nombre):
    return redirect(url_for("web.materia_proyectar", nombre=nombre), code=302)


@web_bp.get("/materia/<nombre>/planes-auto")
def materia_planes_auto(nombre):
    return redirect(url_for("web.materia_proyectar", nombre=nombre), code=302)


@web_bp.post("/materia/<nombre>/planes-auto")
def materia_planes_auto_post(nombre):
    return redirect(url_for("web.materia_proyectar", nombre=nombre), code=302)


@web_bp.post("/materia/<nombre>/plan-eval")
def materia_plan_eval(nombre):
    """
    Endpoint JSON para recalcular un plan personalizado (metas editadas).
    Espera JSON: { "targets": {"sec1_nota2": 85, ...}, "mc_samples": 8000 }
    Usa secciones/labels/objetivo desde la sesión (materia_actual).
    """
    if not _ensure_session_course(nombre):
        data = session.get("materia_actual")
    else:
        data = session.get("materia_actual")
    if not data or data.get("nombre") != nombre:
        return jsonify({"ok": False, "error": "No hay materia en progreso."}), 400

    payload = request.get_json(force=True, silent=True) or {}
    targets = payload.get("targets") or {}
    try:
        mc_samples = int(payload.get("mc_samples", 8000))
    except Exception:
        mc_samples = 8000
    mc_samples = max(2000, min(40000, mc_samples))

    secciones = data["secciones"]
    labels = data["labels"]
    nota_actual = calcular_nota_actual(secciones)
    objetivo = float(data.get("objetivo") or 0.0)

    meta = session.get("course_meta") or {}
    model_key = _model_key_from_meta(nombre, meta)

    res = evaluate_plan_auto(
        secciones=secciones,
        labels=labels,
        model_key=model_key,
        nota_actual=float(nota_actual),
        objetivo=float(objetivo),
        targets=targets,
        mc_samples=mc_samples,
        seed=123,
    )
    return jsonify(res)