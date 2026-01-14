import os
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine
from sqlalchemy.engine.url import make_url
from sqlalchemy.orm import sessionmaker, scoped_session

# Cargar .env también para scripts (seed/retrain) que importan SessionLocal
_BASE_DIR = Path(__file__).resolve().parents[2]  # repo root
load_dotenv(dotenv_path=_BASE_DIR / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///calcu.db")

_connect_args = {}
try:
    url = make_url(DATABASE_URL)
    # Evita “quedarse cargando” cuando la DB no está disponible (p.ej. Postgres local apagado).
    if url.drivername and not url.drivername.startswith("sqlite"):
        _connect_args = {"connect_timeout": int(os.getenv("DB_CONNECT_TIMEOUT", "3"))}
except Exception:
    _connect_args = {}

engine = create_engine(
    DATABASE_URL,
    future=True,
    pool_pre_ping=True,
    connect_args=_connect_args,
)
SessionLocal = scoped_session(
    sessionmaker(bind=engine, autoflush=False, autocommit=False)
)
