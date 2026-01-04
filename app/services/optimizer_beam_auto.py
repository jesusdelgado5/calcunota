# app/services/optimizer_beam_auto.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Tuple
import math
import numpy as np
from scipy.stats import beta as _beta, norm

from app.services.priors import get_eval_prior
from app.services.calibration import get_calibrator
from app.services.grades import normalize_nota


# ----------------------------- Datos -----------------------------
@dataclass
class EvalSpec:
    eval_id: str
    name: str
    weight: float   # 0..1 (porcentaje_seccion/num_notas)
    mu: float       # 0..100
    sigma: float    # >0
    alpha: float    # Beta α (sobre [0,1])
    beta: float     # Beta β (sobre [0,1])
    s_min: int      # 0..100
    s_max: int
    s_step: int
    course_key: str
    eval_label: str  # nombre visible de la sección (para priors/calib)

    @property
    def grid(self) -> List[int]:
        return list(range(self.s_min, self.s_max + 1, self.s_step))


# -------------------- Beta (posterior heurístico) --------------------
def _clip01(x: float) -> float:
    return float(np.clip(x, 1e-4, 1.0 - 1e-4))


def _conc_from_mu_sigma(mu01: float, sigma01: float) -> float:
    """
    Convierte (mu, sigma) en concentración t=(α+β).

    Nota: var_beta = m(1-m)/(t+1) => t = m(1-m)/v - 1
    """
    m = _clip01(mu01)
    v = float(sigma01 ** 2)
    # var máxima de una variable en [0,1] es m(1-m); no puede excederla.
    vmax = float(m * (1.0 - m) - 1e-9)
    v = float(np.clip(v, 1e-6, vmax))
    t = m * (1.0 - m) / v - 1.0
    return float(np.clip(t, 2.0, 500.0))


def _beta_from_mean_conc(mu01: float, t: float) -> Tuple[float, float]:
    m = _clip01(mu01)
    t = float(np.clip(t, 2.0, 500.0))
    return float(m * t), float((1.0 - m) * t)


def _posterior_beta_from_scores(
    scores_norm: List[float],
    *,
    mu_prior: float,
    sigma_prior: float,
    prior_strength: float = 1.0,
) -> Tuple[float, float, float, float]:
    """
    Estima Beta(α,β) en [0,1] para el alumno en una sección, mezclando:
    - Prior (μ_prior, σ_prior) -> (m0, t0)
    - Observaciones del alumno (mean/var) -> (m1, t1) si hay suficiente data

    Devuelve: (alpha, beta, mu_0_100, sigma_0_100)
    """
    xs = [float(x) for x in (scores_norm or []) if x is not None]
    n = len(xs)

    # Prior como Beta(m0, t0)
    m0 = _clip01(float(mu_prior) / 100.0)
    t0 = _conc_from_mu_sigma(m0, float(sigma_prior) / 100.0) * float(max(0.25, prior_strength))
    t0 = float(np.clip(t0, 2.0, 500.0))

    if n == 0:
        a0, b0 = _beta_from_mean_conc(m0, t0)
        mu = 100.0 * m0
        sigma = 100.0 * math.sqrt(m0 * (1.0 - m0) / (t0 + 1.0))
        return a0, b0, float(mu), float(sigma)

    # Datos del alumno
    m1 = _clip01(float(np.mean(xs)) / 100.0)
    t_data: float
    if n >= 5:
        # Si hay suficiente data, estimamos concentración desde var empírica
        v1 = float(np.var(xs, ddof=1)) / (100.0 ** 2)
        # si v1 es demasiado chico/ruidoso, _conc_ lo estabiliza con clamps
        t1 = _conc_from_mu_sigma(m1, math.sqrt(max(1e-9, v1)))
        # cap para no sobre-confiarnos con muestras chicas
        t_data = float(np.clip(t1, 2.0, 200.0))
    else:
        # Con pocas observaciones, usamos un peso conservador proporcional a n
        t_data = float(np.clip(2.0 * n, 2.0, 20.0))

    t_post = float(np.clip(t0 + t_data, 2.0, 500.0))
    m_post = _clip01((t0 * m0 + t_data * m1) / (t0 + t_data))
    a, b = _beta_from_mean_conc(m_post, t_post)

    mu = 100.0 * m_post
    sigma = 100.0 * math.sqrt(m_post * (1.0 - m_post) / (t_post + 1.0))
    return float(a), float(b), float(mu), float(sigma)


