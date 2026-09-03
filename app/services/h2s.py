
"""
H2S adapter.

The public Richmond H2S site is intentionally abstracted behind this service.
Until a sanctioned machine-readable endpoint is confirmed, the demo returns
deterministic simulated sensor readings. Replace get_h2s() only; the rest of
the application does not need to change.
"""
from datetime import datetime, timezone
import math

SENSORS = [
    {"id":"H2S-01","name":"North Perimeter","lat":37.9430,"lon":-122.3715},
    {"id":"H2S-02","name":"Plant Entrance","lat":37.9392,"lon":-122.3690},
    {"id":"H2S-03","name":"South Perimeter","lat":37.9348,"lon":-122.3670},
    {"id":"H2S-04","name":"Marina Corridor","lat":37.9228,"lon":-122.3540},
]

async def get_h2s():
    minute = datetime.now(timezone.utc).timestamp() / 60
    out = []
    for i, s in enumerate(SENSORS):
        baseline = 12 + 8 * math.sin(minute / 18 + i)
        pulse = max(0, 25 * math.sin(minute / 7 + i * 1.7))
        value = round(max(1, baseline + pulse), 1)
        out.append({**s, "h2s_ppb": value, "simulated": True})
    return {"timestamp": datetime.now(timezone.utc).isoformat(), "sensors": out}
