from __future__ import annotations

from datetime import datetime
import re

from flask import Blueprint, request, jsonify, session

from app.db import SessionLocal
from app.db.models import Subject, Professor, SubjectProfessor
from app.services.sections import SECTION_TYPES, normalize_section_label
from app.services.user_progress import upsert_course_config, set_course_objetivo
from app.services.grades import resumen_desde_secciones, calcular_nota_actual
from app.services.goal_grades import grade_to_objective
from app.services.optimizer_beam_auto import optimize_auto_backend
from app.services.observations import log_observed_score
from app.services.predictions import resolve_predictions_with_new_score
from app.services.grades import normalize_nota

api_bp = Blueprint("api", __name__)


def _slugify(name: str) -> str:
    s = re.sub(r"\s+", "-", (name or "").strip().lower())
    s = re.sub(r"[^a-z0-9\-]", "", s)
    return s or "materia"


def _period_code(sem_code: str, year: int) -> str:
    sem_code = (sem_code or "").strip().upper()
    if sem_code not in ("S1", "S2", "V"):
        sem_code = "S1"
    return f"{int(year)}-{sem_code}"


def _default_sections_for_subject(subject_name: str) -> list[dict]:
    """
    Distribución predeterminada (porcentaje en fracción 0..1) para reducir clicks.
    """
    # Default solicitado por UX: mínimo trabajo, distribución estable para todas las materias.
    # Nota: porcentaje aquí es fracción (0..1), luego se normaliza por si cambia en el futuro.
    base = [
        {"label": "Parciales", "porcentaje": 0.35, "num_notas": 4},
        {"label": "Tareas", "porcentaje": 0.25, "num_notas": 8},
        {"label": "Asistencia", "porcentaje": 0.05, "num_notas": 1},
        {"label": "Semestral", "porcentaje": 0.35, "num_notas": 1},
    ]
    s = sum(float(x["porcentaje"]) for x in base) or 1.0
    for x in base:
        x["label"] = normalize_section_label(x["label"])
        x["porcentaje"] = float(x["porcentaje"]) / s
        x["num_notas"] = int(x["num_notas"])
    return base


@api_bp.post("/wizard/start")
def wizard_start():
    payload = request.get_json(force=True, silent=True) or {}
    sem = (payload.get("periodo_semestre") or "S1").strip().upper()
    try:
        anio = int(payload.get("periodo_anio") or datetime.now().year)
    except Exception:
        anio = datetime.now().year

    subject_id = str(payload.get("subject_id") or "").strip()
    professor_id = str(payload.get("professor_id") or "").strip()
    if not subject_id:
        return jsonify({"ok": False, "error": "Selecciona una materia."}), 400

    db = SessionLocal()
    try:
        subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
        if not subj:
            return jsonify({"ok": False, "error": "Materia inválida."}), 400

        chosen_professor_id = None
        if professor_id:
            try:
                pid = int(professor_id)
            except Exception:
                pid = None
            if pid:
                prof = db.query(Professor).filter(Professor.id == pid).one_or_none()
                if prof:
                    link_ok = (
                        db.query(SubjectProfessor)
                        .filter(SubjectProfessor.subject_id == int(subj.id), SubjectProfessor.professor_id == int(pid))
                        .count()
                    )
                    if link_ok > 0:
                        chosen_professor_id = int(pid)

        term_code = _period_code(sem, anio)
        course_key = f"{_slugify(subj.name)}-{_slugify(term_code)}"

        session["course_meta"] = {
            "course_name": str(subj.name),
            "term": term_code,
            "term_label": term_code,
            "subject_id": int(subj.id),
            "professor_id": chosen_professor_id,
        }
        session.modified = True

        rec = None
        if subj.recommended_config and isinstance(subj.recommended_config, dict):
            rec = subj.recommended_config.get("sections") or None
        if not rec:
            rec = _default_sections_for_subject(subj.name)

        out_sections = []
        for s in rec:
            try:
                lbl = normalize_section_label(s.get("label") or s.get("tipo") or "")
                pct = float(s.get("porcentaje", 0.0))
                if pct <= 1.0:
                    pct = pct * 100.0
                n = int(s.get("num_notas", 0))
            except Exception:
                continue
            out_sections.append({"label": lbl, "porcentaje": round(pct, 1), "num_notas": n})

        return jsonify(
            {
                "ok": True,
                "course_key": course_key,
                "section_types": SECTION_TYPES,
                "recommended": out_sections,
            }
        )
    finally:
        db.close()


