# Richmond Odor Intelligence

A development-ready prototype for an odor "weather report" that combines
environmental conditions, H2S observations, sanitary sewer hotspots, community
odor complaints, and a forecast/decision layer.

> **Prototype honesty:** H2S values and CMMS work orders are simulated until
> sanctioned integrations are connected. Weather and tide adapters can call
> live public APIs when the app has internet access.

## What is included

- Odor Forecast landing page with current and 6-hour risk outlook
- Spatial map of illustrative sewer hotspots and H2S monitors
- Live Open-Meteo weather adapter
- NOAA CO-OPS Richmond tide adapter, station `9414863`
- Simulated Richmond H2S adapter behind a replaceable service boundary
- Odor complaint form that mimics Survey123 intake
- Simulated CMMS work-order generation and response status
- Public complaint table with exact coordinates removed
- Landmark-snapped complaint map / density visualization
- ML-ready risk service with explicit "prototype engineering score" labeling
- Docker and local Python run paths
- Architecture, integration, model, and data dictionary documentation

## Quick start

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS/Linux:
source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open `http://localhost:8000`.

### Docker

```bash
docker compose up --build
```

## API endpoints

- `GET /api/health`
- `GET /api/risk`
- `GET /api/weather`
- `GET /api/tides`
- `GET /api/h2s`
- `GET /api/hotspots`
- `GET /api/complaints`
- `POST /api/complaints`
- `PATCH /api/complaints/{complaint_id}/status`

Interactive API docs are at `http://localhost:8000/docs`.

## Complaint privacy design

The server stores raw complaint coordinates because they are useful for internal
source attribution and investigation. The public endpoint does **not** return
those coordinates. Instead it returns the nearest approved landmark and that
landmark's map coordinate. Public free-text comments are also suppressed.

This is intentionally stricter than merely rounding latitude/longitude.

## Swapping in real integrations

### Richmond H2S
Replace `app/services/h2s.py:get_h2s()` with the sanctioned data feed. The UI
and risk endpoint require only a normalized list of:

```json
{
  "timestamp": "ISO-8601",
  "sensors": [
    {"id":"...","name":"...","lat":37.0,"lon":-122.0,"h2s_ppb":12.3,"simulated":false}
  ]
}
```

### Survey123
Point a Survey123 webhook at a production ingestion endpoint patterned after
`POST /api/complaints`. Add authentication and retain reporter PII outside the
public analytical table.

### CMMS
Replace `SIM-*` generation with an authenticated CMMS create-work-order call.
Translate CMMS workflow states into the four public statuses used by the prototype.

## Model evolution

`app/ml/risk.py` is deliberately transparent and deterministic. Do not call it
"machine learning" in a production presentation. Once historical H2S,
meteorological, tide, asset/process and complaint outcomes have been assembled,
replace the function with a trained XGBoost/LightGBM classifier and time-aware
validation. See `docs/MODEL_DESIGN.md`.

## Recommended GitHub workflow

```bash
git init
git add .
git commit -m "Initial Richmond odor intelligence prototype"
git branch -M main
git remote add origin <YOUR-GITHUB-REPO-URL>
git push -u origin main
```

Suggested repository name: `richmond-odor-intelligence`.

## Source notes

- NOAA CO-OPS exposes observations/predictions through its data retrieval API.
- NOAA station 9414863 is Richmond, California.
- Open-Meteo exposes hourly/current forecast variables including 10 m wind speed,
  wind direction, temperature, humidity and precipitation.
- The Richmond public H2S site is treated as a source requiring a sanctioned
  machine-readable integration before production use.

See `docs/INTEGRATIONS.md`.
