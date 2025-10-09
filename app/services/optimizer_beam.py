# app/services/optimizer_beam.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import math
import numpy as np

from app.services.grades import normalize_nota, calcular_nota_actual

# (opcional) priors por materia/sección
try:
    from app.services.priors import get_eval_prior  # (course_key:str|None, eval_label:str) -> (mu0, sigma0)
except Exception:
    def get_eval_prior(course_key: str | None, eval_label: str) -> Tuple[float, float]:
        return 70.0, 12.0  # fallback

# --- Normal CDF: usa SciPy si está, si no usa aproximación rápida ---
try:
    from scipy.stats import norm as _scipy_norm
    def _tail_prob_normal(s: float, mu: float, sigma: float, pmin: float = 1e-8) -> float:
        if sigma <= 1e-9:
            return 1.0 if mu >= s else pmin
        z = (s - mu) / sigma
        p = 1.0 - _scipy_norm.cdf(z)
        return max(p, pmin)
except Exception:
    from math import erf
    def _phi(x: float) -> float:
        return 0.5 * (1.0 + erf(x / math.sqrt(2.0)))
    def _tail_prob_normal(s: float, mu: float, sigma: float, pmin: float = 1e-8) -> float:
        if sigma <= 1e-9:
            return 1.0 if mu >= s else pmin
        z = (s - mu) / sigma
        p = 1.0 - _phi(z)
        return max(p, pmin)

# ---------------- Datos y helpers ----------------
@dataclass
class EvalSpec:
    eval_id: str
    name: str
    weight: float     # w_j en [0,1]
    mu: float         # media (0..100)
    sigma: float      # desviación (>0)
    s_min: int        # grid min (0..100)
    s_max: int        # grid max (0..100)
    s_step: int       # paso (>=1)

    @property
    def grid(self) -> List[int]:
        return list(range(int(self.s_min), int(self.s_max) + 1, int(self.s_step)))


def _estimate_mu_sigma(
    notas_norm: List[float],
    prior_mu: float = 70.0,
    prior_sigma: float = 12.0,
    prior_weight: float = 2.0
) -> Tuple[float, float]:
    """
    Estima mu/sigma con 'shrinkage' hacia un prior si hay poca data.
    - mu_hat = (k*mean + prior_weight*prior_mu) / (k+prior_weight)
    - sigma_hat: si k>=2 usa std muestral (suavizada), si k<2 usa prior_sigma
    """
    xs = [float(x) for x in (notas_norm or []) if x is not None]
    k = len(xs)
    if k == 0:
        return float(prior_mu), float(prior_sigma)
    mean = float(np.mean(xs))
    if k >= 2:
        sd = float(np.std(xs, ddof=1))
    else:
        sd = float(prior_sigma)
    mu_hat = (k * mean + prior_weight * prior_mu) / (k + prior_weight)
    # Limitar sd para evitar valores degenerados
    sd_hat = min(25.0, max(4.0, (sd + prior_sigma) / 2.0))
    return float(mu_hat), float(sd_hat)


def _norm_list(notas_raw: List[Any]) -> List[float]:
    """Convierte una lista de notas (floats/ints o dicts {'score','base'}) a escala 0..100."""
    return [normalize_nota(n) for n in (notas_raw or [])]


