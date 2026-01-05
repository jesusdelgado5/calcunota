from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from sqlalchemy import and_
from sqlalchemy.exc import SQLAlchemyError

from app.db import SessionLocal
from app.db.models import AppUser, UserCourse, UserCourseSection, UserCourseNote
from app.services.grades import normalize_nota


@dataclass
class UserCourseSummary:
    course_key: str
    course_name: str | None
    term: str
    objetivo: float | None
    updated_at: Any
    total_slots: int
    filled_slots: int


def ensure_user(username: str) -> Optional[int]:
    """Crea el usuario si no existe; devuelve app_user.id."""
    db = SessionLocal()
    try:
        row = db.query(AppUser).filter(AppUser.username == username).one_or_none()
        if row:
            return int(row.id)
        row = AppUser(username=username)
        db.add(row)
        db.commit()
        db.refresh(row)
        return int(row.id)
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def upsert_course_config(
    *,
    user_id: int,
    course_key: str,
    course_name: str | None,
    subject_id: int | None = None,
    professor_id: int | None = None,
    labels: List[str],
    secciones: List[Dict[str, Any]],
    term: str = "default",
) -> Optional[int]:
    """
    Guarda/actualiza la configuración de una materia (secciones).
    Nota: por simplicidad, al reconfigurar se eliminan secciones/notas previas.
    """
    db = SessionLocal()
    try:
        course = (
            db.query(UserCourse)
            .filter(
                UserCourse.user_id == user_id,
                UserCourse.course_key == course_key,
                UserCourse.term == term,
            )
            .one_or_none()
        )
        if not course:
            course = UserCourse(
                user_id=user_id,
                course_key=course_key,
                course_name=course_name,
                term=term,
            )
            db.add(course)
            db.flush()
        else:
            course.course_name = course_name or course.course_name
            course.subject_id = subject_id if subject_id is not None else course.subject_id
            course.professor_id = professor_id if professor_id is not None else course.professor_id

        if subject_id is not None:
            course.subject_id = int(subject_id)
        if professor_id is not None:
            course.professor_id = int(professor_id)

        # Limpia secciones + notas (CASCADE desde secciones)
        db.query(UserCourseSection).filter(UserCourseSection.user_course_id == course.id).delete()

        for i, (label, sec) in enumerate(zip(labels, secciones)):
            s = UserCourseSection(
                user_course_id=course.id,
                position=int(i),
                label=str(label),
                porcentaje=float(sec.get("porcentaje", 0.0)),
                num_notas=int(sec.get("num_notas", 0)),
            )
            db.add(s)

        db.commit()
        return int(course.id)
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def set_course_objetivo(*, user_id: int, course_key: str, objetivo: float | None, term: str = "default") -> bool:
    db = SessionLocal()
    try:
        course = (
            db.query(UserCourse)
            .filter(
                UserCourse.user_id == user_id,
                UserCourse.course_key == course_key,
                UserCourse.term == term,
            )
            .one_or_none()
        )
        if not course:
            return False
        course.objetivo = float(objetivo) if objetivo is not None else None
        db.commit()
        return True
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        db.close()


