# Core data dictionary

| Entity | Key fields | Notes |
|---|---|---|
| H2S observation | timestamp, sensor_id, lat/lon, h2s_ppb | Demo is simulated |
| Weather | timestamp, wind speed/direction, gust, temp, RH, precip | Live adapter |
| Tide | timestamp, predicted_ft_mllw | NOAA CO-OPS |
| Sewer hotspot | hotspot_id, category, lat/lon, source_score | Static CSV in v1 |
| Complaint | complaint_id, raw lat/lon, public_location, odor_type, intensity, status | Raw coordinates restricted |
| CMMS record | work_order, status | Simulated in v1 |
| Forecast | issued_at, horizon, probability, risk_level, drivers, model_version | Prototype score in v1 |
