"""Restructure the twin around real STO Tier-3 areas.

- Drop the 4 synthetic archetype areas (MAL-AR-01..04).
- Create 19 areas, one per real Telkom STO Tier-3 access site (with Tier-2 parent).
- Replace the 3 synthetic Operator A OLTs with all 19 Tier-3 STO sites as
  Operator A (Telkom) OLTs, located at their real coordinates.
- Reassign every geolocated asset (A + real B OLTs / ODPs / homes / poles /
  cables) to its nearest STO Tier-3 area.
- Recompute per-area operator port/home rollups, shares, dominance, archetype,
  and rebuild the dashboard.
Writes pon_data.json.bak2 backup first. Operator B actual data is preserved."""
import json, os, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
STO = os.path.join(HERE, "malang_sto.json")

d = json.load(open(PON, encoding="utf-8"))
s = json.load(open(STO, encoding="utf-8"))
shutil.copyfile(PON, PON + ".bak2")

t3 = s["tier3_access"]
t2_by_code = {t["sto_code"]: t for t in s["tier2_aggregation"]}

def nearest_sto3(lat, lon):
    best, bd = None, 1e18
    for t in t3:
        dd = (t["latitude"] - lat) ** 2 + (t["longitude"] - lon) ** 2
        if dd < bd:
            bd, best = dd, t["sto_code"]
    return best

# --- 1) build 19 STO3 areas --------------------------------------------------
areas = []
for t in t3:
    parent = t2_by_code.get(t.get("tier2_parent"), {})
    areas.append({
        "area_id": t["sto_code"], "area_name": t["sto_name"].title(),
        "sto_name_official": t.get("sto_name_official"),
        "archetype": None, "tier": 3,
        "tier2_parent_code": t.get("tier2_parent"),
        "tier2_parent_name": parent.get("sto_name"),
        "datel": t.get("datel"), "witel": t.get("witel"),
        "anchor_latitude": t["latitude"], "anchor_longitude": t["longitude"],
        "operator_A_live_ports": 0, "operator_A_spare_ports": 0,
        "operator_B_live_ports": 0, "operator_B_spare_ports": 0,
        "area_live_ports_total": 0, "area_spare_ports_total": 0,
        "connected_homes_operator_A": 0, "connected_homes_operator_B": 0,
        "connected_homes_total": 0,
        "operator_A_connected_share": 0.0, "operator_B_connected_share": 0.0,
        "dominance_test": None,
        "notes": f"Real Telkom STO Tier-3 access area ({t['sto_code']}); "
                 f"Tier-2 parent {t.get('tier2_parent')}.",
    })
d["areas"] = areas
area_name = {a["area_id"]: a["area_name"] for a in areas}

# --- 2) replace synthetic A OLTs with 19 Tier-3 STO OLTs ---------------------
d["olts"] = [o for o in d["olts"] if o.get("operator_code") != "A"]
for t in t3:
    code = t["sto_code"]
    d["olts"].append({
        "olt_id": f"A-STO-{code}", "operator": "Operator A", "operator_code": "A",
        "area_id": code, "area_name": area_name[code], "archetype": None,
        "latitude": t["latitude"], "longitude": t["longitude"],
        "live_pon_ports": None, "spare_pon_ports": None, "total_pon_ports": None,
        "olt_role": "Access OLT (Telkom STO Tier-3)",
        "deployment_status": "Actual (Telkom STO Tier-3)",
        "site_type": "Telkom STO access office", "technology": "GPON",
        "power_redundancy": "Telkom STO (actual)",
        "sto_code": code, "sto_name_official": t.get("sto_name_official"),
        "tier2_parent_code": t.get("tier2_parent"),
        "notes": "Operator A (Telkom) access OLT = real STO Tier-3 site. "
                 "Modeled A ports/homes retained separately as demand.",
    })

# --- 3) reassign area for every geolocated record ----------------------------
def reloc(rec, latk="latitude", lonk="longitude"):
    lat, lon = rec.get(latk), rec.get(lonk)
    if lat is not None and lon is not None:
        rec["area_id"] = nearest_sto3(lat, lon)
        if "area_name" in rec:
            rec["area_name"] = area_name[rec["area_id"]]
    return rec

for coll in ("olts", "splitters", "odps", "homes", "poles"):
    for rec in d[coll]:
        reloc(rec)
for c in d["cables"]:
    reloc(c, "from_latitude", "from_longitude")
for dc in d["drop_cables"]:
    reloc(dc, "from_latitude", "from_longitude")

# lookups for records without their own coordinates
olt_area = {o["olt_id"]: o["area_id"] for o in d["olts"]}
home_area = {h["home_id"]: h["area_id"] for h in d["homes"]}
odp_area = {o["odp_id"]: o["area_id"] for o in d["odps"]}
def any_area(*ids):
    for i in ids:
        for m in (olt_area, home_area, odp_area):
            if i in m:
                return m[i]
    return None

for p in d["pon_ports"]:
    na = olt_area.get(p.get("olt_id"))
    if na: p["area_id"] = na; p["area_name"] = area_name[na]
for p in d["port_summary"]:
    na = olt_area.get(p.get("olt_id"))
    if na: p["area_id"] = na
for e in d["topo_edges"]:
    na = any_area(e.get("source_asset_id"), e.get("target_asset_id"))
    if na: e["area_id"] = na

# --- 4) recompute per-area rollups -------------------------------------------
# A ports from modeled pon_ports; B ports from real B OLT fields.
a_live = collections.Counter(); a_spare = collections.Counter()
for p in d["pon_ports"]:
    if p.get("operator_code") != "A": continue
    (a_live if p.get("port_status") == "Live" else a_spare)[p["area_id"]] += 1
