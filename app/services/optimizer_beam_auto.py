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
from app.services.sections import normalize_section_label


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
    """
    P(Y ≥ s) con Y ~ Beta(α,β) mapeada a 0..100 y calibración opcional.

    Importante: tratamos `s` como **nota entera** (0..100). Para evitar que 100 dé 0.0%
    siempre (por ser extremo en continuo), usamos un umbral tipo "bin discreto":
      P(Y ≥ s) ≈ P(Y > (s-0.5)/100)
    """
    # Umbral discreto (s entero). Para s=100 => 0.995 (da prob pequeña pero no cero).
    x = (float(s) - 0.5) / 100.0
    x = float(np.clip(x, 0.0, 1.0))
    p = float(_beta.sf(x, alpha, beta))  # survival fn
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
    model_key: str,
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
        label = normalize_section_label(label)

        mu0, s0 = get_eval_prior(model_key, label)
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
                course_key=model_key, eval_label=label
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
        # Metas especiales.
        # Regla: 100 se permite sobre todo en secciones "muy fáciles" o de bajo peso,
        # para evitar planes irreales donde Semestral/Parciales se van a 100.
        wants = [95]
        allow_100 = (e.weight <= 0.06) or (e.eval_label in {"Asistencia", "Portafolio"})
        if allow_100:
            wants.append(100)
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
    max_overshoot_points: Optional[float] = None,
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

    exam_like = {"Semestral", "Parciales", "Quices"}

    for level, e in enumerate(E):
        new: List[Tuple[float, float, Dict[str, int]]] = []
        # candidatos (añade 95/100 sin encajar si supergrid)
        cand = _select_candidates_boosted(e, pre_tail[e.eval_id], diversify, supergrid=supergrid, boost=boost)

        for sc, c, t in beam:
            for s in cand:
                sc2 = sc + e.weight * s
                # Si buscamos "mínimo esfuerzo", imponemos un tope duro al overshoot en puntos:
                # nota_final = nota_actual + sc2, req = objetivo - nota_actual => overshoot = sc2 - req
                if max_overshoot_points is not None and (sc2 - req) > float(max_overshoot_points) + 1e-9:
                    continue
                if not feasible(sc2, level + 1):
                    continue
                p_tail = _tail_value_for(e, s, pre_tail, ab_cal)
                cost = -math.log(max(1e-12, p_tail))
                # Penaliza metas extremas en evaluaciones "difíciles" para favorecer planes realistas
                # (sin impedir que existan planes ambiciosos cuando el objetivo lo exige).
                if e.eval_label in exam_like and s > 85:
                    # creciente suave: 86..100 => penalidad 0..~0.9
                    cost += 0.25 * ((s - 85) / 15.0) ** 2
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
            if max_overshoot_points is not None and (sc - req) > float(max_overshoot_points) + 1e-9:
                continue
            plans.append({"targets": t, "sum_contrib": sc, "sum_cost": c, "prod_prob": math.exp(-c)})
    plans.sort(key=lambda d: (-d["prod_prob"], d["sum_cost"]))
    return plans


# -------------------- MC: Beta con cópula Gaussiana --------------------
def _samples_beta_two_factor(
    evals: List[EvalSpec],
    N: int = 20000,
    seed: int = 123,
    rho_exam: float = 0.45,
    rho_work: float = 0.35,
) -> Dict[str, np.ndarray]:
    """
    Muestras correlacionadas con 2 factores latentes:
    - "examen": Semestral / Parciales / Quices
    - "trabajo": Laboratorios / Tareas / Proyectos / Portafolio / Asistencia / Otros

    Esto mantiene correlación positiva global, pero más fuerte dentro de cada grupo.
    """
    rho_exam = float(np.clip(rho_exam, 0.0, 0.95))
    rho_work = float(np.clip(rho_work, 0.0, 0.95))
    rng = np.random.default_rng(seed)
    Z_exam = rng.standard_normal(size=N).astype(np.float32)
    Z_work = rng.standard_normal(size=N).astype(np.float32)

    exam_types = {"Semestral", "Parciales", "Quices"}

    out: Dict[str, np.ndarray] = {}
    for e in evals:
        eps = rng.standard_normal(size=N).astype(np.float32)
        is_exam = (e.eval_label in exam_types)
        a = rho_exam if is_exam else 0.15
        b = 0.15 if is_exam else rho_work
        # asegura var residual >= 0
        resid = max(1e-9, 1.0 - a * a - b * b)
        latent = a * Z_exam + b * Z_work + np.sqrt(resid) * eps
        U = norm.cdf(latent)
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


