"""
tree_recommender.py
===================
Recommendation engine: location -> baseline environment -> best trees -> per-patch planting plan.

Folder layout expected (DATA_DIR defaults to ./data):

    data/locations.csv                 location_id, name, lat, lon              (the 3-4 prototype sites)
    data/environment_conditions.csv    location_id, time, pm10, pm2_5, ...      (all columns you listed)
    data/tree_species.csv              species_id, common_name, ...             (all columns you listed)
    data/planting_patches.csv          patch_id, lat, lon, area_m2, ...         (+ optional location_id)
    data/geocode_cache.csv             (auto-created; caches geocoding results)

Usage:
    from tree_recommender import RecommendationEngine
    engine = RecommendationEngine("data")
    result = engine.recommend("Anand Lok, New Delhi")         # or engine.recommend(lat=28.57, lon=77.22)
    result.to_dict()      # JSON for your API
    result.to_geojson()   # FeatureCollection for the map

CLI:  python tree_recommender.py "Anand Lok, New Delhi" --data data
"""
from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------------------
FILES = {
    "locations": "locations.csv",
    "environment": "environment_conditions.csv",
    "species": "tree_species.csv",
    "patches": "planting_patches.csv",
    "geocode_cache": "geocode_cache.csv",
}

# Seasons (Delhi-style). Tree leaf-on data only has winter (Nov-Feb) vs Mar-Oct.
SEASONS = {"winter": [11, 12, 1, 2], "summer": [3, 4, 5, 6], "monsoon": [7, 8, 9], "post_monsoon": [10]}
MONTH_TO_SEASON = {m: s for s, ms in SEASONS.items() for m in ms}

# Reference limits (approx. Indian NAAQS 24h values, ug/m3). Tune freely.
LIMITS = {"pm2_5": 60, "pm10": 100, "nitrogen_dioxide": 80, "sulphur_dioxide": 80, "ozone": 100,
          "carbon_monoxide": 2000}
HEAT_APPARENT_C = 35.0

DEFAULT_WEIGHTS = {"benefit": 0.40, "resilience": 0.25, "local_fit": 0.15, "water": 0.10, "cost": 0.10,
                   "bvoc_penalty": 0.15}

ENV_REQUIRED = ["location_id", "time", "pm2_5", "pm10", "nitrogen_dioxide", "ozone", "apparent_temperature",
                "temperature_2m", "relative_humidity_2m", "precipitation", "vapour_pressure_deficit"]
SPECIES_REQUIRED = [
    "species_id", "common_name", "scientific_name", "leaf_on_frac_winter_nov_feb", "leaf_on_frac_mar_oct",
    "leaf_on_frac_annual", "canopy_frac_yr5", "canopy_frac_yr10", "pm_capture_index", "pollution_tolerance_index",
    "resuspension_frac", "pm25_removal_g_yr_mature_at_100ugm3", "pm10_removal_g_yr_mature_at_200ugm3",
    "bvoc_penalty_index", "air_cooling_c_scenario", "mrt_reduction_c_scenario", "summer_shade_effectiveness",
    "surface_temp_reduction_c_under_canopy", "irrigation_L_per_yr_yr1_3", "irrigation_L_per_yr_yr4plus",
    "drought_tolerance", "heat_tolerance", "waterlogging_tolerance", "root_damage_risk", "native_delhi_list",
    "local_suitability_score", "suitable_verge", "suitable_park_edge", "suitable_institutional", "suitable_median",
    "survival_yr10", "total_cost_7yr_inr", "planting_area_per_tree_m2", "min_site_width_m", "spacing_m",
    "mature_crown_diameter_m", "crown_area_m2_mature",
]
PATCH_REQUIRED = ["patch_id", "lat", "lon", "area_m2", "site_type"]  # others optional

SITE_KEYWORDS = {
    "suitable_median": ["median", "divider"],
    "suitable_verge": ["verge", "road", "street", "footpath", "roadside", "sidewalk"],
    "suitable_park_edge": ["park", "garden", "green", "playground"],
    "suitable_institutional": ["institution", "school", "campus", "hospital", "college", "university", "office"],
}
ORDINAL = {"very low": 0.0, "low": 0.25, "medium": 0.5, "moderate": 0.5, "med": 0.5, "high": 0.75,
           "very high": 1.0, "poor": 0.1, "fair": 0.4, "good": 0.75, "excellent": 1.0}


