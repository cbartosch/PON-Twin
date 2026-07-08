"""Startup seeder: wait for the Spanner emulator, then create schema + seed the
twin data from the JSON fixtures (idempotent). Safe to run on every container
start because the emulator is ephemeral."""
import os
import sys

import spanner_store as ss

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
STO = os.path.join(HERE, "malang_sto.json")


def main():
    if not ss.spanner_configured():
        print("[seed] SPANNER_EMULATOR_HOST not set or client unavailable; "
              "skipping seed (server will use JSON fallback).")
        return 0
    print(f"[seed] Waiting for emulator at {os.environ['SPANNER_EMULATOR_HOST']} ...")
    ss.wait_for_emulator()
    print("[seed] Emulator reachable. Ensuring schema + seeding ...")
    result = ss.ensure_schema_and_seed(PON, STO)
    if result["seeded"]:
        print(f"[seed] Seeded {result['rows']} rows into twin_records.")
    else:
        print(f"[seed] Already populated ({result['rows']} rows); nothing to do.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