def baseline_prob_only(
    *,
    secciones: List[Dict[str, Any]],
    labels: List[str],
    model_key: str,
    nota_actual: float,
    objetivo: float,
    mc_samples: int = 8000,
    seed: int = 123,
) -> Dict[str, Any]:
    """
    Calcula SOLO la probabilidad base de alcanzar el objetivo (sin generar planes).
    Útil para dashboards/listas donde queremos un cálculo rápido.
    """
    evals = build_evals_trust_with_priors(model_key, labels, secciones)
    if not evals:
        return {"ok": True, "baseline_prob": 1.0 if nota_actual >= objetivo else 0.0, "message": "No hay evaluaciones pendientes."}

    theoretical_max_pos = float(nota_actual) + sum(float(e.weight) * 100.0 for e in evals)
    if theoretical_max_pos + 1e-9 < float(objetivo):
        return {"ok": True, "baseline_prob": 0.0, "message": "Objetivo inalcanzable aún con máximos teóricos."}

    samples = _samples_beta_two_factor(evals, N=int(mc_samples), seed=int(seed))
    baseline = float(_prob_obj_mc(float(nota_actual), float(objetivo), evals, samples))
    return {"ok": True, "baseline_prob": round(baseline, 4), "message": None}

def _prob_plan_mc(plan: Dict[str, Any], samples: Dict[str, np.ndarray]) -> float:
    N = len(next(iter(samples.values())))
    ok = np.ones(N, dtype=bool)
    for eid, s in plan["targets"].items():
        ok &= (samples[eid] >= s)
        if not ok.any():
            return 0.0
    return float(np.mean(ok))


def difficulty_label(p: float) -> str:
    """
    Etiqueta simple de dificultad basada en probabilidad de cumplir el plan.
    (Umbrales ajustables; se puede calibrar con feedback de usuarios.)
    """
    try:
        p = float(p)
    except Exception:
        p = 0.0
    if p >= 0.80:
        return "Fácil"
    if p >= 0.60:
        return "Alcanzable"
    if p >= 0.40:
        return "Promedio"
    if p >= 0.20:
        return "Difícil"
    return "Legendario"


