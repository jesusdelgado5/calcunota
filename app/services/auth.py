from __future__ import annotations

from typing import Optional

from sqlalchemy import MetaData, Table, select, update
from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
from datetime import datetime, timedelta

from app.db import SessionLocal
from app.db.models import PasswordResetToken


def _app_user_table(db) -> Table:
    # Refleja el esquema real (evita fallas si faltan columnas nuevas).
    md = MetaData()
    return Table("app_user", md, autoload_with=db.bind)


def register_user(
    username: str,
    password: str,
    *,
    first_name: str | None = None,
    last_name: str | None = None,
    email: str | None = None,
) -> Optional[int]:
    username = (username or "").strip()
    if not username or not password:
        return None
    db = SessionLocal()
    try:
        t = _app_user_table(db)
        exists = db.execute(select(t.c.id).where(t.c.username == username)).scalar_one_or_none()
        if exists:
            return None

        values = {
            "username": username,
            "password_hash": generate_password_hash(password),
        }
        if "first_name" in t.c:
            values["first_name"] = (first_name or "").strip() or None
        if "last_name" in t.c:
            values["last_name"] = (last_name or "").strip() or None
        if "email" in t.c:
            values["email"] = (email or "").strip() or None

        db.execute(t.insert().values(**values))
        db.commit()
        return db.execute(select(t.c.id).where(t.c.username == username)).scalar_one()
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def authenticate_user(username: str, password: str) -> Optional[int]:
    username = (username or "").strip()
    if not username or not password:
        return None
    db = SessionLocal()
    try:
        t = _app_user_table(db)
        row = db.execute(select(t.c.id, t.c.password_hash).where(t.c.username == username)).first()
        if not row:
            return None
        user_id = int(row[0])
        pwd_hash = row[1]
        if not pwd_hash:
            return None
        if not check_password_hash(pwd_hash, password):
            return None
        return user_id
    except SQLAlchemyError:
        return None
    finally:
        db.close()


def change_password(user_id: int, current_password: str, new_password: str) -> bool:
    if not current_password or not new_password or len(new_password) < 6:
        return False
    db = SessionLocal()
    try:
        t = _app_user_table(db)
        row = db.execute(select(t.c.password_hash).where(t.c.id == int(user_id))).scalar_one_or_none()
        if not row:
            return False
        if not check_password_hash(row, current_password):
            return False
        db.execute(update(t).where(t.c.id == int(user_id)).values(password_hash=generate_password_hash(new_password)))
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


def issue_reset_token(username: str, *, ttl_minutes: int = 15) -> Optional[str]:
    """
    Modo dev: genera un token y lo retorna para mostrarlo al usuario (en prod se enviaría por email).
    """
    username = (username or "").strip()
    if not username:
        return None
    db = SessionLocal()
    try:
        t = _app_user_table(db)
        user_id = db.execute(select(t.c.id).where(t.c.username == username)).scalar_one_or_none()
        if not user_id:
            return None
        token = secrets.token_urlsafe(24)
        token_hash = generate_password_hash(token)
        expires_at = datetime.utcnow() + timedelta(minutes=int(ttl_minutes))
        row = PasswordResetToken(user_id=int(user_id), token_hash=token_hash, expires_at=expires_at)
        db.add(row)
        db.commit()
        return token
    except SQLAlchemyError:
        try:
            db.rollback()
        except Exception:
            pass
        return None
    finally:
        db.close()


def reset_password(username: str, token: str, new_password: str) -> bool:
    if not username or not token or not new_password or len(new_password) < 6:
        return False
    db = SessionLocal()
    try:
        t = _app_user_table(db)
        user_id = db.execute(select(t.c.id).where(t.c.username == username)).scalar_one_or_none()
        if not user_id:
            return False
        now = datetime.utcnow()
        rows = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == int(user_id),
                PasswordResetToken.used == False,
                PasswordResetToken.expires_at > now,
            )
            .order_by(PasswordResetToken.issued_at.desc())
            .limit(10)
            .all()
        )
        ok_row = None
        for r in rows:
            if check_password_hash(r.token_hash, token):
                ok_row = r
                break
        if not ok_row:
            return False
        ok_row.used = True
        db.execute(update(t).where(t.c.id == int(user_id)).values(password_hash=generate_password_hash(new_password)))
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

