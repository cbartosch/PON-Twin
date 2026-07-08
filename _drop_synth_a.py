"""Drop ALL synthetic Operator A data (homes, ports, ODPs, splitters, cables,
drop_cables, topo_edges, port_summary) while KEEPING the 19 real Telkom STO
Tier-3 OLTs. Recompute per-area rollups (A demand now 0) and dashboard.
Awaiting real Operator A input. Writes pon_data.json.bak3 backup first."""
import json, os, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
d = json.load(open(PON, encoding="utf-8"))
shutil.copyfile(PON, PON + ".bak3")

# Keep A only in 'olts' (real STO sites). Strip synthetic A everywhere else.
STRIP = ("homes", "pon_ports", "port_summary", "splitters", "odps",
         "cables", "drop_cables", "topo_edges", "poles")
before = {k: sum(1 for x in d[k] if x.get("operator_code") == "A") for k in STRIP}
for k in STRIP:
    d[k] = [x for x in d[k] if x.get("operator_code") != "A"]

# --- recompute per-area rollups (A demand = 0 now) ---------------------------
b_live = collections.Counter(); b_spare = collections.Counter()
for o in d["olts"]:
    if o.get("operator_code") == "B":
        b_live[o["area_id"]] += o.get("live_pon_ports") or 0
        b_spare[o["area_id"]] += o.get("spare_pon_ports") or 0
b_conn = collections.Counter()
for h in d["homes"]:
    if h.get("connected_status") == "Connected" and h.get("operator_code") == "B":
        b_conn[h["area_id"]] += 1

for a in d["areas"]:
    aid = a["area_id"]
    a["operator_A_live_ports"] = 0; a["operator_A_spare_ports"] = 0
    a["connected_homes_operator_A"] = 0
    a["operator_B_live_ports"] = b_live[aid]; a["operator_B_spare_ports"] = b_spare[aid]
    a["connected_homes_operator_B"] = b_conn[aid]
    a["area_live_ports_total"] = b_live[aid]; a["area_spare_ports_total"] = b_spare[aid]
    tot = b_conn[aid]
    a["connected_homes_total"] = tot
    a["operator_A_connected_share"] = 0.0
    a["operator_B_connected_share"] = 1.0 if tot else 0.0
    if tot == 0:
        a["dominance_test"] = "No modeled demand"
        a["archetype"] = "STO access only (no modeled homes)"
    else:
        a["dominance_test"] = "B only (A pending real data)"
        a["archetype"] = "Operator B only (A awaiting real data)"

# --- dashboard rebuild -------------------------------------------------------
def n(coll, code=None):
    return sum(1 for x in d[coll] if code is None or x.get("operator_code") == code)
conn_homes = sum(1 for h in d["homes"] if h.get("connected_status") == "Connected")
live_ports = sum(a["area_live_ports_total"] for a in d["areas"])
spare_ports = sum(a["area_spare_ports_total"] for a in d["areas"])
area_ids = tuple(a["area_id"] for a in d["areas"])
head = [m for m in d["dashboard"]
        if m["Metric"] != "Area" and not str(m["Metric"]).startswith(area_ids)]
new_dash = []
for m in head:
    metric = m["Metric"]
    if metric == "OLTs": m["Value"] = n("olts"); m["Comment"] = f'{n("olts","A")} A (STO Tier-3, no demand yet) + {n("olts","B")} B (PLN IconPlus)'
    elif metric == "Live PON ports": m["Value"] = live_ports; m["Comment"] = "Operator B actual only"
    elif metric == "Spare PON ports": m["Value"] = spare_ports
    elif metric == "Connected homes": m["Value"] = conn_homes; m["Comment"] = "Operator B actual only"
    elif metric == "ODPs / secondary splitters": m["Value"] = n("odps")
    elif metric == "Aerial poles": m["Value"] = n("poles")
    elif metric == "Primary splitters": m["Value"] = n("splitters")
    new_dash.append(m)
new_dash.append({"Metric": "Operator A OLTs (STO Tier-3)", "Value": n("olts", "A"), "Unit": "ea",
                 "Comment": "Real STO sites; homes/ports awaiting real input"})
new_dash.append({"Metric": "Operator A synthetic data", "Value": "DROPPED", "Unit": "",
                 "Comment": "Awaiting real Operator A input"})
new_dash.append({"Metric": "Area", "Value": "Archetype", "Unit": "A homes / B homes", "Comment": "Tier-2 parent"})
for a in d["areas"]:
    new_dash.append({"Metric": a["area_id"], "Value": a["archetype"],
                     "Unit": f'0 / {a["connected_homes_operator_B"]}',
                     "Comment": f'{a["area_name"]} <- {a["tier2_parent_code"]}'})
d["dashboard"] = new_dash

d["structure_note"]["operator_A"] = (
    "Operator A = real Telkom STO Tier-3 OLT sites only (19). ALL synthetic A "
    "homes/ports/ODPs/splitters/cables dropped. Awaiting real Operator A input.")

json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
print("Dropped synthetic A per collection:", before)
print("Now: A OLTs=%d (real STO)  B OLTs=%d  homes=%d (all B)  odps=%d  poles=%d" % (
    n("olts", "A"), n("olts", "B"), n("homes"), n("odps"), n("poles")))
print("A records remaining outside olts:",
      {k: sum(1 for x in d[k] if x.get("operator_code") == "A") for k in STRIP})
