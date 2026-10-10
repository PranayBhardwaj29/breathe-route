# Canopy: which tree should go here?

A tree-planting recommender for Delhi, built for an AWS environment hackathon. Search a place (or paste coordinates) and Canopy:

1. matches it to the nearest **study site** we have data for,
2. builds a seasonal **baseline** of that site's air quality, heat and water conditions,
3. ranks the **tree species** that best improve those conditions,
4. assigns species to the site's **planting spaces**, and
5. projects growth, survival, impact and cost over 20 years.

Everything is shown on a satellite map with the planting spaces highlighted.

## How the recommendation works

- **Baseline** (`tree_recommender.py`): per-season statistics (winter, summer, monsoon, post-monsoon) from the 2024-2026 environmental time series, turned into five needs: particle pollution, heat stress, ozone sensitivity, water scarcity and waterlogging risk.
- **Species score (0-100):** benefit (PM capture rescaled to local concentrations and leaf-on fraction, plus cooling) weighted by the site's needs, combined with resilience, local suitability, water use and cost, minus a penalty for ozone-forming (BVOC) emissions. Weights live in `DEFAULT_WEIGHTS`.
- **Planting plan:** species are filtered per patch by site type, minimum width, area per tree and spacing, then picked best-first with a cap so no single species exceeds 40% of planted trees.
- **Projections** (`projections.py`): synthetic 20-year curves built from the species table's canopy, survival and cost columns. Impact is scaled by canopy size and surviving trees. Treat these as comparisons between species, not forecasts.

## Project structure

```
Recommender/
  server.py              FastAPI app: API + serves the frontend
  tree_recommender.py    recommendation engine
  projections.py         20-year growth / survival / impact / cost curves
  requirements.txt
  static/index.html      frontend (Leaflet map + Chart.js charts)
  data/
    locations.csv              location_id, name, lat, lon  (one row per study site)
    environment_conditions.csv location_id, time, pm2_5, pm10, ...  (hourly)
    tree_species.csv           one row per species
    planting_patches.csv       patch_id, lat, lon, area_m2, site_type, ... (+ optional location_id)
    geocode_cache.csv          auto-created cache of place lookups
```

Required columns are validated at startup; a missing file or column stops the app with a message naming it. Column names may carry unit suffixes (e.g. `pm2_5 (μg/m³)`), which are stripped on load. Environment rows with unreadable times are dropped, short gaps (up to 6 hours) are interpolated, and rows still missing a core column are dropped.

## Run locally

Requires Python 3.10+.

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

Open http://127.0.0.1:8000. Interactive API docs are at http://127.0.0.1:8000/docs.

Run from the project folder, or the `data/` and `static/` folders will not be found.

## API

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Status, number of sites and species |
| GET | `/api/overview` | All study sites and planting patches (for the initial map) |
| POST | `/api/recommend` | Recommendation for a place |

`POST /api/recommend` body: `{"query": "Anand Lok, New Delhi", "top_k": 6}` or `{"lat": 28.5575, "lon": 77.22, "top_k": 6}`.

The response contains `result` (matched site, baseline, needs, ranked species, patch plan, plan summary, warnings), `geojson` (map layers), `table` (top species with benefit stats), `colors` and `projection` (per-species and total 20-year curves).

Errors: `422` if the point is more than 5 km from every study site (the message lists the nearest ones), `400` for missing input, `502` if the place lookup fails.

## Adding a study site

1. Add a row to `data/locations.csv`.
2. Add its rows to `data/environment_conditions.csv` with the same `location_id`.
3. Add its patches to `data/planting_patches.csv` (with that `location_id`, or coordinates within 5 km of the site).
4. Restart the server.

## Deploying

The app is a single process: `uvicorn server:app --host 0.0.0.0 --port 8000`. An untested starting-point Dockerfile for App Runner, ECS or similar:

```dockerfile
FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8000"]
```

Before a real deployment:

- **CORS:** `server.py` allows all origins; restrict `allow_origins` to your frontend's domain.
- **Geocoding:** the default is the free Nominatim service, which rate-limits shared IPs. Switch to `AmazonLocationGeocoder` (in `tree_recommender.py`; verify its API call against your boto3 version) and pass it as `geocoder=` when creating the engine.
- **Map tiles:** Esri satellite and OpenStreetMap tiles are fine for a demo but have usage terms for production traffic.
- **Data size:** the environment CSV is loaded into memory once at startup. Keep that in mind when sizing the container.

## Known limitations

- Planting spaces are drawn as circles sized to each patch's area, not true outlines.
- Environmental baselines come from modelled data at the study sites and are applied to nearby points within 5 km.
- Growth, survival and cost projections are synthetic.
