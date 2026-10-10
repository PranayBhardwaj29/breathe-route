"""projections.py - 20-year synthetic projections (growth, survival, impact, cost) per species."""
from __future__ import annotations
import numpy as np

YEARS = np.arange(0, 21)


def _f(v, default=0.0):
    try:
        x = float(v)
        return default if np.isnan(x) else x
    except (TypeError, ValueError):
        return default


def _fr(v, default=0.0):
    x = _f(v, default)
    return x / 100 if x > 1 else x


def tree_curves(row, pm25_mature_g: float) -> dict:
    """Per planted tree. `row` is one species row (dict-like); pm25_mature_g is local PM2.5 removal at maturity."""
    g = row.get
    canopy = np.maximum.accumulate(np.interp(
        YEARS, [0, 1, 3, 5, 10, 20],
        [0] + [_fr(g(f"canopy_frac_yr{k}")) for k in (1, 3, 5, 10, 20)]))
    s5 = _fr(g("survival_yr5")) or _fr(g("survival_yr10"), 0.8)
    s1 = _fr(g("survival_yr1")) or max(s5, 0.9)
    s10 = _fr(g("survival_yr10")) or s5
    s20 = max(0.0, s10 * (s10 / s5)) if s5 > 0 else s10
    surv = np.minimum.accumulate(np.interp(YEARS, [0, 1, 5, 10, 20], [1, s1, s5, s10, s20]))
    pm25 = pm25_mature_g * canopy * surv          # impact scales with canopy size and living trees
    shade = _f(g("crown_area_m2_mature")) * canopy * surv
    annual = np.zeros(len(YEARS))
    annual[0] = _f(g("sapling_cost_inr")) + _f(g("planting_cost_inr")) + _f(g("tree_guard_cost_inr"))
    annual[1] = _f(g("maint_cost_yr1_inr"))
    annual[2] = _f(g("maint_cost_yr2_inr"))
    annual[3:8] = _f(g("maint_cost_yr3_7_inr_per_yr"))
    annual[8:] = _f(g("maint_cost_yr8plus_inr_per_yr"))
    r = lambda a, d=2: [round(float(x), d) for x in a]
    return {"canopy": r(canopy * 100, 1), "survival": r(surv * 100, 1), "pm25": r(pm25), "shade": r(shade),
            "annual_cost": r(annual, 0), "cum_cost": r(np.cumsum(annual), 0)}


def build_projection(species_df, ranked_df, ranking_ids: list, counts: dict, names: dict, colors: dict) -> dict:
    """species_df indexed by species_id; ranked_df indexed by species_id (has pm25_removal_g_yr_mature_local)."""
    def curves(sid):
        return tree_curves(species_df.loc[sid].to_dict(), float(ranked_df.loc[sid, "pm25_removal_g_yr_mature_local"]))

    per_species = [{"species_id": s, "common_name": names[s], "color": colors[s], **curves(s)} for s in ranking_ids]
    tot = {k: np.zeros(len(YEARS)) for k in ("annual_cost", "pm25", "shade")}
    for sid, n in counts.items():
        c = curves(sid)
        for k in tot:
            tot[k] += n * np.array(c[k])
    return {"years": YEARS.tolist(), "species": per_species,
            "totals": {"annual_cost": [round(x) for x in tot["annual_cost"]],
                       "cum_cost": [round(x) for x in np.cumsum(tot["annual_cost"])],
                       "pm25_kg": [round(x / 1000, 2) for x in tot["pm25"]],
                       "pm25_cum_kg": [round(x / 1000, 2) for x in np.cumsum(tot["pm25"])],
                       "shade_m2": [round(x) for x in tot["shade"]]}}
