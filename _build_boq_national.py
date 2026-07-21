"""Rebuild the Bill of Quantities (boq_active / boq_passive) from the NATIONAL
twin. The previous BoQ still held the original synthetic Malang placeholders
(6 OLT chassis, 16 PON ports, 26.9 km cable, 3,478 poles), which are wrong now
that the twin carries national plant.

Quantities are sourced from national_footprint + OLT/port counts and clearly
tagged actual (measured DRL/NET plant) vs synthetic (Telkom estimated from
Icon-derived intensities). Telkom has no measured plant; Iconnect (PLN IconPlus)
national PON-port counts are not in the DRL feed (only the Malang sample), so
port rows are Telkom-only.

Reads/writes pon_data.json (backup .bak13).  Run: python _build_boq_national.py
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")


def r0(x):
    return round(x, 0)


def main():
    d = json.load(open(PON, encoding="utf-8"))
    nf = d["national_footprint"]
    b = nf["operator_B_cable_model"]      # Iconnect actual cable
    a = nf["operator_A_cable_model"]      # Telkom synthetic cable
    bp = nf["operator_B_poles"]           # Iconnect actual poles
    ap = nf["operator_A_poles"]           # Telkom synthetic poles

    n_a_olt = sum(1 for o in d["olts"] if o.get("operator_code") == "A")
    n_b_olt = sum(1 for o in d["olts"] if o.get("operator_code") == "B")
    a_live = sum(o.get("live_pon_ports") or 0 for o in d["olts"] if o.get("operator_code") == "A")
    a_spare = sum(o.get("spare_pon_ports") or 0 for o in d["olts"] if o.get("operator_code") == "A")

    def act(i, item, unit, qty, basis, src, notes):
        return {"boq_item_id": i, "inventory_group": "Active", "item": item, "unit": unit,
                "quantity": qty, "calculation_basis": basis, "source_sheet": src, "notes": notes}

    def pas(i, item, unit, qty, basis, src, notes):
        return {"boq_item_id": i, "inventory_group": "Passive", "item": item, "unit": unit,
                "quantity": qty, "calculation_basis": basis, "source_sheet": src, "notes": notes}

    d["boq_active"] = [
        act("A-BOQ-001", "Telkom OLT chassis", "ea", n_a_olt,
            "Count of Telkom OLT equipment records", "NET-02 Active OLT Equipment",
            "ACTUAL (Telkom NET-02)."),
        act("A-BOQ-002", "Iconnect OLT chassis", "ea", n_b_olt,
            "Count of Iconnect OLT records (national footprint)", "DRL NET-01 / national footprint",
            "ACTUAL (PLN IconPlus)."),
        act("A-BOQ-003", "OLT chassis (total national)", "ea", n_a_olt + n_b_olt,
            "Telkom + Iconnect OLTs", "derived", "ACTUAL."),
        act("A-BOQ-004", "Telkom live PON ports", "port", a_live,
            "Sum of live PON ports across Telkom OLTs", "NET-02 vendor module sheets",
            "ACTUAL (Telkom). Iconnect national PON ports not in DRL feed (Malang sample only)."),
        act("A-BOQ-005", "Telkom spare PON ports", "port", a_spare,
            "Sum of spare PON ports across Telkom OLTs", "NET-02 vendor module sheets",
            "ACTUAL (Telkom)."),
    ]

    cable_total = r0(a["route_km_total"] + b["route_km_total"])
    d["boq_passive"] = [
        pas("P-BOQ-001", "Iconnect ODP with secondary 1:8 splitter", "ea", b["odp_count"],
            "Count of DRL serving-area FAT points", "DRL_ServingArea_Polygon / NET04",
            "ACTUAL (PLN IconPlus)."),
        pas("P-BOQ-002", "Iconnect aerial poles", "ea", bp["count"],
            "Count of NET06 FTTH pole records", "NET06 Ducts and poles",
            "ACTUAL (PLN IconPlus)."),
        pas("P-BOQ-003", "Telkom aerial poles", "ea", ap["count"],
            f"Icon poles/route-km ({ap['poles_per_route_km']}) x Telkom route-km", "synthetic",
            "SYNTHETIC (Telkom has no measured pole plant)."),
        pas("P-BOQ-004", "Iconnect access / drop fibre cable", "km", r0(b["route_km_access"]),
            "NET05 segments, role=Access", "NET05 Fibre Cable and segments",
            "ACTUAL (PLN IconPlus)."),
        pas("P-BOQ-005", "Iconnect distribution / feeder fibre cable", "km", r0(b["route_km_distribution"]),
            "NET05 segments, role=Distribution", "NET05 Fibre Cable and segments",
            "ACTUAL (PLN IconPlus)."),
        pas("P-BOQ-006", "Iconnect backbone / core fibre cable", "km", r0(b["route_km_backbone_core"]),
            "NET05 segments, role=Backbone/Core", "NET05 Fibre Cable and segments",
            "ACTUAL (PLN IconPlus)."),
        pas("P-BOQ-007", "Telkom access / drop fibre cable", "km", r0(a["route_km_access"]),
            "Synthetic route-km x Icon access role share", "synthetic",
            "SYNTHETIC (Telkom estimated from Icon intensity)."),
        pas("P-BOQ-008", "Telkom distribution / feeder fibre cable", "km", r0(a["route_km_distribution"]),
            "Synthetic route-km x Icon distribution role share", "synthetic",
            "SYNTHETIC (Telkom estimated from Icon intensity)."),
        pas("P-BOQ-009", "Total fibre cable route (national)", "km", cable_total,
            "Iconnect actual + Telkom synthetic", "derived",
            "Mixed: Iconnect ACTUAL + Telkom SYNTHETIC."),
        pas("P-BOQ-010", "Iconnect homes passed (estimate)", "home", b["homes_passed_est"],
            "Sum of FAT splitter-ratio capacity", "DRL_ServingArea_Polygon",
            "ESTIMATE (PLN IconPlus)."),
    ]

    shutil.copyfile(PON, PON + ".bak13")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
    print("Rebuilt BoQ from national footprint (backup .bak13).")
    for coll in ("boq_active", "boq_passive"):
        print(f"\n{coll}:")
        for r in d[coll]:
            print(f"  {r['item']}: {r['quantity']:,} {r['unit']}")


if __name__ == "__main__":
    main()
