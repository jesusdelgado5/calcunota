from flask import Blueprint, request, jsonify
from .services.grades import resumen_desde_secciones  # <--- usa el nombre nuevo

api_bp = Blueprint("api", __name__)

@api_bp.post("/calc")
def calc():
    """
    Espera JSON:
    {
      "secciones": [
        {"porcentaje": 20, "num_notas": 4, "notas_obtenidas": [80, 90]},  # 20 o 0.2
        ...
      ],
      "objetivo": 81  # opcional
    }
    """
    try:
        data = request.get_json(force=True, silent=False)
        raw = data.get("secciones", [])
        objetivo = data.get("objetivo", None)

        # Normalizamos SOLO aquí para aceptar 0..100 o 0..1,
        # pero dentro de la app seguimos guardando fracción (0..1)
        secciones = []
        for s in raw:
            p = float(s.get("porcentaje", 0.0))
            if p > 1.0:  # si vino 20 => 0.2
                p = p / 100.0
            n = int(s.get("num_notas", 0))
            notas = [float(x) for x in s.get("notas_obtenidas", [])]
            secciones.append({
                "porcentaje": p,           # fracción 0..1
                "num_notas": n,
                "notas_obtenidas": notas
            })

        res = resumen_desde_secciones(secciones, objetivo)
        return jsonify({"ok": True, "data": res})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400
