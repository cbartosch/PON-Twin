"""Revert the Operator B OLT marker snapping. Restores each B OLT to its
original home-centroid coordinate (from op_b_real.json) and geo_source, keeping
the full cable-route dataset intact. Reassigns area via nearest STO Tier-3."""
import json, os, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
d = json.load(open(PON, encoding="utf-8"))
b = json.load(open(os.path.join(HERE, "op_b_real.json"), encoding="utf-8"))
s = json.load(open(os.path.join(HERE, "malang_sto.json"), encoding="utf-8"))
T3 = s["tier3_access"]
def nearest_sto3(lat, lon):
    return min(T3, key=lambda t: (t["latitude"]-lat)**2 + (t["longitude"]-lon)**2)["sto_code"]

orig = {o["olt_id"]: o for o in b["olts"]}
reverted = 0
for olt in d["olts"]:
    if olt.get("operator_code") != "B":
        continue
    src = orig.get(olt["olt_id"])
    if not src or src.get("latitude") is None:
        continue
    olt["latitude"], olt["longitude"] = src["latitude"], src["longitude"]
    olt["geo_source"] = src.get("geo_source", "home_centroid")
    olt["area_id"] = nearest_sto3(src["latitude"], src["longitude"])
    reverted += 1

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print("Reverted", reverted, "Operator B OLTs to home-centroid.")
print("B OLT geo_source:", dict(collections.Counter(
    o.get("geo_source") for o in d["olts"] if o.get("operator_code") == "B")))
print("cables intact:", len(d["cables"]))