def _tail_prob_beta(s: int, alpha: float, beta: float, calibrator=None) -> float:
    """P(Y ≥ s) con Y ~ Beta(α,β) mapeada a 0..100 y calibración opcional."""
    p = float(_beta.sf(s / 100.0, alpha, beta))  # survival fn
    if calibrator is not None:
        p = calibrator(p)
    return max(1e-8, min(1.0, p))


# -------------------- Grid adaptativo por μ,σ --------------------
def _adaptive_grid_params(
    mu: float, sigma: float, is_final_like: bool,
    default_min: int, final_min: int
) -> Tuple[int, int, int]:
    base_min = final_min if is_final_like else default_min
    k1, k2 = (0.6, 1.2) if is_final_like else (0.8, 1.0)
    s_min = int(max(base_min, math.floor(mu - k1 * sigma)))
    s_max = int(min(100, math.ceil(mu + k2 * sigma)))
    if s_max <= s_min:
        s_min, s_max = max(base_min, int(mu - 0.5 * sigma)), min(100, int(mu + 0.5 * sigma))
    if sigma <= 8:
        step = 2
    elif sigma <= 15:
        step = 3
    else:
        step = 5
    return s_min, s_max, step


# -------------------- Construcción de evaluaciones --------------------
def build_evals_trust_with_priors(
    course_key: str,
    labels: List[str],
    secciones: List[Dict[str, Any]],
    default_min: int = 50,
    final_min: int = 40,
    default_step: int = 5
) -> List[EvalSpec]:
    evals: List[EvalSpec] = []

    for i, sec in enumerate(secciones):
        W = float(sec.get("porcentaje", 0.0))  # fracción 0..1
        m = int(sec.get("num_notas", 0))

        notas_raw = sec.get("notas_obtenidas") or []
        notas_norm = [normalize_nota(n) for n in notas_raw]

        k = len(notas_norm)
        pend = max(0, m - k)
        if m <= 0 or pend <= 0 or W <= 0:
            continue

        w_item = W / float(m)
        label = labels[i] if i < len(labels) else f"Sección {i+1}"

        mu0, s0 = get_eval_prior(course_key, label)
        a, b, mu_hat, sigma_hat = _posterior_beta_from_scores(
            notas_norm, mu_prior=mu0, sigma_prior=s0, prior_strength=1.0
        )

        is_final_like = any(x in label.lower() for x in ["final", "semestral", "examen final"])
        gmin, gmax, gstep = _adaptive_grid_params(mu_hat, sigma_hat, is_final_like, default_min, final_min)

        for j in range(k, m):
            idx = j + 1
            evals.append(EvalSpec(
                eval_id=f"sec{i+1}_nota{idx}",
                name=f"{label} - Nota {idx}",
                weight=w_item, mu=mu_hat, sigma=sigma_hat,
                alpha=a, beta=b,
                s_min=gmin, s_max=gmax, s_step=gstep,
                course_key=course_key, eval_label=label
            ))

    return evals


# -------------------- Colas calibradas por sección --------------------
def _precompute_tail_beta(evals: List[EvalSpec]) -> Dict[str, Dict[int, float]]:
    """eid -> {s: P(Y>=s)} usando Beta(α,β) + calibración por sección."""
    out: Dict[str, Dict[int, float]] = {}
    calibrators = {e.eval_label: get_calibrator(e.course_key, e.eval_label) for e in evals}
    for e in evals:
        cal = calibrators.get(e.eval_label)
        out[e.eval_id] = {s: _tail_prob_beta(s, e.alpha, e.beta, calibrator=cal) for s in e.grid}
    return out


# --- util: cola puntual (incluye 95/100 aunque no estén en el grid) ---
def _tail_value_for(e: EvalSpec, s: int, pre_tail: Dict[str, Dict[int, float]],
                    ab_cal: Dict[str, Tuple[float, float, Any]]) -> float:
    m = pre_tail.get(e.eval_id) or {}
    if s in m:
        return m[s]
    a, b, cal = ab_cal[e.eval_id]
    return _tail_prob_beta(s, a, b, calibrator=cal)


