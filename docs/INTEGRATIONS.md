# Integration contracts

## Richmond H2S
`app/services/h2s.py` is the replacement seam. Preferred order:
1. documented/vendor-supported API,
2. sanctioned JSON/data endpoint used by the public application,
3. scheduled data export,
4. scraping only with explicit permission and as a last resort.

## Survey123
Production option: ArcGIS Survey123 webhook POSTs a normalized complaint object
to an ingestion endpoint. Preserve raw coordinates in restricted storage.

## CMMS
Create a work request from the complaint, store the returned CMMS ID, and poll
or receive webhook updates for status. Public statuses should be mapped into a
small vocabulary: Received, Reviewing, Investigating, Resolved.

## Weather
Open-Meteo is used in the prototype for current/forecast fields.

## Tides
NOAA CO-OPS station 9414863 (Richmond, CA) is used for tide predictions.

## Privacy
Never expose exact residential coordinates, reporter identity/contact information,
or unreviewed free-text comments on the public endpoint.
