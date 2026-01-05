from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash

from app.db import SessionLocal
from app.db.models import AppUser


def register_user(username: str, password: str) -> Optional[int]:
    username = (username or "").strip()
    if not username or not password:
        return None
    db = SessionLocal()
    try:
        exists = db.query(AppUser).filter(AppUser.username == username).one_or_none()
        if exists:
            return None
        row = AppUser(username=username, password_hash=generate_password_hash(password))
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


def authenticate_user(username: str, password: str) -> Optional[int]:
    username = (username or "").strip()
    if not username or not password:
        return None
    db = SessionLocal()
    try:
        row = db.query(AppUser).filter(AppUser.username == username).one_or_none()
        if not row or not row.password_hash:
            return None
        if not check_password_hash(row.password_hash, password):
            return None
        return int(row.id)
    except SQLAlchemyError:
        return None
    finally:
        db.close()