class DataError(Exception):
    pass


class OutOfCoverageError(Exception):
    pass


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
def haversine_km(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    a = np.sin((p2 - p1) / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(np.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * np.arcsin(np.sqrt(a))


def _minmax(s) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    lo, hi = s.min(), s.max()
    if not np.isfinite(lo) or hi - lo < 1e-12:
        return pd.Series(0.5, index=s.index)
    return ((s - lo) / (hi - lo)).fillna(0.5)


def _unit(s) -> pd.Series:
    """Ordinal text (Low/Medium/High) or numeric of any scale -> 0..1."""
    s = pd.Series(s)
    num = pd.to_numeric(s, errors="coerce")
    txt = s.astype(str).str.strip().str.lower().map(ORDINAL)
    if txt.notna().sum() > num.notna().sum():
        return txt.fillna(0.5)
    if num.notna().any() and num.min() >= 0 and num.max() <= 1:
        return num.fillna(0.5)
    return _minmax(num)


def _frac(s) -> pd.Series:
    """Fraction stored as 0-1 or 0-100 -> 0-1."""
    num = pd.to_numeric(pd.Series(s), errors="coerce")
    if num.max() > 1.0:
        num = num / 100.0
    return num.clip(0, 1).fillna(num.median() if num.notna().any() else 0.5)


def _bool(s) -> pd.Series:
    s = pd.Series(s)
    txt = s.astype(str).str.strip().str.lower().isin({"1", "true", "yes", "y", "t", "1.0"})
    num = pd.to_numeric(s, errors="coerce").fillna(0) > 0
    return txt | num


def _clip01(x):
    return float(np.clip(x, 0.0, 1.0))


def _clean(o):
    """Make anything JSON-safe (numpy types, NaN -> None)."""
    if isinstance(o, dict):
        return {str(k): _clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if (math.isnan(o) or math.isinf(o)) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, pd.Timestamp):
        return o.isoformat()
    return o


def _read_csv(path: Path, required: list[str], label: str, **kw) -> pd.DataFrame:
    if not path.exists():
        raise DataError(f"Missing data file: {path}  ({label})")
    df = pd.read_csv(path, **kw)
    df.columns = [c.strip() for c in df.columns]
    # tolerate unit suffixes like "pm2_5 (μg/m³)" -> "pm2_5"
    df.columns = [c.split(" (")[0].strip() for c in df.columns]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise DataError(f"{path.name}: missing required columns: {missing}")
    return df


# --------------------------------------------------------------------------------------
# Geocoding
# --------------------------------------------------------------------------------------
class Geocoder:
    """Nominatim (OpenStreetMap) with a CSV cache and local location name matching."""

    def __init__(self, cache_path: Path, user_agent="tree-recommender-breathe-route", country="in", locations_df=None):
        self.cache_path, self.user_agent, self.country = cache_path, user_agent, country
        self.cache = {}
        self.locations_df = locations_df
        if cache_path.exists():
            try:
                for r in pd.read_csv(cache_path).itertuples():
                    self.cache[str(r.query).lower().strip()] = (float(r.lat), float(r.lon), str(r.display_name))
            except Exception:
                pass

    def geocode(self, query: str):
        key = query.strip().lower()
        if key in self.cache:
            return self.cache[key]

        # 1. Check known study locations first (case-insensitive substring/equality)
        if self.locations_df is not None:
            for _, loc in self.locations_df.iterrows():
                loc_name = str(loc["name"]).strip().lower()
                if key == loc_name or key in loc_name or loc_name in key:
                    res = (float(loc["lat"]), float(loc["lon"]), str(loc["name"]))
                    self.cache[key] = res
                    return res

        # 2. Try Nominatim with standard urllib/requests
        import urllib.request
        import urllib.parse
        params = urllib.parse.urlencode({"q": query, "format": "json", "limit": "1", "countrycodes": self.country})
        url = f"https://nominatim.openstreetmap.org/search?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": self.user_agent})
        try:
            with urllib.request.urlopen(req, timeout=8) as response:
                hits = json.loads(response.read().decode("utf-8"))
                if hits:
                    out = (float(hits[0]["lat"]), float(hits[0]["lon"]), hits[0].get("display_name", query))
                    self.cache[key] = out
                    try:
                        pd.DataFrame([{"query": k, "lat": v[0], "lon": v[1], "display_name": v[2]}
                                      for k, v in self.cache.items()]).to_csv(self.cache_path, index=False)
                    except Exception:
                        pass
                    return out
        except Exception as e:
            print(f"[tree_recommender] Nominatim geocode error for '{query}': {e}")

        raise OutOfCoverageError(f"Could not geocode '{query}'. Please specify coordinates (lat, lon) or choose a Delhi study site.")



class AmazonLocationGeocoder:
    """Optional: Amazon Location Service (Places v2). Verify the API shape against your boto3 version."""

    def __init__(self, region="ap-south-1", bias_lon=77.2, bias_lat=28.6):
        import boto3
        self.client = boto3.client("geo-places", region_name=region)
        self.bias = [bias_lon, bias_lat]

    def geocode(self, query: str):
        r = self.client.search_text(QueryText=query, BiasPosition=self.bias, MaxResults=1)
        if not r.get("ResultItems"):
            raise OutOfCoverageError(f"Could not geocode '{query}'")
        item = r["ResultItems"][0]
        lon, lat = item["Position"]
        return lat, lon, item.get("Title", query)


# --------------------------------------------------------------------------------------
# Result container
# --------------------------------------------------------------------------------------
@dataclass
class Recommendation:
    query: Optional[str]
    input_point: dict
    matched_location: dict
    baseline: dict
    needs: dict
    species_ranking: list
    patch_plan: list
    plan_summary: dict
    warnings: list = field(default_factory=list)

    def to_dict(self):
        return _clean(self.__dict__)

    def to_json(self, **kw):
        return json.dumps(self.to_dict(), **kw)

    def to_geojson(self):
        feats = [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [self.input_point["lon"], self.input_point["lat"]]},
             "properties": {"kind": "query", "label": self.query or "Selected point"}},
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": [self.matched_location["lon"], self.matched_location["lat"]]},
             "properties": {"kind": "matched_location", **{k: v for k, v in self.matched_location.items() if k not in ("lat", "lon")}}},
        ]
        for p in self.patch_plan:
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [p["lon"], p["lat"]]},
                          "properties": {"kind": "patch", **{k: v for k, v in p.items() if k not in ("lat", "lon")}}})
        return _clean({"type": "FeatureCollection", "features": feats})


