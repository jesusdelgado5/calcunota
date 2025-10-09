# app.py
from flask import Flask
from app.db import SessionLocal

app = Flask(__name__)  # 1) crear la app primero

@app.teardown_appcontext
def remove_session(exc=None):
    # 2) ahora sí, usar el decorador
    SessionLocal.remove()

if __name__ == "__main__":
    app.run(debug=True)

