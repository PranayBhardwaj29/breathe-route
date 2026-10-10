"""
server.py - FastAPI backend + static frontend.
Run:  uvicorn server:app --reload      then open http://127.0.0.1:8000
API:  GET /api/health | GET /api/overview | POST /api/recommend {query | lat+lon, top_k}
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from projections import build_projection
from tree_recommender import DataError, OutOfCoverageError, RecommendationEngine, _clean

ROOT = Path(__file__).parent
PALETTE = ["#1f7a4d", "#2b7fb8", "#e08a00", "#8e5bd0", "#d64545", "#13a0a0", "#b08900", "#d4568f",
           "#4f5bd5", "#6f9c1f", "#e0612a", "#0e8fb0", "#7a6ad8", "#7b756c"]

try:
    engine = RecommendationEngine(ROOT / "data")
except DataError as e:
    raise SystemExit(f"Data problem: {e}")

COLORS = {sid: PALETTE[i % len(PALETTE)] for i, sid in enumerate(engine.species["species_id"])}
SP = engine.species.set_index("species_id")
NAMES = SP["common_name"].to_dict()

app = FastAPI(title="Canopy tree recommender")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


class Query(BaseModel):
    query: str | None = None
    lat: float | None = None
    lon: float | None = None
    top_k: int = 6


@app.get("/api/health")
def health():
    return {"status": "ok", "sites": len(engine.locations), "species": len(engine.species)}


@app.get("/api/overview")
def overview():
    p = engine.patches.dropna(subset=["lat", "lon"])
    return _clean({"sites": engine.locations[["location_id", "name", "lat", "lon"]].to_dict("records"),
                   "patches": p[["lat", "lon", "area_m2"]].to_dict("records")})


@app.post("/api/recommend")
def recommend(q: Query):
    try:
        rec = engine.recommend(q.query, q.lat, q.lon, top_k=max(3, min(q.top_k, 10)))
    except OutOfCoverageError as e:
        raise HTTPException(422, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # geocoder/network problems
        raise HTTPException(502, f"Could not look up that place ({e}). Try coordinates or a study-site name.")
    res = rec.to_dict()
    ranked = engine.score_species(res["matched_location"]["location_id"]).set_index("species_id")
    ids = [s["species_id"] for s in res["species_ranking"]]
    table = []
    for s in res["species_ranking"]:
        r = SP.loc[s["species_id"]]
        sv = float(r["survival_yr10"])
        table.append({"species_id": s["species_id"], "common_name": s["common_name"],
                      "scientific_name": s["scientific_name"], "score": s["score"], "color": COLORS[s["species_id"]],
                      "pm25_g": s["pm25_removal_g_yr_mature_local"], "cooling_c": float(r["air_cooling_c_scenario"]),
                      "crown_m2": float(r["crown_area_m2_mature"]), "water_l": float(r["irrigation_L_per_yr_yr4plus"]),
                      "survival10": sv * 100 if sv <= 1 else sv, "cost7": float(r["total_cost_7yr_inr"]),
                      "why": s["why"]})
    counts = res["plan_summary"]["by_species"]
    proj = build_projection(SP, ranked, ids, counts, NAMES, COLORS)
    return _clean({"result": res, "geojson": rec.to_geojson(), "table": table, "colors": COLORS,
                   "projection": proj})


app.mount("/", StaticFiles(directory=ROOT / "static", html=True), name="static")
