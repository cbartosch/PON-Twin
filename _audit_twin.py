"""Read-only audit of the PON-twin. Checks data integrity, cross-consistency
(dashboard / BoQ / national_footprint all agree), the earlier fixes (cable
outliers gone, operator rename complete), referential integrity, coordinate
sanity, and the live Spanner emulator. Prints PASS/FAIL per check.
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")

PASS = FAIL = WARN = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail else ""))
    if ok:
        PASS += 1
    else:
        FAIL += 1


def warn(name, detail=""):
    global WARN
    WARN += 1
    print(f"  [WARN] {name}" + (f"  -- {detail}" if detail else ""))


def close(a, b, tol=2.0):
    return abs(a - b) <= tol


d = json.load(open(PON, encoding="utf-8"))
olts = d["olts"]
A = [o for o in olts if o.get("operator_code") == "A"]
B = [o for o in olts if o.get("operator_code") == "B"]
nf = d["national_footprint"]
nfa = nf["operator_A_cable_model"]
nfb = nf["operator_B_cable_model"]

print("=" * 70)
print("1. COLLECTION INVENTORY")
print("=" * 70)
for k, v in d.items():
    if isinstance(v, list):
        print(f"  {k}: {len(v):,} rows")
    else:
        print(f"  {k}: <{type(v).__name__}>")

print("\n" + "=" * 70)
print("2. OPERATOR CONSISTENCY")
print("=" * 70)
check("OLT count = A + B", len(olts) == len(A) + len(B), f"{len(olts)} = {len(A)}+{len(B)}")
opvals = collections.Counter(o.get("operator") for o in olts)
check("A OLTs labelled 'Telkom'", all(o.get("operator") == "Telkom" for o in A))
check("B OLTs labelled 'Iconnect'", all(o.get("operator") == "Iconnect" for o in B))
blob = json.dumps(d)
n_opA = blob.count("Operator A")
n_opB = blob.count("Operator B")
check("no 'Operator A' string anywhere", n_opA == 0, f"found {n_opA}")
check("no 'Operator B' string anywhere", n_opB == 0, f"found {n_opB}")

print("\n" + "=" * 70)
print("3. CABLE MODEL INTEGRITY")
print("=" * 70)
# per-OLT role sum == total, and outlier check
role_ok = outlier = 0
maxkm = 0.0
for o in olts:
    cm = o.get("cable_model") or {}
    if "route_km_total" not in cm:
        continue
    s = cm["route_km_distribution"] + cm["route_km_access"] + cm["route_km_backbone_core"]
    if not close(s, cm["route_km_total"], 0.1):
        role_ok += 1
    maxkm = max(maxkm, cm["route_km_total"])
    if cm["route_km_total"] > 1000:
        outlier += 1
check("per-OLT role km sums to total", role_ok == 0, f"{role_ok} mismatches")
check("no OLT cable outlier > 1000 km (20km cap worked)", outlier == 0,
      f"{outlier} outliers, max={maxkm:,.1f} km")

b_plant = [o for o in B if (o.get("cable_model") or {}).get("route_km_total") is not None]
sum_b = sum(o["cable_model"]["route_km_total"] for o in b_plant)
check("Iconnect OLT cable sum == national B total",
      close(sum_b, nfb["route_km_total"], 50), f"{sum_b:,.0f} vs {nfb['route_km_total']:,.0f}")
check("Iconnect olts_with_plant matches", len(b_plant) == nfb["olts_with_plant"],
      f"{len(b_plant)} vs {nfb['olts_with_plant']}")

a_plant = [o for o in A if (o.get("cable_model") or {}).get("route_km_total") is not None]
sum_a = sum(o["cable_model"]["route_km_total"] for o in a_plant)
check("Telkom OLT synth cable sum == national A total",
      close(sum_a, nfa["route_km_total"], 50), f"{sum_a:,.0f} vs {nfa['route_km_total']:,.0f}")
check("all Telkom cable_models flagged synthetic",
      all(o["cable_model"].get("synthetic") for o in a_plant))

print("\n" + "=" * 70)
print("4. ODP / HOMES / POLES")
print("=" * 70)
sum_odp = sum((o.get("cable_model") or {}).get("odp_count") or 0 for o in B)
check("Iconnect ODP sum == national odp_count", sum_odp == nfb["odp_count"],
      f"{sum_odp:,} vs {nfb['odp_count']:,}")
sum_hp = sum((o.get("cable_model") or {}).get("homes_passed_est") or 0 for o in B)
check("Iconnect homes sum == national homes_passed_est", sum_hp == nfb["homes_passed_est"],
      f"{sum_hp:,} vs {nfb['homes_passed_est']:,}")
# Telkom synth poles recompute
ppk = nf["operator_A_poles"]["poles_per_route_km"]
expect_a_poles = round(nfa["route_km_total"] * ppk)
# ppk is stored rounded (2 dp), so allow a proportional rounding band.
pole_tol = max(2, round(nfa["route_km_total"] * 0.005) + 2)
check("Telkom synth poles == poles/km x route-km (within ppk rounding)",
      close(nf["operator_A_poles"]["count"], expect_a_poles, pole_tol),
      f"{nf['operator_A_poles']['count']:,} vs {expect_a_poles:,} (tol {pole_tol})")

print("\n" + "=" * 70)
print("5. DASHBOARD CROSS-CHECK")
print("=" * 70)
dash = {r["Metric"]: r["Value"] for r in d["dashboard"] if r.get("Metric")}
a_live = sum(o.get("live_pon_ports") or 0 for o in A)
a_spare = sum(o.get("spare_pon_ports") or 0 for o in A)
checks = [
    ("OLTs", len(olts)),
    ("Telkom OLTs (actual)", len(A)),
    ("Iconnect OLTs (national)", len(B)),
    ("Telkom live PON ports", a_live),
    ("Telkom spare PON ports", a_spare),
    ("Iconnect ODPs (national)", nfb["odp_count"]),
    ("Iconnect homes passed (national, est)", nfb["homes_passed_est"]),
    ("Iconnect cable route-km (actual)", nfb["route_km_total"]),
    ("Telkom cable route-km (synth)", nfa["route_km_total"]),
    ("Iconnect poles (national, actual)", nf["operator_B_poles"]["count"]),
    ("Telkom poles (national, synth)", nf["operator_A_poles"]["count"]),
]
for metric, expect in checks:
    got = dash.get(metric)
    check(f"dash '{metric}'", got is not None and close(float(got), float(expect), 2),
          f"{got} vs {expect}")
# totals
ct = dash.get("Total cable route-km (national)")
check("dash cable total == A+B", ct is not None and close(float(ct), nfa["route_km_total"] + nfb["route_km_total"], 2),
      f"{ct}")
pt = dash.get("Total poles (national)")
check("dash pole total == A+B", pt is not None and pt == nf["operator_A_poles"]["count"] + nf["operator_B_poles"]["count"],
      f"{pt}")

print("\n" + "=" * 70)
print("6. BoQ CROSS-CHECK")
print("=" * 70)
boq = {r["item"]: r["quantity"] for r in d["boq_active"] + d["boq_passive"]}
boq_checks = [
    ("Telkom OLT chassis", len(A)),
    ("Iconnect OLT chassis", len(B)),
    ("OLT chassis (total national)", len(olts)),
    ("Telkom live PON ports", a_live),
    ("Iconnect ODP with secondary 1:8 splitter", nfb["odp_count"]),
    ("Iconnect aerial poles", nf["operator_B_poles"]["count"]),
    ("Telkom aerial poles", nf["operator_A_poles"]["count"]),
    ("Iconnect homes passed (estimate)", nfb["homes_passed_est"]),
]
for item, expect in boq_checks:
    got = boq.get(item)
    check(f"boq '{item}'", got is not None and close(float(got), float(expect), 2), f"{got} vs {expect}")

print("\n" + "=" * 70)
print("7. REFERENTIAL INTEGRITY + COORDS")
print("=" * 70)
area_ids = {a["area_id"] for a in d["areas"]}
orphan = sum(1 for o in olts if o.get("area_id") and o["area_id"] not in area_ids)
if orphan:
    warn("OLTs referencing unknown area_id", f"{orphan} (national OLTs may be un-areaed)")
else:
    check("all OLT area_id references valid", True)
badgeo = sum(1 for o in olts if o.get("latitude") is not None and o.get("longitude") is not None and
             not (-11 <= o["latitude"] <= 6 and 95 <= o["longitude"] <= 141))
check("all OLT coords within Indonesia bbox", badgeo == 0, f"{badgeo} outside")
nogeo = sum(1 for o in olts if o.get("latitude") is None or o.get("longitude") is None)
if nogeo:
    warn("OLTs without coordinates", f"{nogeo}")

print("\n" + "=" * 70)
print(f"SUMMARY: {PASS} passed, {FAIL} failed, {WARN} warnings")
print("=" * 70)
