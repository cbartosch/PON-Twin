#!/bin/sh
set -e

# Seed the Spanner emulator (waits for it, idempotent). No-op if SPANNER_EMULATOR_HOST
# is unset — the app then falls back to the local JSON fixtures.
python seed_spanner.py || echo "[entrypoint] seed step failed; continuing with JSON fallback"

exec streamlit run twin_app.py \
    --server.port=8520 --server.address=0.0.0.0 --server.headless=true
