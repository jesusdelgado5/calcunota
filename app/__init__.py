from flask import Flask
from .db import SessionLocal

def create_app():
    app = Flask(__name__)
    app.secret_key = "dev-secret"  # cambia en producción

    @app.teardown_appcontext
    def remove_session(exc=None):
        SessionLocal.remove()

    # importa los blueprints DENTRO de la factory
    from .routes import web_bp
    app.register_blueprint(web_bp)

    from .api import api_bp
    app.register_blueprint(api_bp, url_prefix="/api")

    return app