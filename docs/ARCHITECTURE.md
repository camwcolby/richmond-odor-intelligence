# Architecture

## Prototype
Browser → FastAPI → adapter/service layer → SQLite + external public APIs.

### Live-capable adapters
- `services/weather.py`: Open-Meteo forecast/current weather.
- `services/tides.py`: NOAA CO-OPS tide predictions, Richmond station 9414863.

### Simulated adapters
- `services/h2s.py`: deterministic H2S monitor simulation until a sanctioned Richmond machine-readable feed is confirmed.
- complaint → CMMS: `SIM-*` work order IDs stand in for the future Survey123/CMMS transaction.

### Public privacy boundary
Raw complaint coordinates are retained server-side for analysis but `/api/complaints` never returns them.
The public endpoint snaps records to the closest approved landmark. Free-text comments are also suppressed.

## Production target
Recommended evolution:

Survey123 webhook ─┐
CMMS API ──────────┤
H2S feed ──────────┤
SCADA/WIMS ────────┼→ ingestion jobs → Postgres/PostGIS → feature store
Weather/tide ──────┘                                  │
                                                     ↓
                                         XGBoost / LightGBM model
                                                     │
                                                     ↓
                                    FastAPI prediction + GIS API
                                                     │
                                                     ↓
                                             React / MapLibre UI

Use scheduled ingestion with timestamps in UTC, maintain source provenance, and retain model/version metadata for every forecast.