@api_bp.post("/wizard/config")
def wizard_config():
    payload = request.get_json(force=True, silent=True) or {}
    course_key = str(payload.get("course_key") or "").strip()
    labels = payload.get("labels") or []
    secciones = payload.get("secciones") or []
    if not course_key:
        return jsonify({"ok": False, "error": "Falta course_key."}), 400
    if not labels or not secciones or len(labels) != len(secciones):
        return jsonify({"ok": False, "error": "Secciones inválidas."}), 400

    try:
        total = sum(float(s.get("porcentaje", 0.0)) for s in secciones)
    except Exception:
        total = 0.0
    if abs(total - 100.0) > 0.2:
        return jsonify({"ok": False, "error": "La suma de porcentajes debe ser 100%."}), 400

    labels_clean = [normalize_section_label(x) for x in labels]
    secs_clean = []
    for s in secciones:
        try:
            pct = float(s.get("porcentaje", 0.0))
            n = int(s.get("num_notas", 0))
        except Exception:
            pct, n = 0.0, 0
        secs_clean.append({"porcentaje": max(0.0, pct) / 100.0, "num_notas": max(0, n), "notas_obtenidas": []})

    meta = session.get("course_meta") or {}
    session["materia_actual"] = {
        "nombre": course_key,
        "labels": labels_clean,
        "secciones": secs_clean,
        "objetivo": None,
        "term": meta.get("term") or "default",
    }
    session.modified = True

    user_pk = session.get("user_pk")
    if user_pk:
        upsert_course_config(
            user_id=int(user_pk),
            course_key=course_key,
            course_name=meta.get("course_name") or course_key,
            subject_id=meta.get("subject_id"),
            professor_id=meta.get("professor_id"),
            labels=labels_clean,
            secciones=secs_clean,
            term=meta.get("term") or "default",
        )

    return jsonify({"ok": True})


@api_bp.get("/wizard/state")
def wizard_state():
    """Devuelve el estado actual del wizard desde sesión."""
    data = session.get("materia_actual") or {}
    meta = session.get("course_meta") or {}
    return jsonify({"ok": True, "materia_actual": data, "course_meta": meta})


@api_bp.post("/wizard/state")
def wizard_state_post():
    """Alias POST para compatibilidad con el frontend del wizard."""
    return wizard_state()


@api_bp.post("/wizard/notes/save")
def wizard_notes_save():
    """
    Guarda notas (0..100) para una sección por índice.
    JSON: { course_key, section_index, notes:[...] }
    """
    payload = request.get_json(force=True, silent=True) or {}
    course_key = str(payload.get("course_key") or "").strip()
    try:
        idx = int(payload.get("section_index"))
    except Exception:
        idx = -1
    notes_in = payload.get("notes") or []

    data = session.get("materia_actual") or {}
    if not course_key or data.get("nombre") != course_key:
        return jsonify({"ok": False, "error": "No hay materia configurada en sesión."}), 400

    secciones = data.get("secciones") or []
    labels = data.get("labels") or []
    if idx < 0 or idx >= len(secciones):
        return jsonify({"ok": False, "error": "Sección inválida."}), 400

    # Sanitizar notas:
    # - acepta números (0..100) => base=100
    # - acepta dict {score, base} => se valida score/base
    cleaned: list[dict] = []
    for x in notes_in:
        # Caso dict: {score, base}
        if isinstance(x, dict):
            try:
                score = float(x.get("score"))
                base = float(x.get("base", 100.0))
            except Exception:
                continue
            if base <= 0:
                continue
            if score < 0 or score > base:
                continue
            cleaned.append({"score": float(score), "base": float(base)})
            continue

        # Caso numérico: se asume escala 0..100
        try:
            v = float(x)
        except Exception:
            continue
        if v < 0 or v > 100:
            continue
        cleaned.append({"score": float(v), "base": 100.0})

    # limitar al total permitido en la sección
    total = int(secciones[idx].get("num_notas", 0) or 0)
    if total > 0 and len(cleaned) > total:
        cleaned = cleaned[:total]

    old = list(secciones[idx].get("notas_obtenidas") or [])
    secciones[idx]["notas_obtenidas"] = cleaned
    data["secciones"] = secciones
    session["materia_actual"] = data
    session.modified = True

    # Persistir en BD si hay usuario
    user_pk = session.get("user_pk")
    meta = session.get("course_meta") or {}
    term = data.get("term") or meta.get("term") or "default"
    if user_pk:
        from app.services.user_progress import save_section_notes
        save_section_notes(
            user_id=int(user_pk),
            course_key=course_key,
            section_position=int(idx),
            num_notas=int(total),
            notas_obtenidas=cleaned,
            term=str(term),
        )

    # Log de observaciones (solo nuevas)
    old_len = len(old)
    new_len = len(cleaned)
    if new_len > old_len:
        # model_key agregado por materia (si existe code)
        model_key = course_key
        subject_id = meta.get("subject_id")
        if subject_id:
            db = SessionLocal()
            try:
                subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
                if subj and subj.code:
                    model_key = f"subj:{str(subj.code)}"
            finally:
                db.close()
        eval_label = labels[idx] if idx < len(labels) else "Otros"
        for k in range(old_len, new_len):
            try:
                s_val_norm = normalize_nota(cleaned[k])
                log_observed_score(model_key, eval_label, s_val_norm)
                resolve_predictions_with_new_score(course_key, eval_label, s_val_norm)
            except Exception:
                pass

    return jsonify({"ok": True})


