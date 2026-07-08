"""Relocate Operator B OLT markers from the (synthetic) home-centroid to the
centroid of their own ODPs, which carry real PLN IconPlus fibre-plant
coordinates -- so OLT markers sit on their cable cluster instead of floating in
open ground. Reassigns each moved OLT to its nearest STO Tier-3 area.
Writes pon_data.json.bak4 backup. Operator A (STO) OLTs are untouched."""
import json, os, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
d = json.load(open(PON, encoding="utf-8"))
s = json.load(open(os.path.join(HERE, "malang_sto.json"), encoding="utf-8"))
shutil.copyfile(PON, PON + ".bak4")

T3 = s["tier3_access"]
def nearest_sto3(lat, lon):
    best, bd = None, 1e18
    for t in T3:
        dd = (t["latitude"] - lat) ** 2 + (t["longitude"] - lon) ** 2
        if dd < bd: bd, best = dd, t["sto_code"]
    return best

# centroid of ODPs per OLT (odps carry real coords + olt_id = "B-<host>")
pts = collections.defaultdict(lambda: [0.0, 0.0, 0])
for o in d["odps"]:
    if o.get("operator_code") != "B": continue
    oid = o.get("olt_id"); lat, lon = o.get("latitude"), o.get("longitude")
    if oid and lat is not None and lon is not None:
        p = pts[oid]; p[0] += lat; p[1] += lon; p[2] += 1

moved = 0
for olt in d["olts"]:
    if olt.get("operator_code") != "B": continue
    p = pts.get(olt["olt_id"])
    if p and p[2] > 0:
        lat, lon = round(p[0] / p[2], 6), round(p[1] / p[2], 6)
        olt["latitude"], olt["longitude"] = lat, lon
        olt["geo_source"] = "odp_centroid (real fibre plant)"
        olt["area_id"] = nearest_sto3(lat, lon)
        moved += 1

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print(f"Relocated {moved} Operator B OLTs to their ODP centroid.")
print("OLTs without ODPs (kept at home-centroid):",
      sum(1 for o in d["olts"] if o.get("operator_code") == "B"
          and o.get("geo_source") != "odp_centroid (real fibre plant)"))