def build_evals_from_secciones(
    secciones: List[Dict[str, Any]],
    labels: Optional[List[str]] = None,
    *,
    default_min: int = 50,
    final_min: int = 40,
    default_step: int = 5,
    course_key: str | None = None
) -> List[EvalSpec]:
    """
    Convierte 'secciones' en evaluaciones pendientes por nota.
    - weight por nota = (porcentaje / num_notas)  [porcentaje ya en fracción 0..1]
    - μ, σ se estiman desde historial normalizado con shrink a priors (si hay).
    - Grid por defecto: [min..100] con step 5 (más laxo si detecta 'final/semestral').
    """
    evals: List[EvalSpec] = []
    labels = labels or [f"Sección {i+1}" for i in range(len(secciones))]

    for i, sec in enumerate(secciones):
        W_sec = float(sec.get("porcentaje", 0.0))  # fracción 0..1
        m = int(sec.get("num_notas", 0))
        hist_norm = _norm_list(sec.get("notas_obtenidas") or [])
        k_realizadas = len(hist_norm)
        pendientes = max(0, m - k_realizadas)

        if m <= 0 or pendientes <= 0 or W_sec <= 0:
            continue

        w_item = W_sec / float(m)

        label_str = labels[i] or f"Sección {i+1}"
        # priors opcionales por sección
        mu0, sigma0 = get_eval_prior(course_key, label_str)
        mu_hat, sigma_hat = _estimate_mu_sigma(hist_norm, prior_mu=mu0, prior_sigma=sigma0)

        # Heurística de grid mínimo
        low = label_str.lower()
        is_final_like = any(x in low for x in ["final", "semestral", "examen final"])
        gmin = final_min if is_final_like else default_min

        for j in range(k_realizadas, m):
            idx = j + 1
            eid = f"sec{i+1}_nota{idx}"
            name = f"{label_str} - Nota {idx}"
            evals.append(EvalSpec(
                eval_id=eid, name=name, weight=w_item, mu=mu_hat, sigma=sigma_hat,
                s_min=gmin, s_max=100, s_step=default_step
            ))

    return evals

# --------------- Beam Search + MC ----------------
def _precompute_tail_tables(evals: List[EvalSpec], pmin: float = 1e-8) -> Dict[str, Dict[int, float]]:
    tail_p: Dict[str, Dict[int, float]] = {}
    for e in evals:
        pmap: Dict[int, float] = {}
        for s in e.grid:
            pmap[s] = _tail_prob_normal(s, e.mu, e.sigma, pmin=pmin)
        tail_p[e.eval_id] = pmap
    return tail_p


def _beam_search(
    evals: List[EvalSpec], nota_actual: float, objetivo: float, tail_p: Dict[str, Dict[int, float]],
    beam_width: int = 64, max_nodes_per_level: int = 256, diversify_per_eval: int = 6
) -> List[Dict[str, Any]]:
    if objetivo <= nota_actual:
        return [{"targets": {}, "sum_contrib": 0.0, "sum_cost": 0.0, "prod_prob": 1.0}]

    required = objetivo - nota_actual
    evals_sorted = sorted(evals, key=lambda e: e.weight, reverse=True)
    beam: List[Tuple[float, float, Dict[str, int]]] = [(0.0, 0.0, {})]

    # Poda de factibilidad con máximos restantes
    max_remain = [0.0] * (len(evals_sorted) + 1)
    for i in range(len(evals_sorted) - 1, -1, -1):
        e = evals_sorted[i]
        max_remain[i] = max_remain[i+1] + e.weight * max(e.grid)

    def feasible(sum_contrib: float, level: int) -> bool:
        return (sum_contrib + max_remain[level]) + 1e-9 >= required

    for level, e in enumerate(evals_sorted):
        new_nodes: List[Tuple[float, float, Dict[str, int]]] = []

        # costo por punto (más bajo es mejor)
        def cpp(s: int) -> float:
            p = tail_p[e.eval_id][s]
            contrib = max(1e-9, e.weight * s)
            return (-math.log(p)) / contrib

        grid_sorted = sorted(e.grid, key=cpp)
        candidates_s = list(dict.fromkeys(
            [grid_sorted[i] for i in range(min(diversify_per_eval, len(grid_sorted)))] +
            [min(e.grid), max(e.grid)]
        ))

        for sc, cc, t in beam:
            for s in candidates_s:
                sc2 = sc + e.weight * s
                if not feasible(sc2, level + 1):
                    continue
                c_add = -math.log(tail_p[e.eval_id][s])
                new_nodes.append((sc2, cc + c_add, {**t, e.eval_id: s}))

        if not new_nodes:
            break

        def key(n: Tuple[float, float, Dict[str, int]]):
            sc2, c2, _ = n
            gap = max(0.0, required - sc2)
            return (gap, c2, -sc2)

        new_nodes.sort(key=key)
        new_nodes = new_nodes[:max_nodes_per_level]
        beam = new_nodes[:beam_width]

    plans: List[Dict[str, Any]] = []
    for sc, c, t in beam:
        if len(t) == len(evals_sorted) and sc + 1e-9 >= required:
            plans.append({"targets": t, "sum_contrib": sc, "sum_cost": c, "prod_prob": math.exp(-c)})
    plans.sort(key=lambda d: (-d["prod_prob"], d["sum_cost"]))
    return plans


