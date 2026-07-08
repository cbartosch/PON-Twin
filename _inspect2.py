import json, os
HERE = os.path.dirname(os.path.abspath(__file__))
s = json.load(open(os.path.join(HERE, "malang_sto.json"), encoding="utf-8"))
print("=== Tier3 access (%d) ===" % len(s["tier3_access"]))
for t in s["tier3_access"]:
    print("  %-5s %-18s (%.4f,%.4f) parent=%s" % (
        t["sto_code"], t["sto_name"], t["latitude"], t["longitude"], t.get("tier2_parent")))
print("=== Tier2 (%d) ===" % len(s["tier2_aggregation"]))
for t in s["tier2_aggregation"]:
    print("  %-5s %-18s (%.4f,%.4f)" % (t["sto_code"], t["sto_name"], t["latitude"], t["longitude"]))
d = json.load(open(os.path.join(HERE, "pon_data.json"), encoding="utf-8"))
print("=== Current Operator A OLTs ===")
for o in d["olts"]:
    if o.get("operator_code") == "A":
        print(" ", o["olt_id"], o["area_id"], o.get("latitude"), o.get("longitude"),
              o.get("live_pon_ports"), "/", o.get("spare_pon_ports"))
print("A pon_ports:", sum(1 for p in d["pon_ports"] if p.get("operator_code") == "A"))
print("A homes:", sum(1 for h in d["homes"] if h.get("operator_code") == "A"))
print("A odps:", sum(1 for x in d["odps"] if x.get("operator_code") == "A"))
print("A splitters:", sum(1 for x in d["splitters"] if x.get("operator_code") == "A"))
