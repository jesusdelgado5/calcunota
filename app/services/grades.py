# app/services/grades.py

def calcular_nota_actual(secciones):
    nota_actual = 0.0
    for seccion in secciones:
        num_notas = seccion['num_notas']
        porcentaje = seccion['porcentaje']  # fracción 0..1
        if num_notas > 0:
            suma_norm = sum(normalize_nota(n) for n in seccion['notas_obtenidas'])
            # se mantiene la lógica: dividir por total (faltantes aportan 0)
            nota_actual += (suma_norm / num_notas) * porcentaje
    return float(nota_actual)

def calcular_porcentaje_restante(secciones):
    porcentaje_restante = 0.0
    for seccion in secciones:
        num_rest = seccion['num_notas'] - len(seccion['notas_obtenidas'])
        if seccion['num_notas'] > 0 and num_rest > 0:
            porcentaje_restante += (seccion['porcentaje'] / seccion['num_notas']) * num_rest
    return float(porcentaje_restante)

def calcular_nota_necesaria(nota_actual, porcentaje_restante, objetivo):
    if porcentaje_restante == 0:
        return float('inf')
    return (objetivo - nota_actual) / porcentaje_restante

def resumen_desde_secciones(secciones, objetivo=None):
    """
    Arma un dict de salida con los 3 valores clave.
    Se asume que 'porcentaje' ya viene en fracción (0..1).
    """
    nota_actual = calcular_nota_actual(secciones)
    por_rest = calcular_porcentaje_restante(secciones)

    out = {
        "nota_actual": round(nota_actual, 4),
        "porcentaje_restante": round(por_rest, 6)
    }
    if objetivo is not None:
        necesaria = calcular_nota_necesaria(nota_actual, por_rest, float(objetivo))
        out["nota_necesaria_promedio_restante"] = float('inf') if necesaria == float('inf') else round(necesaria, 4)
        if necesaria == float('inf'):
            out["mensaje"] = "No queda porcentaje disponible para subir la nota."
        elif necesaria > 100:
            out["mensaje"] = "Objetivo inalcanzable: requeriría > 100 en las notas restantes."
        elif necesaria <= 0:
            out["mensaje"] = "Objetivo ya alcanzado."
        else:
            out["mensaje"] = f"Necesitas promedio ~{round(necesaria,2)} en lo que falta."
    return out

def normalize_nota(n):
    """
    Devuelve la nota en escala 0..100.
    - Si n es dict: {'score': X, 'base': B} => (X/B)*100
    - Si n es número: se asume que ya está en 0..100
    - Fallbacks seguros ante valores inválidos
    """
    try:
        if isinstance(n, dict):
            score = float(n.get('score', 0.0))
            base = float(n.get('base', 100.0)) or 100.0
            val = (score / base) * 100.0
            return max(0.0, min(100.0, val))
        else:
            return max(0.0, min(100.0, float(n)))
    except Exception:
        return 0.0