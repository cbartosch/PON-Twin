# Malang PON Digital Twin

An interactive digital twin of a synthetic Malang 4-area PON (Passive Optical
Network), reconciled against the real Telkom Malang STO backbone (Tier 1/2/3).
Ships as an **MCP server** (queryable by an AI agent) with a **Streamlit**
front-end that acts as an MCP client. Data of record lives in a **Cloud Spanner
emulator**, seeded automatically at startup from the JSON fixtures.

## What's inside
- `server.py` — MCP server exposing 22 tools over the twin (topology, inventory,
  cable/port stats, operator-consolidation business case, STO reconciliation,
  Tier-2 aggregation, datastore status).
- `twin_app.py` — Streamlit UI (Dashboard, Areas & Utilisation, Consolidation,
  Reconciliation, Fiber Path Tracer, Map, BoQ, Ask/LLM, Tool Explorer).
- `spanner_store.py` — Spanner (emulator) datastore: schema, seed, load.
- `seed_spanner.py` / `entrypoint.sh` — wait for the emulator + seed on startup.
- `pon_data.json` — the synthetic twin dataset (also the Spanner seed source).
- `malang_sto.json` — real Telkom Malang STO nodes + routing (Tier 1/2/3).
- `_build_sto.py` — regenerates `malang_sto.json` from the source workbook.
- `Dockerfile`, `docker-compose.yml`, `requirements.txt` — containerised run.

## Architecture
Two containers via docker compose:
- **`spanner-emulator`** — Cloud Spanner emulator (datastore of record).
- **`digital-twin`** — Streamlit app + MCP server. On boot it seeds the emulator
  (idempotent) then serves on port **8520**. The MCP server reads all data from
  Spanner; if the emulator is unreachable it transparently falls back to the
  bundled JSON fixtures.

The emulator is ephemeral, so data is re-seeded on every fresh `up` (~10.4k rows).

## Run with Docker (recommended, portable)
Requires Docker Desktop.

```powershell
# 1. Add your OpenAI key (only needed for the Ask/LLM tab)
copy .env.example .env
#    then edit .env and paste your key

# 2. Build & start BOTH containers (app + Spanner emulator)
docker compose up -d --build

# 3. Open the app  (sidebar should show "Datastore: Spanner emulator")
start http://localhost:8520
```

Stop with `docker compose down`. The app is served on port **8520**; the Spanner
emulator gRPC is published on host **9011** (host 9010 is often held by Zscaler)
and REST on **9020**. The `.env` is mounted read-only and is **never** baked into
the image.

> Behind a TLS-inspection proxy (e.g. Zscaler on BCG laptops)? The Dockerfile
> already trusts the PyPI hosts so `pip` works during the build.

### Without the LLM tab
Every tab except **Ask (LLM)** works with no API key. You can also paste a key
directly into the sidebar at runtime instead of using `.env`.

## Run locally without Docker
Requires Python 3.11+. Without a Spanner emulator the app uses the JSON fixtures
(no `SPANNER_EMULATOR_HOST` set → automatic fallback).

```powershell
pip install -r requirements.txt
copy .env.example .env      # optional, for the Ask tab
streamlit run twin_app.py --server.port 8520
```

To use Spanner locally, start an emulator and export the env vars before running:

```powershell
docker run -d -p 9010:9010 -p 9020:9020 gcr.io/cloud-spanner-emulator/emulator
$env:SPANNER_EMULATOR_HOST="localhost:9010"
python seed_spanner.py       # create schema + seed
streamlit run twin_app.py --server.port 8520
```

## Regenerating the STO data
If you have an updated source workbook, edit the `XLSX` path in `_build_sto.py`
and run `python _build_sto.py` to refresh `malang_sto.json`.
