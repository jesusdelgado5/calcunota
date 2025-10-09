from __future__ import with_statement

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool
from alembic import context
from dotenv import load_dotenv

# --- Añade la raíz del proyecto al sys.path ---
BASE_DIR = Path(__file__).resolve().parents[1]  # .../flask-app
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# --- Carga variables del .env (si existe) ---
load_dotenv(dotenv_path=BASE_DIR / ".env")

# Este objeto config da acceso a alembic.ini
config = context.config

# Si hay DATABASE_URL en el entorno, pisa la url de alembic.ini
database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Logging de Alembic
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Importa tu metadata para autogenerate
from app.db.models import Base
target_metadata = Base.metadata

print(">> Alembic DB URL:", context.config.get_main_option("sqlalchemy.url"))

def run_migrations_offline():
    """Migrations en modo 'offline' (sin conexión real)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url, target_metadata=target_metadata,
        literal_binds=True, dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()

def run_migrations_online():
    """Migrations en modo 'online' (con conexión)."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