# -------------------- Selección de candidatos --------------------
def _select_candidates(e: EvalSpec, tail_map: Dict[int, float], diversify: int) -> List[int]:
    # 1) top por costo/punto
    def cpp(s: int) -> float:
        p = max(1e-9, tail_map[s])
        return (-math.log(p)) / max(1e-9, e.weight * s)

    grid_sorted = sorted(e.grid, key=cpp)

    # 2) cuantiles de cola
    target_ps = [0.9, 0.75, 0.6, 0.5, 0.4, 0.3, 0.2]
    by_quantiles: List[int] = []
    for p in target_ps:
        best_s = None
        for s in sorted(e.grid):
            if tail_map[s] >= p:
                best_s = s
                break
        if best_s is not None:
            by_quantiles.append(best_s)

    pool = [grid_sorted[i] for i in range(min(diversify, len(grid_sorted)))] \
         + by_quantiles + [min(e.grid), max(e.grid)]

    out = list(dict.fromkeys(pool))
    return out[: max(diversify + 2, len(target_ps) + 2)]


def _select_candidates_boosted(e: EvalSpec, tail_map: Dict[int, float], diversify: int, *,
                               supergrid: bool, boost: bool) -> List[int]:
    """
    Si 'supergrid' es True, no encajamos 95/100 al grid: los dejamos pasar
    como metas explícitas (y su prob. se calcula on-the-fly).
    """
    base = _select_candidates(e, tail_map, diversify)

    if boost or supergrid:
        wants = [95, 100]
        if supergrid:
            # dejamos 95/100 “tal cual”
            base.extend(wants)
        else:
            # encajar al grid hacia arriba si no existen
            gset = set(e.grid)
            for s in wants:
                if s in gset:
                    base.append(s)
                else:
                    cand = [x for x in e.grid if x >= s]
                    base.append(cand[0] if cand else max(e.grid))
        base = list(dict.fromkeys(base))

    return base


# -------------------- Beam Search flexible --------------------
def _beam_search(
    evals: List[EvalSpec],
    nota_actual: float,
    objetivo: float,
    pre_tail: Dict[str, Dict[int, float]],
    *,
    beam_width: int = 64,
    max_nodes: int = 256,
    diversify: int = 8,
    overshoot_penalty: float = 0.25,
    jitter: float = 1e-4,
    boost: bool = False,
    supergrid: bool = False
) -> List[Dict[str, Any]]:
    if objetivo <= nota_actual:
        return [{"targets": {}, "sum_contrib": 0.0, "sum_cost": 0.0, "prod_prob": 1.0}]

    req = objetivo - nota_actual
    E = sorted(evals, key=lambda e: e.weight, reverse=True)

    # Prepara (α,β, calibrator) por eval para colas on-the-fly
    # (se consulta una sola vez por request; get_calibrator ya es robusto si la DB no está lista)
    calibrators = {e.eval_label: get_calibrator(e.course_key, e.eval_label) for e in E}
    ab_cal = {e.eval_id: (e.alpha, e.beta, calibrators.get(e.eval_label)) for e in E}

    beam: List[Tuple[float, float, Dict[str, int]]] = [(0.0, 0.0, {})]

    # Poda por máximos (si supergrid, el máximo es 100)
    max_rem = [0.0] * (len(E) + 1)
    for i in range(len(E) - 1, -1, -1):
        max_s = 100.0 if supergrid else max(E[i].grid)
        max_rem[i] = max_rem[i + 1] + E[i].weight * max_s

    def feasible(sc: float, level: int) -> bool:
        return (sc + max_rem[level]) + 1e-9 >= req

    rng = np.random.default_rng(12345)

    for level, e in enumerate(E):
        new: List[Tuple[float, float, Dict[str, int]]] = []
        # candidatos (añade 95/100 sin encajar si supergrid)
        cand = _select_candidates_boosted(e, pre_tail[e.eval_id], diversify, supergrid=supergrid, boost=boost)

        for sc, c, t in beam:
            for s in cand:
                sc2 = sc + e.weight * s
                if not feasible(sc2, level + 1):
                    continue
                p_tail = _tail_value_for(e, s, pre_tail, ab_cal)
                cost = -math.log(max(1e-12, p_tail))
                if overshoot_penalty > 0:
                    over = max(0.0, sc2 - req)
                    if over > 0:
                        cost *= (1.0 + overshoot_penalty * over / (sc2 + 1e-9))
                new.append((sc2, c + cost, {**t, e.eval_id: s}))

        if not new:
            break

        def rank_key(n: Tuple[float, float, Dict[str, int]]):
            sc2, c2, _ = n
            gap = max(0.0, req - sc2)
            over = max(0.0, sc2 - req)
            j = rng.uniform(-jitter, jitter)
            return (gap, c2 + overshoot_penalty * over + j, -sc2)

        new.sort(key=rank_key)
        new = new[:max_nodes]
        beam = new[:beam_width]

    plans: List[Dict[str, Any]] = []
    for sc, c, t in beam:
        if len(t) == len(E) and sc + 1e-9 >= req:
            plans.append({"targets": t, "sum_contrib": sc, "sum_cost": c, "prod_prob": math.exp(-c)})
    plans.sort(key=lambda d: (-d["prod_prob"], d["sum_cost"]))
    return plans


