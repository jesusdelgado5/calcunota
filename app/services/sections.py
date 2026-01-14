"""
Taxonomía de secciones (tipos) estandarizada.

Objetivo:
- Evitar ambigüedades de escritura (backend consistente)
- Permitir priors/probabilidades por (materia, tipo de sección)
"""

from __future__ import annotations

from typing import List


# Tipos estándar (en español, tal como se muestran en UI)
SECTION_TYPES: List[str] = [
    "Semestral",
    "Parciales",
    "Laboratorios",
    "Tareas",
    "Proyectos",
    "Quices",
    "Portafolio",
    "Asistencia",
    "Otros",
]


def normalize_section_label(label: str) -> str:
    """
    Normaliza una etiqueta proveniente de UI.
    Hoy el usuario elige de un dropdown, así que esta función es defensiva.
    """
    lbl = (label or "").strip()
    if not lbl:
        return "Otros"
    # Coincidencia exacta primero
    if lbl in SECTION_TYPES:
        return lbl
    # Heurística por minúsculas
    low = lbl.lower()
    aliases = {
        "semestral": "Semestral",
        "examen semestral": "Semestral",
        "parcial": "Parciales",
        "parciales": "Parciales",
        "lab": "Laboratorios",
        "laboratorio": "Laboratorios",
        "laboratorios": "Laboratorios",
        "tarea": "Tareas",
        "tareas": "Tareas",
        "proyecto": "Proyectos",
        "proyectos": "Proyectos",
        "quiz": "Quices",
        "quices": "Quices",
        "portafolio": "Portafolio",
        "asistencia": "Asistencia",
    }
    return aliases.get(low, "Otros")