@api_bp.post("/wizard/proyectar")
def wizard_proyectar():
    payload = request.get_json(force=True, silent=True) or {}
    course_key = str(payload.get("course_key") or "").strip()
    objetivo_grade = str(payload.get("objetivo_grade") or "").strip()
    if not course_key:
        return jsonify({"ok": False, "error": "Falta course_key."}), 400

    data = session.get("materia_actual") or {}
    if data.get("nombre") != course_key:
        return jsonify({"ok": False, "error": "No hay materia configurada en sesión."}), 400

    objetivo = grade_to_objective(objetivo_grade)
    if objetivo is None:
        return jsonify({"ok": False, "error": "Objetivo inválido."}), 400

    session["materia_actual"]["objetivo"] = float(objetivo)
    session.modified = True

    user_pk = session.get("user_pk")
    meta = session.get("course_meta") or {}
    if user_pk:
        set_course_objetivo(user_id=int(user_pk), course_key=course_key, objetivo=float(objetivo), term=meta.get("term") or "default")

    secciones = data.get("secciones") or []
    labels = data.get("labels") or []
    nota_actual = calcular_nota_actual(secciones)

    model_key = course_key
    subject_id = meta.get("subject_id")
    if subject_id:
        db = SessionLocal()
        try:
            subj = db.query(Subject).filter(Subject.id == int(subject_id)).one_or_none()
            if subj and subj.code:
                model_key = f"subj:{str(subj.code)}"
        finally:
            db.close()

    res = optimize_auto_backend(
        secciones=secciones,
        labels=labels,
        course_key=course_key,
        model_key=model_key,
        nota_actual=nota_actual,
        objetivo=float(objetivo),
    )
    return jsonify({"ok": True, "result": res, "objetivo": float(objetivo), "nota_actual": float(round(nota_actual, 2))})
@api_bp.post("/calc")
def calc():
    """
    Espera JSON:
    {
      "secciones": [
        {"porcentaje": 20, "num_notas": 4, "notas_obtenidas": [80, 90]},  # 20 o 0.2
        ...
      ],
      "objetivo": 81  # opcional
    }
    """
    try:
        data = request.get_json(force=True, silent=False)
        raw = data.get("secciones", [])
        objetivo = data.get("objetivo", None)

        # Normalizamos SOLO aquí para aceptar 0..100 o 0..1,
        # pero dentro de la app seguimos guardando fracción (0..1)
        secciones = []
        for s in raw:
            p = float(s.get("porcentaje", 0.0))
            if p > 1.0:  # si vino 20 => 0.2
                p = p / 100.0
            n = int(s.get("num_notas", 0))
            notas = [float(x) for x in s.get("notas_obtenidas", [])]
            secciones.append({
                "porcentaje": p,           # fracción 0..1
                "num_notas": n,
                "notas_obtenidas": notas
            })

        res = resumen_desde_secciones(secciones, objetivo)
        return jsonify({"ok": True, "data": res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
