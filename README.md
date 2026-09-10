
# Richmond Sonoma Raw API Probe

Copy `probe_sonoma_raw.py` into the repository root and run:

    python probe_sonoma_raw.py

It bypasses the FastAPI app and directly reproduces the Sonoma POST payload
previously observed in the Richmond site's browser Network panel.

It tests 2-hour, 24-hour, and 7-day windows and prints raw/valid counts plus
latest raw and latest valid observations for each returned series.

It reads `SONOMA_DMS_TOKEN` from your existing `.env` and never prints the token.