def _mc_samples(evals: List[EvalSpec], N: int = 20000, seed: Optional[int] = 123) -> Dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    out: Dict[str, np.ndarray] = {}
    for e in evals:
        y = rng.normal(e.mu, e.sigma, size=N)
        y = np.clip(y, 0.0, 100.0).astype(np.float32)
        out[e.eval_id] = y
    return out


def _prob_objectivo_mc(nota_actual: float, objetivo: float, evals: List[EvalSpec], samples: Dict[str, np.ndarray]) -> float:
    N = len(next(iter(samples.values())))
    total = np.full(N, float(nota_actual), dtype=np.float32)
    for e in evals:
        total += e.weight * samples[e.eval_id]
    return float(np.mean(total >= objetivo))


def _prob_plan_mc(plan: Dict[str, Any], samples: Dict[str, np.ndarray]) -> float:
    N = len(next(iter(samples.values())))
    ok = np.ones(N, dtype=bool)
    for eid, s in plan["targets"].items():
        ok &= (samples[eid] >= s)
        if not ok.any():
            return 0.0
    return float(np.mean(ok))


def optimize_from_secciones(
    secciones: List[Dict[str, Any]],
    labels: Optional[List[str]],
    nota_actual: float,
    objetivo: float,
    *,
    beam_width: int = 64,
    max_nodes_per_level: int = 256,
    diversify_per_eval: int = 6,
    mc_samples: int = 20000,
    seed: Optional[int] = 123,
    course_key: str | None = None
) -> Dict[str, Any]:
    """
    Punto de entrada para la app:
    - Construye evals desde 'secciones' + 'labels' (normaliza historial y usa priors)
    - Corre beam + Monte Carlo
    - Devuelve dict listo para Jinja
    """
    # 1) Construir evaluaciones
    evals = build_evals_from_secciones(
        secciones, labels,
        default_min=50, final_min=40, default_step=5,
        course_key=course_key
    )

    if not evals:
        return {"baseline_prob": 0.0, "plans": [], "message": "No hay evaluaciones pendientes."}

    # 2) Poda de imposibilidad
    max_pos = nota_actual + sum(e.weight * e.s_max for e in evals)
    if max_pos + 1e-9 < objetivo:
        return {"baseline_prob": 0.0, "plans": [], "message": "Objetivo inalcanzable con los máximos actuales."}

    # 3) Beam
    tail_p = _precompute_tail_tables(evals)
    plans = _beam_search(evals, nota_actual, objetivo, tail_p,
                         beam_width=beam_width,
                         max_nodes_per_level=max_nodes_per_level,
                         diversify_per_eval=diversify_per_eval)

    # 4) Monte Carlo
    samples = _mc_samples(evals, N=mc_samples, seed=seed)
    baseline = _prob_objectivo_mc(nota_actual, objetivo, evals, samples)

    enriched = []
    for plan in plans:
        mc = _prob_plan_mc(plan, samples)
        details = []
        for e in evals:
            s = plan["targets"][e.eval_id]
            p_tail = tail_p[e.eval_id][s]
            contrib = e.weight * s
            details.append({
                "eval_id": e.eval_id, "name": e.name, "weight": round(e.weight, 4),
                "mu": round(e.mu, 2), "sigma": round(e.sigma, 2),
                "target": int(s), "p_tail": round(p_tail, 4),
                "contrib": round(contrib, 2)
            })
        enriched.append({
            "targets": plan["targets"],
            "sum_contrib": round(plan["sum_contrib"], 2),
            "prod_prob": round(plan["prod_prob"], 4),
            "mc_prob": round(mc, 4),
            "details": details
        })
    enriched.sort(key=lambda d: d["mc_prob"], reverse=True)

    return {"baseline_prob": round(baseline, 4), "plans": enriched}
