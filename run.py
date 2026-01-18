"""
Entry-point alternativo para desarrollo.

Preferido: `python wsgi.py` (más explícito), pero este archivo también debe funcionar.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)

