"""Fix the 'Aerial poles' KPI: it currently shows 2,000 (the map-sampled subset
in d["poles"]), not a real count.

Operator B (PLN IconPlus) has REAL national poles in NET06 (DRL_NET-06_PolesFTTH,
1.29M rows with lat/lng). We count them for the actual figure. Telkom (NET-02)
has no pole plant, so we synthesize Telkom poles from Icon's measured pole
intensity per route-km, applied to Telkom's synthetic route-km:

    poles_per_km = Icon national poles / Icon national route-km
    Telkom poles = poles_per_km * Telkom synthetic route-km

Both are stored under national_footprint (operator_B_poles actual /
operator_A_poles synthetic) and surfaced as dashboard KPIs. The 2,000-pole
sample in d["poles"] is untouched (still used by the map).

Reads pon_data.json (must already contain both cable models), writes
pon_data.json.bak11.  Run:  python _build_poles_national.py [--dry-run]
"""
import argparse
import collections
import io
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
NET_ZIP = os.path.expanduser("~/Downloads/01 NET.zip")
NET06 = "01 NET/NET06 Ducts and poles/DRL_NET-06_PolesFTTH_v1.csv"


def count_net06():
    z = zipfile.ZipFile(NET_ZIP)
    n = 0
    per_sbu = collections.Counter()
    with z.open(NET06) as f:
        t = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        next(t)
        for line in t:
            c = line.rstrip("\n").split("|")
            if len(c) < 10:
                continue
            n += 1
            per_sbu[(c[8] or "").strip() or "UNSPECIFIED"] += 1
            if n % 500000 == 0:
                print(f"  NET06 ...{n:,} scanned", flush=True)
    z.close()
    return n, per_sbu


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = json.load(open(PON, encoding="utf-8"))
    nfb = d["national_footprint"]["operator_B_cable_model"]
    nfa = d["national_footprint"]["operator_A_cable_model"]

    print("Counting NET06 poles (1.29M) ...")
    b_poles, per_sbu = count_net06()
    poles_per_km = b_poles / nfb["route_km_total"]
    a_poles = round(nfa["route_km_total"] * poles_per_km)
    print(f"Operator B poles (actual):   {b_poles:,}")
    print(f"poles per route-km (Icon):   {poles_per_km:.4f}")
    print(f"Operator A poles (synth):    {a_poles:,}")
    print(f"National total poles:        {b_poles + a_poles:,}")

    d["national_footprint"]["operator_B_poles"] = {
        "count": b_poles,
        "source": "NET06 DRL_NET-06_PolesFTTH (PLN IconPlus, national)",
        "per_sbu": dict(per_sbu),
        "note": "Actual national pole inventory. d['poles'] holds a 2,000-pole map sample only.",
    }
    d["national_footprint"]["operator_A_poles"] = {
        "count": a_poles,
        "synthetic": True,
        "poles_per_route_km": round(poles_per_km, 4),
        "basis_route_km": nfa["route_km_total"],
        "method": ("SYNTHETIC. Telkom NET-02 has no pole plant; poles = Icon national "
                   "poles-per-route-km x Telkom synthetic route-km."),
    }

    # --- dashboard: drop the misleading 2,000 sample row, add national poles ---
    dash = [r for r in d["dashboard"] if r.get("Metric") != "Aerial poles"]
    pole_rows = [
        {"Metric": "Operator B poles (national, actual)", "Value": b_poles, "Unit": "ea",
         "Comment": "NET06 PolesFTTH (PLN IconPlus, national)"},
        {"Metric": "Operator A poles (national, synth)", "Value": a_poles, "Unit": "ea",
         "Comment": f"Synthetic: {poles_per_km:.2f} poles/route-km (Icon) x Telkom route-km"},
        {"Metric": "Total poles (national)", "Value": b_poles + a_poles, "Unit": "ea",
         "Comment": "Icon actual + Telkom synthetic"},
    ]
    idx = next((i for i, r in enumerate(dash)
                if r.get("Metric") == "Total cable route-km (national)"), len(dash) - 1) + 1
    d["dashboard"] = dash[:idx] + pole_rows + dash[idx:]

    if args.dry_run:
        print("\n[dry-run] pon_data.json NOT written.")
        return
    shutil.copyfile(PON, PON + ".bak11")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nWrote {PON} (backup pon_data.json.bak11).")


if __name__ == "__main__":
    main()
