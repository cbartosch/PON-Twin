"""Merge real Operator B (op_b_real.json) into the twin (pon_data.json).
Removes all synthetic operator_code=='B' records, inserts real B OLTs / ODPs /
homes / poles (Malang-scoped, PLN IconPlus), then recomputes area B rollups,
shares, dominance, dashboard metrics and a B cable/pole summary.
Synthetic Operator A is left untouched. A backup pon_data.json.bak is written."""
import json, os, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
REAL = os.path.join(HERE, "op_b_real.json")

d = json.load(open(PON, encoding="utf-8"))
b = json.load(open(REAL, encoding="utf-8"))
shutil.copyfile(PON, PON + ".bak")

area_by_id = {a["area_id"]: a for a in d["areas"]}
def aname(aid): return area_by_id.get(aid, {}).get("area_name", "")
def aarch(aid): return area_by_id.get(aid, {}).get("archetype", "")

# --- 1) strip synthetic B from every list collection -------------------------
for k, v in d.items():
    if isinstance(v, list):
        d[k] = [x for x in v if not (isinstance(x, dict) and x.get("operator_code") == "B")]

# --- 2) insert real B OLTs ---------------------------------------------------
for o in b["olts"]:
    aid = o["area_id"]
    d["olts"].append({
        "olt_id": o["olt_id"], "operator": "Operator B", "operator_code": "B",
        "area_id": aid, "area_name": aname(aid), "archetype": aarch(aid),
        "latitude": o["latitude"], "longitude": o["longitude"],
        "live_pon_ports": o["live_pon_ports"], "spare_pon_ports": o["spare_pon_ports"],
        "total_pon_ports": o["total_pon_ports"],
        "olt_role": o.get("olt_role", "Access OLT"),
        "deployment_status": o.get("deployment_status", "Actual (PLN IconPlus)"),
        "site_type": o.get("site_type", "PLN IconPlus OLT"),
        "technology": o.get("technology", "GPON"),
        "power_redundancy": "PLN grid (actual)",
        "hostname": o.get("hostname"), "geo_source": o.get("geo_source"),
        "connected_homes": o.get("connected_homes"), "homepass": o.get("homepass"),
        "homeconnected": o.get("homeconnected"),
        "notes": "Actual Operator B OLT (PLN IconPlus FTTH DRL), Malang-scoped.",
    })

# --- 3) insert real B ODPs (from splitters) ----------------------------------
for s in b["splitters"]:
    aid = s["area_id"]
    d["odps"].append({
        "odp_id": s["odp_id"], "secondary_splitter_id": s["odp_id"],
        "operator": "Operator B", "operator_code": "B", "area_id": aid,
        "pon_port_id": None, "primary_splitter_id": s.get("fdt_id"),
        "splitter_stage": "ODP", "splitter_ratio": s.get("splitter_ratio"),
        "homes_served": None, "attached_pole_id": None,
        "latitude": s["latitude"], "longitude": s["longitude"],
        "olt_id": f"B-{s['olt_hostname']}" if s.get("olt_hostname") else None,
        "deployment": "Actual (PLN IconPlus)", "inventory_status": "Actual",
    })

# --- 4) insert real B homes --------------------------------------------------
for h in b["homes"]:
    aid = h["area_id"]
    d["homes"].append({
        "home_id": h["home_id"], "operator": "Operator B", "operator_code": "B",
        "area_id": aid, "area_name": aname(aid), "archetype": aarch(aid),
        "pon_port_id": None, "odp_id": h.get("fat_id"),
        "connected_status": "Connected" if h.get("connected") else "Not connected",
        "latitude": h["latitude"], "longitude": h["longitude"],
        "drop_type": "Aerial drop", "olt_hostname": h.get("olt_hostname"),
        "kabupaten": h.get("kabupaten"), "kecamatan": h.get("kecamatan"),
        "kelurahan": h.get("kelurahan"), "service_status": h.get("service_status"),
        "inventory_status": "Actual (PLN IconPlus)",
    })

# --- 5) insert real B poles (sample) -----------------------------------------
for p in b["poles"]["sample"]:
    aid = p["area_id"]
    d["poles"].append({
        "pole_id": p["pole_id"], "operator": "Operator B", "operator_code": "B",
        "area_id": aid, "route_type": p.get("category", ""), "pole_role": "FTTH pole",
        "latitude": p["latitude"], "longitude": p["longitude"],
        "attached_asset_id": None, "pole_material": p.get("owner", ""),
        "deployment": "Actual (PLN IconPlus)", "inventory_status": "Actual (sampled)",
    })

# --- 6) recompute per-area B rollups + shares + dominance --------------------
b_live = collections.Counter(); b_spare = collections.Counter(); b_conn = collections.Counter()
for o in b["olts"]:
    b_live[o["area_id"]] += o["live_pon_ports"]; b_spare[o["area_id"]] += o["spare_pon_ports"]