# -------------------- MC: Beta con cópula Gaussiana --------------------
def _samples_beta_copula(evals: List[EvalSpec], N: int = 20000, seed: int = 123, rho: float = 0.35) -> Dict[str, np.ndarray]:
    """Muestras correlacionadas: mismo Z compartido para todas las evals."""
    rho = float(np.clip(rho, 0.0, 0.95))
    rng = np.random.default_rng(seed)
    Z = rng.standard_normal(size=N).astype(np.float32)  # factor común

    out: Dict[str, np.ndarray] = {}
    for e in evals:
        eps = rng.standard_normal(size=N).astype(np.float32)
        latent = rho * Z + np.sqrt(max(1e-9, 1 - rho**2)) * eps
        U = norm.cdf(latent)  # vectorizado
        U = np.clip(U, 1e-6, 1 - 1e-6)
        Y = _beta.ppf(U, e.alpha, e.beta).astype(np.float32) * 100.0
        out[e.eval_id] = np.clip(Y, 0.0, 100.0)
    return out


def _prob_obj_mc(nota_actual: float, objetivo: float, evals: List[EvalSpec], samples: Dict[str, np.ndarray]) -> float:
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


# -------------------- Diversidad + etiquetas --------------------
def _diversity_filter(plans: List[Dict[str, Any]], evals: List[EvalSpec], *, min_l1: int = 18, top: int = 5):
    selected: List[Dict[str, Any]] = []
    vecs: List[List[int]] = []

    for p in plans:
        vec = [p["targets"][e.eval_id] for e in evals]
        if not vecs or all(sum(abs(a - b) for a, b in zip(vec, v)) >= min_l1 for v in vecs):
            selected.append(p)
            vecs.append(vec)
        if len(selected) >= top:
            break

    labeled = []
    for i, p in enumerate(selected):
        prob = p.get("mc_prob", p.get("prod_prob", 0.0))
        if i == 0:
            tag = "Conservador"
        elif i == 1:
            tag = "Balanceado"
        else:
            tag = "Ambicioso"
        labeled.append((p, tag, prob))
    return labeled


