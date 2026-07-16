import json, synergy
D = json.load(open('pon_data.json', encoding='utf-8'))
for k in ("areas","olts","cables","homes","odps","splitters"):
    D.setdefault(k, [])

print("== catalogue ==")
cat = synergy.catalogue()
print("levers:", len(cat["levers"]), "weights sum:", round(sum(cat["certainty_weights"].values()),3))

print("\n== drivers national ==")
dr = synergy.twin_drivers(D, "national")
print("label:", dr["region_label"], "olts:", dr["drivers"]["olts"], "homes:", dr["drivers"]["homes_passed"], "fat:", dr["drivers"]["fat_count"]["value"])

print("\n== analyze olt_retire_redundant / national ==")
r = synergy.analyze_lever(D, "olt_retire_redundant", "national")
print("driver", r["twin_evidence"]["driver_volume"], r["twin_evidence"]["driver_source"],
      "twin_grounded", r["twin_evidence"]["twin_grounded_volume"])
print("gross", r["estimate_idr_bn"]["gross_synergy"], "net", r["estimate_idr_bn"]["net_synergy"],
      "bankable", r["estimate_idr_bn"]["bankable_synergy"], "certainty", r["estimate_idr_bn"]["certainty_score"])
print("derived_from_synthetic", r["derived_from_synthetic"])

print("\n== analyze pe_retire (synthetic vol) / SBU ==")
r2 = synergy.analyze_lever(D, "pe_retire", "SBU-JAWA-BAGIAN-TIMUR")
print("driver", r2["twin_evidence"]["driver"], r2["twin_evidence"]["driver_volume"],
      "source", r2["twin_evidence"]["driver_source"], "grounded", r2["twin_evidence"]["twin_grounded_volume"])
print("flag:", r2["flag"])

print("\n== summary national totals ==")
s = synergy.summary(D, "national")
print(s["portfolio_totals_idr_bn"])
print("snapshot", s["twin_volume_snapshot"])
print("flag:", s["flag"])

print("\n== bad lever ==")
print(synergy.analyze_lever(D, "nope").get("error"))