for h in b["homes"]:
    if h.get("connected"): b_conn[h["area_id"]] += 1

for a in d["areas"]:
    aid = a["area_id"]
    a["operator_B_live_ports"] = b_live[aid]
    a["operator_B_spare_ports"] = b_spare[aid]
    a["connected_homes_operator_B"] = b_conn[aid]
    a["area_live_ports_total"] = a["operator_A_live_ports"] + b_live[aid]
    a["area_spare_ports_total"] = a["operator_A_spare_ports"] + b_spare[aid]
    ca = a["connected_homes_operator_A"]; cb = b_conn[aid]; tot = ca + cb
    a["connected_homes_total"] = tot
    a["operator_A_connected_share"] = round(ca / tot, 4) if tot else 0.0
    a["operator_B_connected_share"] = round(cb / tot, 4) if tot else 0.0
    sa = a["operator_A_connected_share"]; sb = a["operator_B_connected_share"]
    a["dominance_test"] = ("A >55%" if sa > 0.55 else "B >55%" if sb > 0.55 else "Contested")
    a["archetype"] = ("Operator A dominant" if sa > 0.55 else
                      "Operator B dominant" if sb > 0.55 else "Contested overlap")
    a["notes"] = (a.get("notes", "").split(";")[0] +
                  "; Operator B reconciled to actual PLN IconPlus FTTH (Malang).")

# --- 7) dashboard rebuild ----------------------------------------------------
def n(coll, code=None):
    return sum(1 for x in d[coll] if code is None or x.get("operator_code") == code)
live_ports = sum(o.get("live_pon_ports", 0) for o in d["olts"])
spare_ports = sum(o.get("spare_pon_ports", 0) for o in d["olts"])
conn_homes = sum(1 for h in d["homes"] if h.get("connected_status") == "Connected")
cs = b["cable_summary"]
head = [m for m in d["dashboard"] if not str(m["Metric"]).startswith("MAL-AR")
        and m["Metric"] != "Area"]
new_dash = []
for m in head:
    metric = m["Metric"]
    if metric == "OLTs": m["Value"] = n("olts")
    elif metric == "Live PON ports": m["Value"] = live_ports
    elif metric == "Spare PON ports": m["Value"] = spare_ports
    elif metric == "Connected homes": m["Value"] = conn_homes
    elif metric == "ODPs / secondary splitters": m["Value"] = n("odps")
    elif metric == "Aerial poles": m["Value"] = n("poles")
    new_dash.append(m)
new_dash += [
    {"Metric": "Operator B OLTs (actual)", "Value": n("olts", "B"), "Unit": "ea",
     "Comment": "PLN IconPlus FTTH, Malang-scoped"},
    {"Metric": "Operator B ODPs (actual)", "Value": n("odps", "B"), "Unit": "ea", "Comment": "NET04 splitters"},
    {"Metric": "Operator B homes (actual)", "Value": n("homes", "B"), "Unit": "home",
     "Comment": "NET07 ONT, Malang kabupaten"},
    {"Metric": "Operator B drop cable (actual)", "Value": cs["drop_km"], "Unit": "km", "Comment": "NET05 aggregate"},
    {"Metric": "Operator B distribution cable (actual)", "Value": cs["distribution_km"], "Unit": "km",
     "Comment": "NET05 aggregate"},
    {"Metric": "Operator B poles in Malang bbox", "Value": b["poles"]["count_bbox"], "Unit": "ea",
     "Comment": "NET06 (2000 sampled to map)"},
    {"Metric": "Area", "Value": "Archetype", "Unit": "A homes / B homes", "Comment": ""},
]
for a in d["areas"]:
    new_dash.append({"Metric": a["area_id"],
                     "Value": f'{a["archetype"]}',
                     "Unit": f'{a["connected_homes_operator_A"]} / {a["connected_homes_operator_B"]}',
                     "Comment": a["dominance_test"]})
d["dashboard"] = new_dash

# --- 8) attach B source metadata ---------------------------------------------
d["operator_b_source"] = {
    "source": b["source"], "scope_kabupaten": b["scope_kabupaten"],
    "counts": b["counts"], "cable_summary": cs,
    "note": "Real Operator B = PLN IconPlus FTTH DRL. OLT geo = centroid of its "
            "Malang ONT homes (anonymised hostnames don't join NET01). Homes/ODPs "
            "assigned to nearest of 4 synthetic area anchors. Poles/cables aggregated.",
}

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print("Merged. Totals now:")
for c in ["olts", "odps", "homes", "poles", "splitters"]:
    print(f"  {c}: total={n(c)}  A={n(c,'A')}  B={n(c,'B')}")
print("  connected homes:", conn_homes, " live ports:", live_ports, " spare:", spare_ports)
for a in d["areas"]:
    print(f'  {a["area_id"]}: A={a["connected_homes_operator_A"]} B={a["connected_homes_operator_B"]} '
          f'shareB={a["operator_B_connected_share"]} -> {a["dominance_test"]}')
