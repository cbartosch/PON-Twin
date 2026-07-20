"""Synthesize a cable model for Telkom (Operator A) OLTs and fix the dashboard
cable KPIs to a NATIONAL basis (Icon actual + Telkom synthetic).

Telkom's NET-02 feed gives OLT equipment + PON-port capacity but NO plant/cable.
Operator B (PLN IconPlus) DOES have real fibre plant (NET05), already rolled up
nationally into national_footprint.operator_B_cable_model. We reuse Icon's REAL
intensities to synthesize Telkom cable, so the estimate is grounded in measured
plant rather than invented:

  eta  = Icon cable-km per home passed        (national, actual)
       = route_km_total / homes_passed_est
  rho  = Icon homes passed per live PON port  (Malang, the only place Icon has
         both homepass and live ports)        = homepass_sum / live_ports_sum
  intensity = eta * rho  = cable-km per live PON port

Each Telkom OLT gets  km = live_pon_ports * intensity, split by Icon's role mix
(access / distribution / backbone_core). Everything is flagged SYNTHETIC.

Reads pon_data.json (must already contain the Icon national cable model), writes
pon_data.json.bak10.  Run:  python _synth_telkom_cables.py [--dry-run]
"""
import argparse
import collections
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")

# Malang granular cable rows -> replaced by national operator cable rows.
DROP_DASH = {
    "48-pair feeder cable", "24-pair distribution cable",
    "12-pair final branch cable", "Aerial drop cable",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    d = json.load(open(PON, encoding="utf-8"))
    nfb = d["national_footprint"]["operator_B_cable_model"]

    # --- Icon-derived intensities (all real measurements) --------------------
    eta = nfb["route_km_total"] / nfb["homes_passed_est"]         # km per home passed
    b_olts = [o for o in d["olts"] if o.get("operator_code") == "B"]
    hp = sum(float(o["homepass"]) for o in b_olts if o.get("homepass"))
    lp = sum(o.get("live_pon_ports") or 0 for o in b_olts if o.get("homepass"))
    rho = hp / lp                                                 # homes passed per live port
    intensity = eta * rho                                         # km per live PON port

    tot = nfb["route_km_total"]
    frac = {
        "access": nfb["route_km_access"] / tot,
        "distribution": nfb["route_km_distribution"] / tot,
        "backbone_core": nfb["route_km_backbone_core"] / tot,
    }
    print(f"eta (Icon km/home passed)      = {eta:.6f}")
    print(f"rho (Icon homes/live port,Mlg) = {rho:.4f}")
    print(f"=> cable-km per live PON port  = {intensity:.4f}")
    print(f"role mix: access={frac['access']:.4f} dist={frac['distribution']:.4f} "
          f"bb/core={frac['backbone_core']:.6f}")

    # --- attach synthetic cable_model to every Telkom OLT with ports ---------
    a_olts = [o for o in d["olts"] if o.get("operator_code") == "A"]
    area_roll = collections.defaultdict(lambda: collections.Counter())
    nat = collections.Counter()
    modeled = 0
    for o in a_olts:
        ports = o.get("live_pon_ports") or 0
        if not ports:
            o["cable_model"] = {"status": "no_live_ports",
                                "geo_basis": "synthetic (Icon intensity x live PON ports)"}
            continue
        km_total = ports * intensity
        km_a = km_total * frac["access"]
        km_d = km_total * frac["distribution"]
        km_b = km_total * frac["backbone_core"]
        o["cable_model"] = {
            "route_km_distribution": round(km_d, 2),
            "route_km_access": round(km_a, 2),
            "route_km_backbone_core": round(km_b, 4),
            "route_km_total": round(km_total, 2),
            "basis_live_pon_ports": ports,
            "synthetic": True,
            "source": ("SYNTHETIC: Telkom NET-02 has no plant; cable estimated as "
                       "live_pon_ports x Icon-derived intensity (Icon km/home-passed x "
                       "Icon homes/live-port), split by Icon national role mix."),
        }
        modeled += 1
        nat["route_km_total"] += km_total
        nat["route_km_access"] += km_a
        nat["route_km_distribution"] += km_d
        nat["route_km_backbone_core"] += km_b
        nat["live_pon_ports"] += ports
        aid = o.get("area_id")
        if aid:
            ar = area_roll[aid]
            ar["route_km_total"] += km_total
            ar["route_km_access"] += km_a
            ar["route_km_distribution"] += km_d
            ar["route_km_backbone_core"] += km_b

    # national synthetic A summary
    d["national_footprint"]["operator_A_cable_model"] = {
        "olts_with_model": modeled,
        "olts_total_a": len(a_olts),
        "basis_live_pon_ports": int(nat["live_pon_ports"]),
        "route_km_total": round(nat["route_km_total"], 1),
        "route_km_distribution": round(nat["route_km_distribution"], 1),
        "route_km_access": round(nat["route_km_access"], 1),
        "route_km_backbone_core": round(nat["route_km_backbone_core"], 1),
        "synthetic": True,
        "intensity_km_per_live_port": round(intensity, 5),
        "method": ("SYNTHETIC. Telkom NET-02 supplies OLT/port capacity only (no plant). "
                   "Cable = live_pon_ports x (Icon national km/home-passed x Icon Malang "
                   "homes/live-port), split by Icon national role mix. Grounded in real "
                   "IconPlus plant intensities; NOT measured Telkom plant."),
    }

    # roll up onto area records
    a_by_id = {a["area_id"]: a for a in d["areas"]}
    for aid, ar in area_roll.items():
        a = a_by_id.get(aid)
        if not a:
            continue
        a["operator_A_cable_model_synth"] = {
            "route_km_total": round(ar["route_km_total"], 1),
            "route_km_distribution": round(ar["route_km_distribution"], 1),
            "route_km_access": round(ar["route_km_access"], 1),
            "route_km_backbone_core": round(ar["route_km_backbone_core"], 1),
            "synthetic": True,
        }

    # --- fix dashboard cable KPIs to national basis --------------------------
    km_a_tot = round(nat["route_km_total"], 0)
    km_b_tot = round(nfb["route_km_total"], 0)
    dash = [r for r in d["dashboard"] if r.get("Metric") not in DROP_DASH]
    for r in dash:
        if r.get("Metric") == "Operator B route-km (national)":
            r["Metric"] = "Operator B cable route-km (actual)"
            r["Comment"] = (f"NET05 fibre, national: access {nfb['route_km_access']:,.0f} + "
                            f"distribution {nfb['route_km_distribution']:,.0f} km")
    idx = next((i for i, r in enumerate(dash)
                if r.get("Metric") == "Operator B cable route-km (actual)"), len(dash) - 1) + 1
    new_rows = [
        {"Metric": "Operator A cable route-km (synth)", "Value": km_a_tot, "Unit": "km",
         "Comment": f"Synthetic: {intensity:.3f} km/live-port (Icon-derived) x 433,279 ports"},
        {"Metric": "Total cable route-km (national)", "Value": round(km_a_tot + km_b_tot, 0),
         "Unit": "km", "Comment": "Icon actual + Telkom synthetic"},
    ]
    d["dashboard"] = dash[:idx] + new_rows + dash[idx:]

    print(f"\nTelkom OLTs given synthetic cable_model: {modeled:,} / {len(a_olts):,}")
    print(f"Telkom synthetic route-km: {km_a_tot:,.0f} "
          f"(access {nat['route_km_access']:,.0f} dist {nat['route_km_distribution']:,.0f})")
    print(f"Icon actual route-km:      {km_b_tot:,.0f}")
    print(f"National total route-km:   {km_a_tot + km_b_tot:,.0f}")

    if args.dry_run:
        print("\n[dry-run] pon_data.json NOT written.")
        return
    shutil.copyfile(PON, PON + ".bak10")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nWrote {PON} (backup pon_data.json.bak10).")


if __name__ == "__main__":
    main()
