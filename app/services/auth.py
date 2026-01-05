from __future__ import annotations

from typing import Optional

from sqlalchemy.exc import SQLAlchemyError
from werkzeug.security import check_password_hash, generate_password_hash
import secrets
from datetime import datetime, timedelta

from app.db import SessionLocal
from app.db.models import AppUser, PasswordResetToken


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


def change_password(user_id: int, current_password: str, new_password: str) -> bool:
    if not current_password or not new_password or len(new_password) < 6:
        return False
    db = SessionLocal()
    try:
        row = db.query(AppUser).filter(AppUser.id == int(user_id)).one_or_none()
        if not row or not row.password_hash:
            return False
        if not check_password_hash(row.password_hash, current_password):
            return False
        row.password_hash = generate_password_hash(new_password)
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
        user = db.query(AppUser).filter(AppUser.username == username).one_or_none()
        if not user:
            return None
        token = secrets.token_urlsafe(24)
        token_hash = generate_password_hash(token)
        expires_at = datetime.utcnow() + timedelta(minutes=int(ttl_minutes))
        row = PasswordResetToken(user_id=user.id, token_hash=token_hash, expires_at=expires_at)
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
        user = db.query(AppUser).filter(AppUser.username == username).one_or_none()
        if not user:
            return False
        now = datetime.utcnow()
        rows = (
            db.query(PasswordResetToken)
            .filter(
                PasswordResetToken.user_id == user.id,
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
        user.password_hash = generate_password_hash(new_password)
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