def evaluate_plan_auto(
    *,
    secciones: List[Dict[str, Any]],
    labels: List[str],
    model_key: str,
    nota_actual: float,
    objetivo: float,
    targets: Dict[str, int],
    mc_samples: int = 8000,
    seed: int = 123,
) -> Dict[str, Any]:
    """
    Recalcula métricas del plan cuando el usuario edita metas.
    Devuelve:
    - prob de cumplir plan (MC correlacionado)
    - nota final si cumple metas
    - bool llega_objetivo
    - dificultad
    - detalle por evaluación (eval_id, name, target, p_tail)
    """
    evals = build_evals_trust_with_priors(model_key, labels, secciones)
    if not evals:
        return {
            "ok": False,
            "message": "No hay evaluaciones pendientes.",
            "plan": None,
        }

    # Normaliza targets: solo evals existentes, clamp 0..100
    t_clean: Dict[str, int] = {}
    for e in evals:
        raw = targets.get(e.eval_id, None)
        if raw is None:
            # default conservador: usa mínimo del grid (permite UI partial updates sin romper)
            raw = e.s_min
        try:
            s = int(raw)
        except Exception:
            s = int(e.s_min)
        t_clean[e.eval_id] = int(max(0, min(100, s)))

    calibrators = {e.eval_label: get_calibrator(e.course_key, e.eval_label) for e in evals}
    details = []
    sum_contrib = 0.0
    for e in evals:
        s = t_clean[e.eval_id]
        sum_contrib += float(e.weight) * float(s)
        p_tail = _tail_prob_beta(s, e.alpha, e.beta, calibrator=calibrators.get(e.eval_label))
        details.append(
            {
                "eval_id": e.eval_id,
                "name": e.name,
                "target": int(s),
                "p_tail": round(float(p_tail), 4),
            }
        )

    nota_final_si_cumple = float(nota_actual) + float(sum_contrib)
    llega_objetivo = bool(nota_final_si_cumple + 1e-9 >= float(objetivo))

    samples = _samples_beta_two_factor(evals, N=int(mc_samples), seed=int(seed))
    plan_prob = float(_prob_plan_mc({"targets": t_clean}, samples))

    return {
        "ok": True,
        "plan": {
            "targets": t_clean,
            "sum_contrib": round(float(sum_contrib), 2),
            "nota_final_si_cumple": round(float(nota_final_si_cumple), 2),
            "llega_objetivo": llega_objetivo,
            "mc_prob": round(float(plan_prob), 4),
            "difficulty": difficulty_label(plan_prob),
            "details": details,
        },
    }

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
    model_key: str,
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
        model_key, labels, secciones,
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
    samples = _samples_beta_two_factor(evals, N=mc_samples, seed=seed)
    baseline = _prob_obj_mc(nota_actual, objetivo, evals, samples)

    # 5.5) Utilidades: enriquecer + "tighten" para mínimo esfuerzo
    def _enrich_from_targets(tg: Dict[str, int]) -> Dict[str, Any]:
        details = []
        sum_contrib = 0.0
        for e in evals:
            s = int(max(0, min(100, int(tg.get(e.eval_id, e.s_min)))))
            sum_contrib += float(e.weight) * float(s)
            cal = calibrators.get(e.eval_label)
            p_tail = _tail_prob_beta(s, e.alpha, e.beta, calibrator=cal)
            details.append({
                "eval_id": e.eval_id,
                "name": e.name,
                "eval_label": e.eval_label,
                "weight": round(e.weight, 4),
                "mu": round(e.mu, 2),
                "sigma": round(e.sigma, 2),
                "target": int(s),
                "p_tail": round(p_tail, 4),
                "contrib": round(e.weight * s, 2),
            })
        mc = _prob_plan_mc({"targets": tg}, samples) if tg else 1.0
        nota_final = float(nota_actual) + float(sum_contrib)
        return {
            "targets": {k: int(v) for k, v in tg.items()},
            "sum_contrib": round(float(sum_contrib), 2),
            "nota_final_si_cumple": round(float(nota_final), 2),
            "prod_prob": None,
            "mc_prob": round(float(mc), 4),
            "details": details,
        }

    def _tighten_targets(tg: Dict[str, int]) -> Tuple[Dict[str, int], float]:
        """
        Reduce metas todo lo posible manteniendo nota_final >= objetivo.
        Resultado queda lo más cerca posible del objetivo (mínimo esfuerzo).
        """
        t = {k: int(v) for k, v in (tg or {}).items()}
        # calcula total
        total = float(nota_actual)
        for e in evals:
            total += float(e.weight) * float(int(t.get(e.eval_id, e.s_min)))

        if total + 1e-9 < float(objetivo):
            return t, total

        # decrementos greedy: siempre elige el decremento que deja la menor sobrepasada >=0
        improved = True
        while improved:
            improved = False
            best_eid = None
            best_new_over = None
            best_w = None
            for e in evals:
                eid = e.eval_id
                cur = int(t.get(eid, e.s_min))
                if cur <= 0:
                    continue
                new_total = total - float(e.weight)
                if new_total + 1e-9 < float(objetivo):
                    continue
                new_over = float(new_total) - float(objetivo)
                if best_new_over is None or new_over < best_new_over - 1e-12:
                    best_new_over = new_over
                    best_eid = eid
                    best_w = float(e.weight)
            if best_eid is not None and best_w is not None:
                t[best_eid] = int(t.get(best_eid, 0)) - 1
                total -= best_w
                improved = True

        return t, total

    # Tolerancia solicitada: objetivo <= nota_final <= objetivo + 0.8 (puntos)
    tight_tol = 0.8

    # Un pase adicional de BEAM con tope duro de overshoot para encontrar una base buena.
    tight_plans = _beam_search(
        evals, nota_actual, objetivo, tail,
        beam_width=min(beam_width + 96, 256),
        max_nodes=min(max_nodes_per_level + 512, 1400),
        diversify=min(diversify_per_eval + 8, 20),
        overshoot_penalty=0.05,
        max_overshoot_points=tight_tol,
        boost=True,
        supergrid=True,
    )

    # 6) Enriquecer resultados y ordenar por MC
    enriched: List[Dict[str, Any]] = []
    for p in plans:
        mc = _prob_plan_mc(p, samples)
        nota_final_si_cumple = float(nota_actual) + float(p["sum_contrib"])
        details = []
        for e in evals:
            s = p["targets"][e.eval_id]
            # prob de cola coherente con lo que usó el beam (puede ser 95/100 fuera del grid)
            cal = calibrators.get(e.eval_label)
            p_tail = _tail_prob_beta(s, e.alpha, e.beta, calibrator=cal)
            details.append({
                "eval_id": e.eval_id,
                "name": e.name,
                "eval_label": e.eval_label,
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
            "nota_final_si_cumple": round(nota_final_si_cumple, 2),
            "prod_prob": round(p["prod_prob"], 4),
            "mc_prob": round(mc, 4),
            "details": details,
        })
    enriched.sort(key=lambda d: d["mc_prob"], reverse=True)

    def _overshoot_points(total: float) -> float:
        return max(0.0, float(total) - float(objetivo))

    # Construye candidatos para recomendado:
    # 1) toma planes tight (si existen), si no, toma los mejores planes generales
    base_candidates = list(tight_plans or []) or list(plans or [])
    base_candidates = base_candidates[:200]  # limita costo

    tightened_candidates: List[Dict[str, Any]] = []
    seen = set()
    for p in base_candidates:
        tg0 = dict(p.get("targets") or {})
        tg1, tot1 = _tighten_targets(tg0)
        # key para deduplicar
        key = tuple(sorted((k, int(v)) for k, v in tg1.items()))
        if key in seen:
            continue
        seen.add(key)
        enriched1 = _enrich_from_targets(tg1)
        enriched1["nota_final_si_cumple"] = round(float(tot1), 2)
        enriched1["recommended_tightened"] = True
        tightened_candidates.append(enriched1)

    # filtra por la ventana objetivo..objetivo+tight_tol
    within_window = [
        p for p in tightened_candidates
        if float(p.get("nota_final_si_cumple", 0.0)) + 1e-9 >= float(objetivo)
        and _overshoot_points(float(p.get("nota_final_si_cumple", 0.0))) <= float(tight_tol) + 1e-9
    ]

    # Selección:
    # - primero el más cercano al objetivo (mínimo esfuerzo)
    # - luego mayor prob (mc_prob)
    # - luego menor pico de targets
    def _max_target(p: Dict[str, Any]) -> int:
        ts = [int(d.get("target", 0)) for d in (p.get("details") or [])]
        return max(ts) if ts else 0

    def _pick_best(pool: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        if not pool:
            return None
        return sorted(
            pool,
            key=lambda p: (
                _overshoot_points(float(p.get("nota_final_si_cumple", 0.0))),
                -float(p.get("mc_prob", 0.0)),
                _max_target(p),
            ),
        )[0]

    recommended_plan = _pick_best(within_window) or _pick_best(tightened_candidates) or (enriched[0] if enriched else None)

    # 7) Planes destacados (3 más eficientes)
    def _plan_difficulty(p: Dict[str, Any]) -> Tuple[float, float]:
        # menor es "más fácil": (max_target, mean_target)
        ts = [int(d.get("target", 0)) for d in (p.get("details") or [])]
        if not ts:
            return (0.0, 0.0)
        return (float(max(ts)), float(sum(ts) / len(ts)))

    def _is_reasonable(p: Dict[str, Any], *, min_tail: float) -> bool:
        # Evita planes donde alguna meta tiene prob prácticamente cero.
        for d in (p.get("details") or []):
            try:
                if float(d.get("p_tail", 0.0)) < float(min_tail):
                    return False
            except Exception:
                return False
        return True

    # Primero intentamos planes "razonables"; si no alcanza para 3, relajamos umbral.
    candidates = [p for p in enriched if _is_reasonable(p, min_tail=0.02)]
    if len(candidates) < 3:
        candidates = [p for p in enriched if _is_reasonable(p, min_tail=0.01)]
    if len(candidates) < 3:
        candidates = enriched

    # Highlighted: para UI antigua dejamos 3, pero si existe recommended_plan lo ponemos primero.
    highlighted = sorted(
        candidates,
        key=lambda p: (-float(p.get("mc_prob", 0.0)),) + _plan_difficulty(p),
    )[:3]
    if recommended_plan:
        # evita duplicado
        highlighted = [recommended_plan] + [p for p in highlighted if p is not recommended_plan][:2]
    for i, p in enumerate(highlighted):
        p["style"] = "Destacado"
        p["rank"] = i + 1

    # 8) Categorías (1 plan por categoría, expandible en UI)
    pool = enriched[:50]  # suficiente diversidad sin costo grande

    def _avg_target_for_label(p: Dict[str, Any], lbl: str) -> float:
        ts = [int(d["target"]) for d in (p.get("details") or []) if d.get("eval_label") == lbl]
        return float(sum(ts) / len(ts)) if ts else float("-inf")

    def _pick_best(plans: List[Dict[str, Any]], score_fn):
        best = None
        best_score = None
        for p in plans:
            sc = score_fn(p)
            if best is None or sc > best_score:
                best, best_score = p, sc
        return best

    # umbral suave para evitar categorías con planes imposibles
    def _ok(p: Dict[str, Any]) -> bool:
        return float(p.get("mc_prob", 0.0)) >= 0.15

    cat_sem = _pick_best([p for p in pool if _ok(p)], lambda p: (_avg_target_for_label(p, "Semestral"), p["mc_prob"]))
    cat_par = _pick_best([p for p in pool if _ok(p)], lambda p: (_avg_target_for_label(p, "Parciales"), p["mc_prob"]))
    cat_lab = _pick_best([p for p in pool if _ok(p)], lambda p: (_avg_target_for_label(p, "Laboratorios"), p["mc_prob"]))

    def _balance_score(p: Dict[str, Any]) -> float:
        ts = [int(d.get("target", 0)) for d in (p.get("details") or [])]
        if not ts:
            return float("-inf")
        mean = sum(ts) / len(ts)
        var = sum((t - mean) ** 2 for t in ts) / max(1, len(ts))
        max_t = max(ts)
        # mayor score = más balanceado y moderado, con buena prob
        return float(p.get("mc_prob", 0.0)) - 0.0025 * float(var) - 0.002 * float(max_t)

    cat_bal = _pick_best(pool, _balance_score)

    category_plans = []
    if cat_sem:
        category_plans.append({"key": "semestral_alto", "title": "Plan con nota alta en semestral", "plan": cat_sem})
    if cat_par:
        category_plans.append({"key": "parciales_alto", "title": "Plan con nota alta en parciales", "plan": cat_par})
    if cat_lab:
        category_plans.append({"key": "labs_alto", "title": "Plan con nota alta en laboratorios", "plan": cat_lab})
    if cat_bal:
        category_plans.append({"key": "balanceado", "title": "Plan balanceado sin picos", "plan": cat_bal})

    # 9) Diversidad (para seguir ofreciendo alternativas si el usuario explora)
    diverse = _diversity_filter(enriched, evals, min_l1=18, top=5)
    out_plans: List[Dict[str, Any]] = []
    for p, tag, _ in diverse:
        q = dict(p)
        q["style"] = tag
        out_plans.append(q)

    return {
        "baseline_prob": round(baseline, 4),
        "highlighted_plans": highlighted,
        "category_plans": category_plans,
        "plans": out_plans,  # compat/debug
        "recommended_plan": recommended_plan,
        "recommended_tight": bool(within_window),
        "recommended_tolerance": tight_tol,
    }