# -------------------- Orquestador --------------------
def optimize_auto_backend(
    secciones: List[Dict[str, Any]],
    labels: List[str],
    course_key: str,
    nota_actual: float,
    objetivo: float,
    *,
    beam_width: int = 64,
    max_nodes_per_level: int = 256,
    diversify_per_eval: int = 6,
    mc_samples: int = 20000,
    seed: int = 123,
    default_min: int = 50,
    final_min: int = 40,
    default_step: int = 5
) -> Dict[str, Any]:
    evals = build_evals_trust_with_priors(
        course_key, labels, secciones,
        default_min=default_min, final_min=final_min, default_step=default_step
    )
    if not evals:
        return {"baseline_prob": 0.0, "plans": [], "message": "No hay evaluaciones pendientes."}

    # 1) Imposibilidad teórica (usa 100, no el grid)
    theoretical_max_pos = nota_actual + sum(e.weight * 100.0 for e in evals)
    if theoretical_max_pos + 1e-9 < objetivo:
        return {"baseline_prob": 0.0, "plans": [], "message": "Objetivo inalcanzable aún con máximos teóricos."}

    # 2) Colas calibradas precomputadas (solo grid)
    #    Importante: evitar consultas repetidas a DB durante el cálculo.
    calibrators = {e.eval_label: get_calibrator(e.course_key, e.eval_label) for e in evals}
    tail: Dict[str, Dict[int, float]] = {}
    for e in evals:
        cal = calibrators.get(e.eval_label)
        tail[e.eval_id] = {s: _tail_prob_beta(s, e.alpha, e.beta, calibrator=cal) for s in e.grid}

    # 3) BEAM — Pase 1 (realista, sin booster ni supergrid)
    plans = _beam_search(
        evals, nota_actual, objetivo, tail,
        beam_width=beam_width,
        max_nodes=max_nodes_per_level,
        diversify=diversify_per_eval,
        overshoot_penalty=0.25,
        boost=False,
        supergrid=False
    )

    # 4) Si no encontró nada pero teóricamente es posible, o si el promedio
    #    restante requerido supera el máximo del grid → Pase 2 con supergrid.
    remaining_w = sum(e.weight for e in evals)
    req_avg = (max(0.0, objetivo - nota_actual) / remaining_w) if remaining_w > 1e-9 else 100.0
    max_grid_avg = np.average([max(e.grid) for e in evals], weights=[e.weight for e in evals]) if evals else 0.0

    need_supergrid = (req_avg > max_grid_avg + 1e-6)
    if (not plans) and (theoretical_max_pos + 1e-9 >= objetivo or need_supergrid):
        plans = _beam_search(
            evals, nota_actual, objetivo, tail,
            beam_width=min(beam_width + 32, 160),
            max_nodes=min(max_nodes_per_level + 256, 768),
            diversify=min(diversify_per_eval + 3, 14),
            overshoot_penalty=0.22,   # ligeramente menor para no castigar metas altas necesarias
            boost=True,
            supergrid=True           # ⬅ clave: permite 95/100 reales y poda con 100
        )

    # 5) Monte Carlo correlacionado
    rho = 0.35
    samples = _samples_beta_copula(evals, N=mc_samples, seed=seed, rho=rho)
    baseline = _prob_obj_mc(nota_actual, objetivo, evals, samples)

    # 6) Enriquecer resultados y ordenar por MC
    enriched: List[Dict[str, Any]] = []
    for p in plans:
        mc = _prob_plan_mc(p, samples)
        details = []
        for e in evals:
            s = p["targets"][e.eval_id]
            # prob de cola coherente con lo que usó el beam (puede ser 95/100 fuera del grid)
            cal = calibrators.get(e.eval_label)
            p_tail = _tail_prob_beta(s, e.alpha, e.beta, calibrator=cal)
            details.append({
                "eval_id": e.eval_id,
                "name": e.name,
                "weight": round(e.weight, 4),
                "mu": round(e.mu, 2),
                "sigma": round(e.sigma, 2),
                "target": int(s),
                "p_tail": round(p_tail, 4),
                "contrib": round(e.weight * s, 2),
            })
        enriched.append({
            "targets": p["targets"],
            "sum_contrib": round(p["sum_contrib"], 2),
            "prod_prob": round(p["prod_prob"], 4),
            "mc_prob": round(mc, 4),
            "details": details,
        })
    enriched.sort(key=lambda d: d["mc_prob"], reverse=True)

    # 7) Diversidad y etiquetas
    diverse = _diversity_filter(enriched, evals, min_l1=18, top=5)
    out_plans: List[Dict[str, Any]] = []
    for p, tag, _ in diverse:
        q = dict(p)
        q["style"] = tag
        out_plans.append(q)

    return {"baseline_prob": round(baseline, 4), "plans": out_plans}