b_live = collections.Counter(); b_spare = collections.Counter()
for o in d["olts"]:
    if o.get("operator_code") == "B":
        b_live[o["area_id"]] += o.get("live_pon_ports") or 0
        b_spare[o["area_id"]] += o.get("spare_pon_ports") or 0
a_conn = collections.Counter(); b_conn = collections.Counter()
for h in d["homes"]:
    if h.get("connected_status") != "Connected": continue
    (a_conn if h.get("operator_code") == "A" else b_conn)[h["area_id"]] += 1

for a in areas:
    aid = a["area_id"]
    a["operator_A_live_ports"] = a_live[aid]; a["operator_A_spare_ports"] = a_spare[aid]
    a["operator_B_live_ports"] = b_live[aid]; a["operator_B_spare_ports"] = b_spare[aid]
    a["area_live_ports_total"] = a_live[aid] + b_live[aid]
    a["area_spare_ports_total"] = a_spare[aid] + b_spare[aid]
    ca, cb = a_conn[aid], b_conn[aid]; tot = ca + cb
    a["connected_homes_operator_A"] = ca; a["connected_homes_operator_B"] = cb
    a["connected_homes_total"] = tot
    sa = round(ca / tot, 4) if tot else 0.0
    sb = round(cb / tot, 4) if tot else 0.0
    a["operator_A_connected_share"] = sa; a["operator_B_connected_share"] = sb
    if tot == 0:
        a["dominance_test"] = "No modeled demand"; a["archetype"] = "STO access only (no modeled homes)"
    elif sa > 0.55:
        a["dominance_test"] = "A >55%"; a["archetype"] = "Telkom (A) dominant"
    elif sb > 0.55:
        a["dominance_test"] = "B >55%"; a["archetype"] = "Operator B dominant"
    else:
        a["dominance_test"] = "Contested"; a["archetype"] = "Contested overlap"

# propagate archetype onto olts/homes for their area
arch = {a["area_id"]: a["archetype"] for a in areas}
for coll in ("olts", "homes"):
    for rec in d[coll]:
        if "archetype" in rec:
            rec["archetype"] = arch.get(rec.get("area_id"))

# --- 5) dashboard rebuild ----------------------------------------------------
def n(coll, code=None):
    return sum(1 for x in d[coll] if code is None or x.get("operator_code") == code)
conn_homes = sum(1 for h in d["homes"] if h.get("connected_status") == "Connected")
live_ports = sum(a["area_live_ports_total"] for a in areas)
spare_ports = sum(a["area_spare_ports_total"] for a in areas)
head = [m for m in d["dashboard"] if not str(m["Metric"]).startswith(("MAL-AR",))
        and m["Metric"] not in ("Area",) and not str(m["Metric"]).startswith(tuple(a["area_id"] for a in areas))]
new_dash = []
for m in head:
    metric = m["Metric"]
    if metric == "Areas": m["Value"] = len(areas); m["Comment"] = "Real STO Tier-3 access areas"
    elif metric == "OLTs": m["Value"] = n("olts"); m["Comment"] = f'{n("olts","A")} A (STO Tier-3) + {n("olts","B")} B (PLN IconPlus)'
    elif metric == "Live PON ports": m["Value"] = live_ports
    elif metric == "Spare PON ports": m["Value"] = spare_ports
    elif metric == "Connected homes": m["Value"] = conn_homes
    elif metric == "ODPs / secondary splitters": m["Value"] = n("odps")
    elif metric == "Aerial poles": m["Value"] = n("poles")
    new_dash.append(m)
new_dash.append({"Metric": "Operator A OLTs (STO Tier-3)", "Value": n("olts", "A"), "Unit": "ea",
                 "Comment": "Real Telkom STO access sites"})
new_dash.append({"Metric": "Area", "Value": "Archetype", "Unit": "A homes / B homes", "Comment": "Tier-2 parent"})
for a in areas:
    new_dash.append({"Metric": a["area_id"], "Value": a["archetype"],
                     "Unit": f'{a["connected_homes_operator_A"]} / {a["connected_homes_operator_B"]}',
                     "Comment": f'{a["area_name"]} <- {a["tier2_parent_code"]}'})
d["dashboard"] = new_dash

d["structure_note"] = {
    "areas": "Real Telkom STO Tier-3 access areas (19); 4 synthetic archetype "
             "areas dropped.",
    "operator_A": "All Operator A OLTs = real Telkom STO Tier-3 sites (19). "
                  "Modeled A homes/ports/ODPs retained as demand, reassigned to "
                  "nearest STO Tier-3 area.",
    "operator_B": "Real PLN IconPlus FTTH (Malang), reassigned to nearest STO "
                  "Tier-3 area.",
}

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print("Rebuilt around %d STO Tier-3 areas." % len(areas))
print("OLTs: total=%d A=%d B=%d | ODPs=%d homes=%d poles=%d | connected=%d" % (
    n("olts"), n("olts", "A"), n("olts", "B"), n("odps"), n("homes"), n("poles"), conn_homes))
print("Per-area (A homes / B homes | dominance):")
for a in sorted(areas, key=lambda x: -x["connected_homes_total"]):
    print("  %-4s %-16s A=%-4d B=%-5d %s" % (
        a["area_id"], a["area_name"], a["connected_homes_operator_A"],
        a["connected_homes_operator_B"], a["dominance_test"]))
