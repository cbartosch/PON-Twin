"""Fallback: for Operator B OLTs still at the synthetic home-centroid, snap to
the nearest real ODP so no OLT marker floats off the fibre plant."""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
s = json.load(open(os.path.join(HERE, "malang_sto.json"), encoding="utf-8"))
d = json.load(open(PON, encoding="utf-8"))
T3 = s["tier3_access"]
def nearest_sto3(lat, lon):
    return min(T3, key=lambda t: (t["latitude"]-lat)**2 + (t["longitude"]-lon)**2)["sto_code"]

odps = [(o["latitude"], o["longitude"]) for o in d["odps"]
        if o.get("operator_code") == "B" and o.get("latitude") is not None]
fixed = 0
for olt in d["olts"]:
    if olt.get("operator_code") != "B": continue
    if olt.get("geo_source") == "odp_centroid (real fibre plant)": continue
    la, lo = olt.get("latitude"), olt.get("longitude")
    if la is None or not odps: continue
    nl, no = min(odps, key=lambda p: (p[0]-la)**2 + (p[1]-lo)**2)
    olt["latitude"], olt["longitude"] = nl, no
    olt["geo_source"] = "nearest_odp (real fibre plant)"
    olt["area_id"] = nearest_sto3(nl, no)
    fixed += 1

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print("Fallback-snapped", fixed, "OLTs to nearest ODP.")
import collections
print("B OLT geo_source:", dict(collections.Counter(
    o.get("geo_source") for o in d["olts"] if o.get("operator_code") == "B")))
