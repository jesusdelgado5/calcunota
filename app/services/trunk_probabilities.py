"""
Probabilidades base (sintéticas) por materia (tronco de ingeniería) y tipo de sección.

Fuente: tablas proporcionadas (Excel).
Objetivo:
- Generar data histórica sintética (ObservedEvalScore)
- Inicializar priors (EvalDifficultyPrior) mediante recompute_priors.py

Notas:
- Las tablas usan valores aproximados ("~" y ">1%"). Aquí se modelan como pesos
  y luego se normaliza a probabilidad (suma=1).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple
import random
import math


# -------------------- Materias (catálogo) --------------------
@dataclass(frozen=True)
class TrunkSubject:
    name: str
    code: str
    credits: int
    mu_mean: float
    sigma_mean: float
    group: str  # "soft" o "hard"


TRUNK_SUBJECTS: List[TrunkSubject] = [
    TrunkSubject("INGLES I", "8403", 3, 85, 10, "soft"),
    TrunkSubject("INGLES II", "8355", 3, 85, 10, "soft"),
    TrunkSubject("GEOGRAFIA DE PANAMA", "1403", 3, 85, 10, "soft"),
    TrunkSubject("DESARROLLO LOGICO Y ALGORITMOS", "0741", 4, 81, 10, "soft"),
    TrunkSubject("DIBUJO I", "1548", 4, 81, 10, "soft"),
    TrunkSubject("COMUNICACIÓN ORAL Y ESCRITA", "8360", 3, 81, 10, "soft"),
    TrunkSubject("CALCULO I", "7987", 5, 71, 20, "hard"),
    TrunkSubject("CALCULO II", "7988", 5, 61, 20, "hard"),
    TrunkSubject("CALCULO III", "8322", 4, 71, 20, "hard"),
    TrunkSubject("FISICA I", "8319", 5, 71, 20, "hard"),
    TrunkSubject("FISICA II", "8320", 5, 61, 20, "hard"),
    TrunkSubject("QUIMICA I", "1547", 4, 75, 16, "hard"),
]


# -------------------- Distribuciones por grupo --------------------
# Bins en escala 0..100 (incluye 100 como punto)
_BINS: List[Tuple[int, int]] = [
    (0, 10),
    (11, 20),
    (21, 30),
    (31, 40),
    (41, 50),
    (51, 60),
    (61, 70),
    (71, 80),
    (81, 90),
    (91, 99),
    (100, 100),
]


def _norm_weights(ws: List[float]) -> List[float]:
    s = float(sum(max(0.0, w) for w in ws))
    if s <= 0:
        return [1.0 / len(ws)] * len(ws)
    return [max(0.0, w) / s for w in ws]


def _sample_from_bins(rng: random.Random, weights: List[float]) -> int:
    """Devuelve una nota entera 0..100 (uniforme dentro del bin elegido)."""
    probs = _norm_weights(weights)
    r = rng.random()
    acc = 0.0
    idx = 0
    for i, p in enumerate(probs):
        acc += p
        if r <= acc:
            idx = i
            break
    lo, hi = _BINS[idx]
    if lo == hi:
        return int(lo)
    return int(rng.randint(int(lo), int(hi)))


def _stats_from_bins(weights: List[float]) -> Tuple[float, float]:
    """
    Media y sigma aproximadas usando el centro de cada bin.
    """
    probs = _norm_weights(weights)
    centers = [0.5 * (lo + hi) for lo, hi in _BINS]
    mu = sum(p * c for p, c in zip(probs, centers))
    var = sum(p * (c - mu) ** 2 for p, c in zip(probs, centers))
    return float(mu), float(math.sqrt(max(1e-9, var)))


# Pesos aproximados por tabla (se normalizan internamente)
SOFT_WEIGHTS_BY_TYPE: Dict[str, List[float]] = {
    # (Inglés/Geografía/DLA/Dibujo/COE/Ing II)
    "Semestral":      [1, 1, 1, 1, 1, 5, 20, 45, 20, 10, 1],
    "Parciales":      [1, 1, 1, 1, 1, 1, 5, 35, 30, 20, 10],
    "Laboratorios":   [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Tareas":         [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Proyectos":      [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Quices":         [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Portafolio":     [1, 1, 1, 1, 1, 1, 1, 1, 5, 10, 85],
    "Asistencia":     [1, 1, 1, 1, 1, 1, 1, 1, 10, 5, 80],
    "Otros":          [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
}

HARD_WEIGHTS_BY_TYPE: Dict[str, List[float]] = {
    # (Cálculos/Física/Química)
    "Semestral":      [1, 1, 1, 1, 5, 25, 30, 25, 10, 5, 1],
    "Parciales":      [1, 1, 1, 1, 3, 12, 35, 25, 12, 12, 1],
    "Laboratorios":   [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Tareas":         [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Proyectos":      [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
    "Quices":         [1, 1, 1, 1, 3, 12, 35, 25, 12, 12, 1],
    "Portafolio":     [1, 1, 1, 1, 1, 1, 1, 1, 5, 10, 85],
    "Asistencia":     [1, 1, 1, 1, 1, 1, 1, 1, 10, 5, 80],
    "Otros":          [1, 1, 1, 1, 1, 1, 1, 10, 20, 45, 25],
}


def weights_for(subject_group: str, section_type: str) -> List[float]:
    if subject_group == "hard":
        return HARD_WEIGHTS_BY_TYPE.get(section_type, HARD_WEIGHTS_BY_TYPE["Otros"])
    return SOFT_WEIGHTS_BY_TYPE.get(section_type, SOFT_WEIGHTS_BY_TYPE["Otros"])


def sample_score(subject_group: str, section_type: str, *, seed: int, i: int) -> int:
    rng = random.Random((seed * 1000003) ^ (i * 9176) ^ hash((subject_group, section_type)))
    return _sample_from_bins(rng, weights_for(subject_group, section_type))


def prior_mu_sigma(subject_group: str, section_type: str) -> Tuple[float, float]:
    return _stats_from_bins(weights_for(subject_group, section_type))