def save_section_notes(
    *,
    user_id: int,
    course_key: str,
    section_position: int,
    num_notas: int,
    notas_obtenidas: List[Dict[str, Any]],
    term: str = "default",
) -> bool:
    """Guarda notas (score/base) de una sección."""
    db = SessionLocal()
    try:
        course = (
            db.query(UserCourse)
            .filter(
                UserCourse.user_id == user_id,
                UserCourse.course_key == course_key,
                UserCourse.term == term,
            )
            .one_or_none()
        )
        if not course:
            return False

        sec = (
            db.query(UserCourseSection)
            .filter(
                UserCourseSection.user_course_id == course.id,
                UserCourseSection.position == int(section_position),
            )
            .one_or_none()
        )
        if not sec:
            return False

        sec.num_notas = int(num_notas)

        # Upsert por índice
        wanted = []
        for i, n in enumerate(notas_obtenidas or []):
            score = float((n or {}).get("score", 0.0))
            base = float((n or {}).get("base", 100.0) or 100.0)
            if base <= 0:
                base = 100.0
            norm = float(normalize_nota({"score": score, "base": base}))
            wanted.append((i, score, base, norm))

        existing = {
            int(r.note_index): r
            for r in db.query(UserCourseNote).filter(UserCourseNote.section_id == sec.id).all()
        }

        keep_idxs = set()
        for idx, score, base, norm in wanted:
            keep_idxs.add(idx)
            if idx in existing:
                row = existing[idx]
                row.score = score
                row.base = base
                row.normalized = norm
            else:
                db.add(
                    UserCourseNote(
                        section_id=sec.id,
                        note_index=idx,
                        score=score,
                        base=base,
                        normalized=norm,
                    )
                )

        # Borra sobras si el usuario redujo notas
        for idx, row in existing.items():
            if idx not in keep_idxs:
                db.delete(row)

        db.commit()
        return True
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        db.close()


def load_course_state(*, user_id: int, course_key: str, term: str = "default") -> Optional[Dict[str, Any]]:
    """
    Devuelve dict compatible con session['materia_actual']:
    {nombre, labels, secciones, objetivo}
    """
    db = SessionLocal()
    try:
        course = (
            db.query(UserCourse)
            .filter(
                UserCourse.user_id == user_id,
                UserCourse.course_key == course_key,
                UserCourse.term == term,
            )
            .one_or_none()
        )
        if not course:
            return None

        secs = (
            db.query(UserCourseSection)
            .filter(UserCourseSection.user_course_id == course.id)
            .order_by(UserCourseSection.position.asc())
            .all()
        )
        labels: List[str] = []
        secciones: List[Dict[str, Any]] = []
        for sec in secs:
            labels.append(sec.label)
            notes = (
                db.query(UserCourseNote)
                .filter(UserCourseNote.section_id == sec.id)
                .order_by(UserCourseNote.note_index.asc())
                .all()
            )
            secciones.append(
                {
                    "porcentaje": float(sec.porcentaje),
                    "num_notas": int(sec.num_notas),
                    "notas_obtenidas": [{"score": float(n.score), "base": float(n.base)} for n in notes],
                }
            )

        return {
            "nombre": course_key,
            "labels": labels,
            "secciones": secciones,
            "objetivo": float(course.objetivo) if course.objetivo is not None else None,
        }
    except SQLAlchemyError:
        return None
    finally:
        db.close()


def list_user_courses(*, user_id: int, term: str = "default") -> List[UserCourseSummary]:
    db = SessionLocal()
    try:
        courses = (
            db.query(UserCourse)
            .filter(UserCourse.user_id == user_id)
            .order_by(UserCourse.updated_at.desc())
            .all()
        )
        out: List[UserCourseSummary] = []
        for c in courses:
            secs = db.query(UserCourseSection).filter(UserCourseSection.user_course_id == c.id).all()
            total_slots = sum(max(0, int(s.num_notas)) for s in secs)
            # Count notes rows (cheaper than joining all notes)
            filled_slots = (
                db.query(UserCourseNote)
                .join(UserCourseSection, UserCourseNote.section_id == UserCourseSection.id)
                .filter(UserCourseSection.user_course_id == c.id)
                .count()
            )
            out.append(
                UserCourseSummary(
                    course_key=str(c.course_key),
                    course_name=c.course_name,
                    term=str(c.term),
                    objetivo=float(c.objetivo) if c.objetivo is not None else None,
                    updated_at=c.updated_at,
                    total_slots=int(total_slots),
                    filled_slots=int(filled_slots),
                )
            )
        return out
    except SQLAlchemyError:
        return []
    finally:
        db.close()

