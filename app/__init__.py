import os
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask

def create_app():
    # Cargar .env también en runtime (no solo en Alembic)
    base_dir = Path(__file__).resolve().parents[1]
    load_dotenv(dotenv_path=base_dir / ".env")

    app = Flask(__name__)
    # Seguridad: usar SECRET_KEY desde entorno en despliegue real
    app.secret_key = os.getenv("SECRET_KEY", "dev-secret")

    # Importar DB session DESPUÉS de cargar .env, para que DATABASE_URL aplique.
    from .db import SessionLocal

    @app.teardown_appcontext
    def remove_session(exc=None):
        SessionLocal.remove()

    # importa los blueprints DENTRO de la factory
    from .routes import web_bp
    app.register_blueprint(web_bp)

    from .api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    return app