# --------------------------------------------------------------------------------------
# Engine
# --------------------------------------------------------------------------------------
class RecommendationEngine:
    def __init__(self, data_dir="data", weights: Optional[dict] = None, geocoder=None,
                 max_snap_km=5.0, max_species_share=0.40, diversity_grace_trees=30, cap_by_est_trees=True,
                 pm10_coarse_weight=0.3):
        self.dir = Path(data_dir)
        self.w = {**DEFAULT_WEIGHTS, **(weights or {})}
        self.max_snap_km, self.max_share = max_snap_km, max_species_share
        self.grace, self.cap_est, self.pm10_w = diversity_grace_trees, cap_by_est_trees, pm10_coarse_weight

        self.locations = _read_csv(self.dir / FILES["locations"], ["location_id", "name", "lat", "lon"], "locations")
        self.locations["location_id"] = self.locations["location_id"].astype(str)
        self.env = _read_csv(self.dir / FILES["environment"], ENV_REQUIRED, "environment", parse_dates=["time"])
        self.env["location_id"] = self.env["location_id"].astype(str)
        # --- parse time robustly ---
        t = pd.to_datetime(self.env["time"], errors="coerce")
        if t.isna().mean() > 0.01:                       # likely day-first format like 15-01-2024
            t = pd.to_datetime(self.env["time"], errors="coerce", dayfirst=True)
        bad = int(t.isna().sum())
        if bad:
            print(f"WARNING: {bad} environment rows have an unreadable 'time' and were dropped")
        self.env["time"] = t
        self.env = self.env.dropna(subset=["time"])
        
        # --- clean environment data ---
        self.env = self.env.sort_values(["location_id", "time"]).reset_index(drop=True)
        core = [c for c in ENV_REQUIRED if c not in ("location_id", "time")]
        fill_cols = [c for c in core if c != "precipitation"]
        self.env[fill_cols] = (self.env.groupby("location_id")[fill_cols]
                               .transform(lambda s: s.interpolate(limit=6, limit_area="inside")))
        before = len(self.env)
        self.env = self.env.dropna(subset=core).reset_index(drop=True)
        if before and (before - len(self.env)) / before > 0.10:
            print(f"WARNING: dropped {before - len(self.env)} of {before} environment rows with NaN in core columns")
        self.species = _read_csv(self.dir / FILES["species"], SPECIES_REQUIRED, "species").reset_index(drop=True)
        self.patches = _read_csv(self.dir / FILES["patches"], PATCH_REQUIRED, "patches")
        self.patches["patch_id"] = self.patches["patch_id"].astype(str)
        self._assign_patches_to_locations()
        self._prep_species()
        self.geocoder = geocoder or Geocoder(self.dir / FILES["geocode_cache"], locations_df=self.locations)
        self._baseline_cache: dict = {}

    # ---------------- data prep ----------------
    def _assign_patches_to_locations(self):
        if "location_id" in self.patches.columns:
            self.patches["location_id"] = self.patches["location_id"].astype(str)
            return
        ids = []
        for r in self.patches.itertuples():
            d = haversine_km(r.lat, r.lon, self.locations["lat"].values, self.locations["lon"].values)
            i = int(np.argmin(d))
            ids.append(self.locations["location_id"].iloc[i] if d[i] <= self.max_snap_km else None)
        self.patches["location_id"] = ids

    def _prep_species(self):
        s = self.species
        n = pd.DataFrame(index=s.index)
        n["pm_cap"] = _unit(s["pm_capture_index"])
        n["poll_tol"] = _unit(s["pollution_tolerance_index"])
        n["heat_tol"] = _unit(s["heat_tolerance"])
        n["drought_tol"] = _unit(s["drought_tolerance"])
        n["waterlog_tol"] = _unit(s["waterlogging_tolerance"])
        n["bvoc"] = _unit(s["bvoc_penalty_index"])
        n["root_risk"] = _unit(s["root_damage_risk"])
        n["survival"] = _frac(s["survival_yr10"])
        n["resusp"] = _frac(s["resuspension_frac"])
        n["growth"] = _minmax(0.5 * pd.to_numeric(s["canopy_frac_yr5"], errors="coerce")
                              + 0.5 * pd.to_numeric(s["canopy_frac_yr10"], errors="coerce"))
        n["cool"] = (0.35 * _minmax(s["air_cooling_c_scenario"]) + 0.35 * _minmax(s["mrt_reduction_c_scenario"])
                     + 0.15 * _minmax(s["surface_temp_reduction_c_under_canopy"])
                     + 0.15 * _unit(s["summer_shade_effectiveness"]))
        irr = 0.5 * _minmax(s["irrigation_L_per_yr_yr1_3"]) + 0.5 * _minmax(s["irrigation_L_per_yr_yr4plus"])
        if "water_multiplier" in s.columns:
            irr = 0.7 * irr + 0.3 * _minmax(s["water_multiplier"])
        n["water_eff"] = 1 - irr
        n["cost_eff"] = 1 - _minmax(s["total_cost_7yr_inr"])
        n["local_fit"] = 0.8 * _unit(s["local_suitability_score"]) + 0.2 * _bool(s["native_delhi_list"]).astype(float)
        n["leaf_w"] = _frac(s["leaf_on_frac_winter_nov_feb"])
        n["leaf_s"] = _frac(s["leaf_on_frac_mar_oct"])
        n["leaf_a"] = _frac(s["leaf_on_frac_annual"]).clip(lower=0.05)
        self.sn = n
        for c in ("suitable_verge", "suitable_park_edge", "suitable_institutional", "suitable_median"):
            s[c] = _bool(s[c])

    # ---------------- location matching ----------------
    def resolve_location(self, query=None, lat=None, lon=None):
        label = query
        if lat is None or lon is None:
            if not query:
                raise ValueError("Provide a place name or lat/lon.")
            lat, lon, label = self.geocoder.geocode(query)
        d = haversine_km(lat, lon, self.locations["lat"].values, self.locations["lon"].values)
        order = np.argsort(d)
        best = self.locations.iloc[int(order[0])]
        dist = float(d[order[0]])
        warnings = []
        if dist > self.max_snap_km:
            near = ", ".join(f"{self.locations.iloc[int(i)]['name']} ({d[i]:.1f} km)" for i in order[:3])
            raise OutOfCoverageError(f"'{label}' is {dist:.1f} km from the nearest covered site. Nearest: {near}")
        if dist > self.max_snap_km * 0.6:
            warnings.append(f"Point is {dist:.1f} km from the matched site; results are approximate.")
        match = {"location_id": best["location_id"], "name": best["name"], "lat": float(best["lat"]),
                 "lon": float(best["lon"]), "distance_km": round(dist, 3)}
        return {"lat": float(lat), "lon": float(lon), "label": label}, match, warnings

    # ---------------- baseline ----------------
    def baseline(self, location_id: str) -> dict:
        if location_id in self._baseline_cache:
            return self._baseline_cache[location_id]
        df = self.env[self.env["location_id"] == str(location_id)].copy()
        if df.empty:
            raise DataError(f"No environment rows for location_id={location_id}")
        df["season"] = df["time"].dt.month.map(MONTH_TO_SEASON)
        years = max((df["time"].max() - df["time"].min()).days / 365.25, 1e-6)
        num_cols = [c for c in df.columns if c not in ("location_id", "time", "season")
                    and pd.api.types.is_numeric_dtype(df[c])]

        def summarize(d):
            out = {"share": len(d) / len(df), "mean": d[num_cols].mean().to_dict(), "n_hours": len(d)}
            out["p90"] = {c: float(d[c].quantile(0.9)) for c in ("pm2_5", "pm10", "apparent_temperature",
                                                                 "vapour_pressure_deficit") if c in d}
            out["exceedance_frac"] = {c: float((d[c] > lim).mean()) for c, lim in LIMITS.items() if c in d}
            out["heat_hours_frac"] = float((d["apparent_temperature"] >= HEAT_APPARENT_C).mean())
            return out

        base = {"seasons": {s: summarize(g) for s, g in df.groupby("season")}, "annual": summarize(df),
                "period": [df["time"].min().isoformat(), df["time"].max().isoformat()],
                "precip_mm_per_year": float(df["precipitation"].sum() / years)}
        mons = df[df["season"] == "monsoon"]
        base["monsoon_precip_mm_per_year"] = float(mons["precipitation"].sum() / years) if len(mons) else 0.0
        base["needs"] = self._needs(base)
        self._baseline_cache[location_id] = base
        return base

    @staticmethod
    def _needs(b) -> dict:
        a = b["annual"]["mean"]
        pm = 0.6 * _clip01(a["pm2_5"] / 120) + 0.4 * _clip01(a["pm10"] / 250)
        hs = {s: _clip01((v["p90"]["apparent_temperature"] - 30) / 15) for s, v in b["seasons"].items()}
        voc = 0.5 * _clip01(a["ozone"] / 100) + 0.5 * _clip01(a["nitrogen_dioxide"] / 80)
        scarcity = 0.5 * _clip01(a["vapour_pressure_deficit"] / 2.5) + 0.5 * _clip01(1 - b["precip_mm_per_year"] / 1200)
        return {"pm_need": pm, "heat_need": max(hs.values()), "heat_stress_by_season": hs,
                "voc_sensitivity": voc, "water_scarcity": scarcity,
                "waterlogging_risk": _clip01(b["monsoon_precip_mm_per_year"] / 600)}

    # ---------------- species scoring ----------------
    def score_species(self, location_id: str) -> pd.DataFrame:
        b, nd, s, n = self.baseline(location_id), None, self.species, self.sn
        nd = b["needs"]
        rem25 = pd.Series(0.0, index=s.index)
        rem10 = pd.Series(0.0, index=s.index)
        cool_num = pd.Series(0.0, index=s.index)
        hs_sum = sum(nd["heat_stress_by_season"].values()) or 1e-9
        for season, st in b["seasons"].items():
            leaf = n["leaf_w"] if season == "winter" else n["leaf_s"]
            rel_leaf = leaf / n["leaf_a"]
            rem25 += st["share"] * s["pm25_removal_g_yr_mature_at_100ugm3"] * (st["mean"]["pm2_5"] / 100) * rel_leaf
            rem10 += st["share"] * s["pm10_removal_g_yr_mature_at_200ugm3"] * (st["mean"]["pm10"] / 200) * rel_leaf
            cool_num += nd["heat_stress_by_season"][season] * n["cool"] * leaf
        net_removal = (rem25 + self.pm10_w * rem10) * (1 - n["resusp"])
        pm_idx = 0.5 * n["pm_cap"] + 0.5 * _minmax(net_removal)
        cool_idx = cool_num / hs_sum

        pm_w, heat_w = 0.25 + 0.75 * nd["pm_need"], 0.25 + 0.75 * nd["heat_need"]
        benefit = (pm_w * pm_idx + heat_w * cool_idx) / (pm_w + heat_w) * (0.6 + 0.4 * n["growth"])

        rw = {"heat": 0.5 + 0.5 * nd["heat_need"], "drought": 0.5 + 0.5 * nd["water_scarcity"],
              "flood": 0.25 + 0.75 * nd["waterlogging_risk"], "poll": 0.5 + 0.5 * nd["pm_need"], "surv": 1.0}
        resilience = (rw["heat"] * n["heat_tol"] + rw["drought"] * n["drought_tol"] + rw["flood"] * n["waterlog_tol"]
                      + rw["poll"] * n["poll_tol"] + rw["surv"] * n["survival"]) / sum(rw.values())
        water = 0.5 + (n["water_eff"] - 0.5) * (0.3 + 0.7 * nd["water_scarcity"])
        bvoc_pen = n["bvoc"] * nd["voc_sensitivity"]

        w = self.w
        score = (w["benefit"] * benefit + w["resilience"] * resilience + w["local_fit"] * n["local_fit"]
                 + w["water"] * water + w["cost"] * n["cost_eff"] - w["bvoc_penalty"] * bvoc_pen)
        tot = w["benefit"] + w["resilience"] + w["local_fit"] + w["water"] + w["cost"]
        out = pd.DataFrame({
            "species_id": s["species_id"], "common_name": s["common_name"], "scientific_name": s["scientific_name"],
            "score": (score / tot).clip(0, 1) * 100,
            "pm_index": pm_idx, "cooling_index": cool_idx, "benefit": benefit, "resilience": resilience,
            "local_fit": n["local_fit"], "water_term": water, "cost_term": n["cost_eff"], "bvoc_penalty": bvoc_pen,
            "pm25_removal_g_yr_mature_local": rem25 * (1 - n["resusp"]),
            "pm10_removal_g_yr_mature_local": rem10 * (1 - n["resusp"]),
        })
        out["why"] = [self._reasons(i, out, nd) for i in out.index]
        return out.sort_values("score", ascending=False).reset_index(drop=True)

    def _reasons(self, i, o, nd):
        n, s, r = self.sn.loc[i], self.species.loc[i], []
        if o.loc[i, "pm_index"] >= 0.66 and nd["pm_need"] >= 0.4:
            r.append(f"strong particulate capture (~{o.loc[i, 'pm25_removal_g_yr_mature_local']:.0f} g PM2.5/yr per mature tree at local levels)")
        if o.loc[i, "cooling_index"] >= 0.6 and nd["heat_need"] >= 0.4:
            r.append("effective summer cooling and shade")
        if n["heat_tol"] >= 0.66:
            r.append("heat tolerant")
        if n["drought_tol"] >= 0.66 and nd["water_scarcity"] >= 0.4:
            r.append("drought tolerant, low irrigation need")
        if n["waterlog_tol"] >= 0.66 and nd["waterlogging_risk"] >= 0.5:
            r.append("tolerates monsoon waterlogging")
        if n["poll_tol"] >= 0.66:
            r.append("tolerates polluted air")
        if bool(_bool(pd.Series([s["native_delhi_list"]])).iloc[0]):
            r.append("native to Delhi")
        if n["cost_eff"] >= 0.66:
            r.append("low 7-year cost")
        if n["bvoc"] >= 0.66 and nd["voc_sensitivity"] >= 0.5:
            r.append("caution: high BVOC emissions can add to ozone formation here")
        return r

    # ---------------- patch planning ----------------
    @staticmethod
    def _site_flag(site_type: str) -> Optional[str]:
        t = str(site_type).lower()
        for flag, kws in SITE_KEYWORDS.items():
            if any(k in t for k in kws):
                return flag
        return None

    def _tree_count(self, p, sp) -> int:
        n = int(p["area_m2"] // max(float(sp["planting_area_per_tree_m2"]), 1e-6))
        flag = self._site_flag(p["site_type"])
        linear = flag in ("suitable_verge", "suitable_median") or any(
            k in str(p.get("shape", "")).lower() for k in ("linear", "strip", "line", "elong"))
        length = pd.to_numeric(p.get("length_m"), errors="coerce")
        if linear and np.isfinite(length) and length > 0:
            n = min(n, int(length // max(float(sp["spacing_m"]), 1e-6)) + 1)
        est = pd.to_numeric(p.get("est_trees"), errors="coerce")
        if self.cap_est and np.isfinite(est) and est > 0:
            n = min(n, int(est))
        return max(n, 0)

    def plan_patches(self, location_id: str, ranked: pd.DataFrame) -> list:
        pts = self.patches[self.patches["location_id"] == str(location_id)].sort_values("area_m2", ascending=False)
        if pts.empty:
            return []
        base_score = ranked.set_index("species_id")["score"]
        sp_by_id = self.species.set_index("species_id")
        root = self.sn.set_index(self.species["species_id"])["root_risk"]
        counts, planned, plan = {}, 0, []
        for _, p in pts.iterrows():
            flag = self._site_flag(p["site_type"])
            maxw = pd.to_numeric(p.get("max_width_m"), errors="coerce")
            avgw = pd.to_numeric(p.get("avg_width_m"), errors="coerce")
            cands = []
            for sid, sp in sp_by_id.iterrows():
                if flag and not bool(sp[flag]):
                    continue
                if np.isfinite(maxw) and maxw < float(sp["min_site_width_m"]):
                    continue
                if p["area_m2"] < float(sp["planting_area_per_tree_m2"]):
                    continue
                n = self._tree_count(p, sp)
                if n < 1:
                    continue
                narrow = _clip01(1 - (avgw if np.isfinite(avgw) else maxw if np.isfinite(maxw) else 10)
                                 / (2 * max(float(sp["min_site_width_m"]), 1e-6)))
                adj = base_score[sid] * (1 - 0.2 * root[sid] * narrow)
                cands.append((sid, adj, n))
            if not cands:
                plan.append({"patch_id": p["patch_id"], "lat": p["lat"], "lon": p["lon"], "site_type": p["site_type"],
                             "area_m2": p["area_m2"], "recommended": None,
                             "note": "No species fits this patch (width/area/site-type constraints)."})
                continue
            cands.sort(key=lambda c: c[1], reverse=True)
            choice = cands[0]
            if planned >= self.grace:
                for c in cands:
                    if (counts.get(c[0], 0) + c[2]) / (planned + c[2]) <= self.max_share:
                        choice = c
                        break
            sid, adj, n = choice
            counts[sid] = counts.get(sid, 0) + n
            planned += n
            sp = sp_by_id.loc[sid]
            canopy10 = float(pd.to_numeric(sp.get("canopy_frac_yr10", np.nan), errors="coerce"))
            surv10 = float(_frac(pd.Series([sp["survival_yr10"]])).iloc[0]) if "survival_yr10" in sp else 1.0
            plan.append({
                "patch_id": p["patch_id"], "lat": p["lat"], "lon": p["lon"], "site_type": p["site_type"],
                "area_m2": p["area_m2"], "recommended": sid, "common_name": sp["common_name"],
                "scientific_name": sp["scientific_name"], "n_trees": n, "fit_score": round(adj, 2),
                "alternatives": [{"species_id": c[0], "common_name": sp_by_id.loc[c[0], "common_name"],
                                  "fit_score": round(c[1], 2), "n_trees": c[2]} for c in cands if c[0] != sid][:2],
                "est_cost_7yr_inr": float(sp["total_cost_7yr_inr"]) * n,
                "est_irrigation_L_per_yr_mature": float(sp["irrigation_L_per_yr_yr4plus"]) * n,
                "_canopy10": canopy10, "_surv10": surv10,
            })
        return plan

    def summarize_plan(self, plan: list, ranked: pd.DataFrame) -> dict:
        r = ranked.set_index("species_id")
        sp = self.species.set_index("species_id")
        tot = {"trees": 0, "cost_7yr_inr": 0.0, "pm25_g_yr_mature": 0.0, "pm25_g_yr_year10_expected": 0.0,
               "mature_crown_area_m2": 0.0, "irrigation_L_yr_mature": 0.0, "by_species": {}}
        for p in plan:
            if not p.get("recommended"):
                continue
            sid, n = p["recommended"], p["n_trees"]
            rem = float(r.loc[sid, "pm25_removal_g_yr_mature_local"])
            c10 = p["_canopy10"] if np.isfinite(p["_canopy10"]) else 1.0
            if c10 > 1:
                c10 /= 100
            tot["trees"] += n
            tot["cost_7yr_inr"] += p["est_cost_7yr_inr"]
            tot["pm25_g_yr_mature"] += rem * n
            tot["pm25_g_yr_year10_expected"] += rem * n * c10 * p["_surv10"]
            tot["mature_crown_area_m2"] += float(sp.loc[sid, "crown_area_m2_mature"]) * n
            tot["irrigation_L_yr_mature"] += p["est_irrigation_L_per_yr_mature"]
            tot["by_species"][sid] = tot["by_species"].get(sid, 0) + n
        for p in plan:
            p.pop("_canopy10", None)
            p.pop("_surv10", None)
        return tot

    # ---------------- public API ----------------
    def recommend(self, query: Optional[str] = None, lat: Optional[float] = None, lon: Optional[float] = None,
                  top_k: int = 5) -> Recommendation:
        point, match, warns = self.resolve_location(query, lat, lon)
        lid = match["location_id"]
        base = self.baseline(lid)
        ranked = self.score_species(lid)
        plan = self.plan_patches(lid, ranked)
        if not plan:
            warns.append("No planting patches found for this location; showing species ranking only.")
        summary = self.summarize_plan(plan, ranked)
        top = ranked.head(top_k).to_dict(orient="records")
        for t in top:
            t["why"] = t["why"] or ["balanced overall fit for local conditions"]
        base_out = {k: v for k, v in base.items() if k != "needs"}
        return Recommendation(query=query or point["label"], input_point=point, matched_location=match,
                              baseline=base_out, needs=base["needs"], species_ranking=top, patch_plan=plan,
                              plan_summary=summary, warnings=warns)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("query", nargs="?")
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lon", type=float)
    ap.add_argument("--data", default="data")
    a = ap.parse_args()
    res = RecommendationEngine(a.data).recommend(a.query, a.lat, a.lon)
    print(json.dumps({
    "matched_location": res.matched_location,
    "needs": res.needs,
    "species_ranking": res.species_ranking,
    "patch_plan": res.patch_plan,
    "plan_summary": res.plan_summary,
    "warnings": res.warnings
    }, indent=2))
