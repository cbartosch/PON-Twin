"""
Malang PON Digital Twin — MCP Server
Exposes tools for an AI agent to query the full topology and inventory.
"""
import json, os, math
from pathlib import Path
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types

# ── Load data ────────────────────────────────────────────────────────────────
# Source of truth is the Cloud Spanner (emulator) database when configured;
# otherwise fall back to the local JSON fixtures (portable / no-Docker path).
DATA_PATH = Path(__file__).parent / "pon_data.json"
STO_PATH  = Path(__file__).parent / "malang_sto.json"
DATA_BACKEND = "json"          # overwritten to "spanner" on success below
_SPANNER_STO = None            # STO blob loaded from Spanner (if any)

def _load_json():
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)

def _load_data():
    """Return (D, backend). Prefer Spanner; fall back to JSON on any failure."""
    global _SPANNER_STO
    try:
        import spanner_store as ss
        if ss.spanner_configured():
            data, sto = ss.load_twin()
            if data:
                _SPANNER_STO = sto
                return data, "spanner"
    except Exception as e:                       # noqa: BLE001
        import sys as _sys
        print(f"[server] Spanner load failed ({e}); using JSON fallback.", file=_sys.stderr)
    return _load_json(), "json"

D, DATA_BACKEND = _load_data()

# Ensure every expected collection exists (empty collections are absent from the
# Spanner load once all their rows are dropped, e.g. synthetic Operator A data).
for _k in ("areas", "olts", "pon_ports", "port_summary", "splitters", "odps",
           "poles", "cables", "homes", "drop_cables", "topo_edges",
           "boq_active", "boq_passive", "dashboard"):
    D.setdefault(_k, [])

# Build quick-lookup indexes
_olt_idx      = {o["olt_id"]: o      for o in D["olts"]}
_port_idx     = {p["pon_port_id"]: p for p in D["pon_ports"]}
_ps_idx       = {s["primary_splitter_id"]: s for s in D["splitters"]}
_odp_idx      = {o["odp_id"]: o      for o in D["odps"]}
_home_idx     = {h["home_id"]: h     for h in D["homes"]}
_area_idx     = {a["area_id"]: a     for a in D["areas"]}
_port_summary = {r["pon_port_id"]: r for r in D["port_summary"]}

# Topology edge adjacency  {source_id: [edge, ...]}
_adj: dict[str, list] = {}
for e in D["topo_edges"]:
    _adj.setdefault(e["source_asset_id"], []).append(e)

def _j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, default=str)

def _filter(records: list, **kwargs) -> list:
    out = records
    for k, v in kwargs.items():
        if v is not None:
            out = [r for r in out if str(r.get(k, "")).upper() == str(v).upper()]
    return out

def _haversine_m(lat1, lon1, lat2, lon2) -> float:
    R = 6_371_000
    f1, f2 = math.radians(lat1), math.radians(lat2)
    df = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(df/2)**2 + math.cos(f1)*math.cos(f2)*math.sin(dl/2)**2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ── Real Telkom Malang STO backbone (Tier 1/2/3) ─────────────────────────────
# Extracted from "Malang Sites (cleaned)-vShared.xlsx" via _build_sto.py.
# Prefer the copy loaded from Spanner; else read the JSON fixture.
if _SPANNER_STO is not None:
    STO = _SPANNER_STO
else:
    try:
        with open(STO_PATH, encoding="utf-8") as f:
            STO = json.load(f)
    except FileNotFoundError:
        STO = None

if STO:
    _sto_core   = STO.get("core_tier1")
    _sto_tier2  = STO.get("tier2_aggregation", [])
    _sto_tier3  = STO.get("tier3_access", [])
    _sto_idx    = {n["sto_code"]: n for n in (_sto_tier2 + _sto_tier3 + ([_sto_core] if _sto_core else []))}

    def _reconcile_op_a():
        """Map every Operator-A twin OLT to the nearest real Tier-3 access STO,
        then up the hierarchy: Tier-3 -> Tier-2 aggregation -> Tier-1 core."""
        out = []
        for o in [x for x in D["olts"] if x.get("operator_code") == "A"]:
            ll = (o["latitude"], o["longitude"])
            ranked = sorted(
                _sto_tier3,
                key=lambda t: _haversine_m(ll[0], ll[1], t["latitude"], t["longitude"]))
            cand = [{
                "sto_code": t["sto_code"], "sto_name": t["sto_name_official"],
                "distance_km": round(_haversine_m(ll[0], ll[1], t["latitude"], t["longitude"]) / 1000, 3),
            } for t in ranked[:3]]
            m = ranked[0]
            dkm = cand[0]["distance_km"]
            t2 = _sto_idx.get(m.get("tier2_parent"))
            out.append({
                "twin_olt_id": o["olt_id"], "area_id": o["area_id"], "area_name": o["area_name"],
                "twin_latitude": o["latitude"], "twin_longitude": o["longitude"],
                "matched_tier3_code": m["sto_code"], "matched_tier3_name": m["sto_name_official"],
                "matched_tier3_latitude": m["latitude"], "matched_tier3_longitude": m["longitude"],
                "match_distance_km": dkm,
                "match_confidence": "high" if dkm < 3 else ("medium" if dkm < 8 else "low"),
                "candidates_top3": cand,
                "tier2_aggregation_code": m.get("tier2_parent"),
                "tier2_aggregation_name": t2["sto_name_official"] if t2 else None,
                "tier2_link_km": m.get("tier2_parent_km"),
                "tier1_core_code": _sto_core["sto_code"] if _sto_core else None,
                "tier1_core_name": _sto_core["sto_name_official"] if _sto_core else None,
                "backhaul_path": [
                    {"tier": 4, "role": "Access OLT (twin)", "id": o["olt_id"]},
                    {"tier": 3, "role": "Access STO", "id": m["sto_code"], "name": m["sto_name_official"]},
                    {"tier": 2, "role": "Aggregation STO", "id": m.get("tier2_parent"),
                     "name": t2["sto_name_official"] if t2 else None, "link_km": m.get("tier2_parent_km")},
                    {"tier": 1, "role": "Core STO", "id": _sto_core["sto_code"] if _sto_core else None,
                     "name": _sto_core["sto_name_official"] if _sto_core else None},
                ],
            })
        return out

    def _tier2_aggregation_view():
        """Tier-2 aggregation nodes, the Tier-3 access STOs that home onto each,
        and their uplink to the Tier-1 core."""
        groups = {t["sto_code"]: {**t, "tier3_children": []} for t in _sto_tier2}
        for n in _sto_tier3:
            p = n.get("tier2_parent")
            if p in groups:
                groups[p]["tier3_children"].append({
                    "sto_code": n["sto_code"], "sto_name": n["sto_name_official"],
                    "link_km": n.get("tier2_parent_km"), "method": n.get("tier2_parent_method"),
                })
        return list(groups.values())

# ── Consolidation cost model ──────────────────────────────────────────────────
# All unit costs are documented MODELING ASSUMPTIONS in USD (synthetic network).
DEFAULT_COSTS = {
    "pole_cost": 150.0,           # per aerial pole (material + install)
    "feeder_per_m": 8.0,          # 48-pair feeder cable, per metre
    "dist_per_m": 4.0,            # distribution/branch cable, per metre
    "drop_per_m": 1.5,            # aerial drop cable, per metre
    "primary_splitter_cost": 120.0,   # 1:8 primary splitter closure
    "odp_cost": 250.0,            # ODP incl. 1:8 secondary splitter
    "olt_cost": 25000.0,          # OLT chassis
    "port_cost": 400.0,           # per PON port line card share
    "ont_cost": 60.0,             # per-home ONT/termination
    "opex_pct": 0.08,             # annual passive maintenance as % of asset value
    "resplice_per_home": 45.0,    # re-point one home onto surviving ODP
    "decomm_per_pole": 40.0,      # remove & make-safe one pole
    "decomm_per_cable_km": 800.0, # recover/dispose one km of retired cable
    "project_overhead_pct": 0.15, # PM, design, permits on migration works
    "discount_rate": 0.10,        # annual discount rate for NPV
    "poles_per_month": 600.0,     # decommission crew productivity
    "homes_per_month": 500.0,     # migration crew productivity
    "planning_months": 2.0,       # fixed design/permit lead time
}

def _cable_m_for(area_id, op_code):
    """Return (feeder_m, distribution_m, drop_m) for an operator in an area."""
    feeder = dist = 0.0
    for c in D["cables"]:
        if c.get("area_id") != area_id or c.get("operator_code") != op_code:
            continue
        L = c.get("segment_length_m", 0) or 0
        stage = str(c.get("route_stage", "")).lower()
        role = str(c.get("cable_role", "")).lower()
        if "feeder" in stage or "feeder" in role:
            feeder += L
        else:
            dist += L
    drop = sum((d.get("drop_length_m", 0) or 0)
               for d in D["drop_cables"]
               if d.get("area_id") == area_id and d.get("operator_code") == op_code)
    return feeder, dist, drop

def _operator_inventory(area_id, op_code):
    feeder, dist, drop = _cable_m_for(area_id, op_code)
    return {
        "operator_code": op_code,
        "poles": sum(1 for p in D["poles"] if p.get("area_id") == area_id and p.get("operator_code") == op_code),
        "primary_splitters": sum(1 for s in D["splitters"] if s.get("area_id") == area_id and s.get("operator_code") == op_code),
        "odps": sum(1 for o in D["odps"] if o.get("area_id") == area_id and o.get("operator_code") == op_code),
        "olts": sum(1 for o in D["olts"] if o.get("area_id") == area_id and o.get("operator_code") == op_code),
        "live_ports": sum(1 for p in D["pon_ports"] if p.get("area_id") == area_id and p.get("operator_code") == op_code and p.get("port_status") == "Live"),
        "homes": sum(1 for h in D["homes"] if h.get("area_id") == area_id and h.get("operator_code") == op_code),
        "feeder_m": round(feeder, 1),
        "distribution_m": round(dist, 1),
        "drop_m": round(drop, 1),
    }

def _passive_value(inv, c):
    return (inv["poles"] * c["pole_cost"]
            + inv["feeder_m"] * c["feeder_per_m"]
            + inv["distribution_m"] * c["dist_per_m"]
            + inv["drop_m"] * c["drop_per_m"]
            + inv["primary_splitters"] * c["primary_splitter_cost"]
            + inv["odps"] * c["odp_cost"])

def _active_value(inv, c):
    return inv["olts"] * c["olt_cost"] + inv["live_ports"] * c["port_cost"]

def _consolidate_area(area_id, c):
    area = _area_idx.get(area_id)
    invs = {op: _operator_inventory(area_id, op) for op in ("A", "B")}
    present = [op for op in ("A", "B") if invs[op]["homes"] > 0 or invs[op]["live_ports"] > 0]
    if len(present) < 2:
        return {
            "area_id": area_id,
            "area_name": area.get("area_name") if area else None,
            "archetype": area.get("archetype") if area else None,
            "operators_present": present,
            "consolidation_applicable": False,
            "note": "Single-operator area — no duplicate passive plant to consolidate.",
        }
    # Choose surviving operator = larger passive plant; retire the other.
    pv = {op: _passive_value(invs[op], c) for op in present}
    surviving = max(present, key=lambda op: pv[op])
    retiring = [op for op in present if op != surviving][0]
    ri = invs[retiring]
    retired_passive_value = pv[retiring]
    cable_km_removed = (ri["feeder_m"] + ri["distribution_m"] + ri["drop_m"]) / 1000.0
    homes_migrated = ri["homes"]

    migration_direct = (homes_migrated * c["resplice_per_home"]
                        + ri["poles"] * c["decomm_per_pole"]
                        + cable_km_removed * c["decomm_per_cable_km"])
    migration_capex = migration_direct * (1 + c["project_overhead_pct"])
    annual_opex_savings = retired_passive_value * c["opex_pct"]
    payback_months = (migration_capex / (annual_opex_savings / 12)) if annual_opex_savings else None
    duration_months = math.ceil(
        c["planning_months"]
        + max(ri["poles"] / c["poles_per_month"], homes_migrated / c["homes_per_month"])
    )
    r = c["discount_rate"]
    npv_5yr = -migration_capex + sum(annual_opex_savings / ((1 + r) ** t) for t in range(1, 6))

    as_is_capex = sum(_passive_value(invs[op], c) + _active_value(invs[op], c) for op in present)
    to_be_capex = as_is_capex - retired_passive_value

    return {
        "area_id": area_id,
        "area_name": area.get("area_name") if area else None,
        "archetype": area.get("archetype") if area else None,
        "operators_present": present,
        "consolidation_applicable": True,
        "surviving_operator": surviving,
        "retiring_operator": retiring,
        "inventory_by_operator": invs,
        "as_is_asset_value_usd": round(as_is_capex),
        "to_be_asset_value_usd": round(to_be_capex),
        "avoided_duplicate_passive_value_usd": round(retired_passive_value),
        "one_time_migration_capex_usd": round(migration_capex),
        "annual_opex_savings_usd": round(annual_opex_savings),
        "five_year_net_cash_usd": round(5 * annual_opex_savings - migration_capex),
        "npv_5yr_usd": round(npv_5yr),
        "payback_months": round(payback_months, 1) if payback_months else None,
        "project_duration_months": duration_months,
        "homes_migrated": homes_migrated,
        "poles_removed": ri["poles"],
        "cable_km_removed": round(cable_km_removed, 2),
    }

# ── Server ───────────────────────────────────────────────────────────────────
server = Server("pon-digital-twin")

@server.list_tools()
async def list_tools():
    return [
        types.Tool(
            name="get_dashboard",
            description="Return all top-level KPIs and summary statistics for the Malang PON network (areas, OLTs, ports, homes, cable totals).",
            inputSchema={"type":"object","properties":{}},
        ),
        types.Tool(
            name="list_areas",
            description="List all four PON areas with archetype, operator shares, connected-home counts, and dominant operator.",
            inputSchema={"type":"object","properties":{}},
        ),
        types.Tool(
            name="get_area",
            description="Return full detail for a single area.",
            inputSchema={"type":"object","properties":{"area_id":{"type":"string","description":"e.g. MAL-AR-01"}},"required":["area_id"]},
        ),
        types.Tool(
            name="list_olts",
            description="List OLTs, optionally filtered by area_id or operator_code (A or B).",
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string"},
                "operator_code":{"type":"string","enum":["A","B"]}
            }},
        ),
        types.Tool(
            name="get_olt",
            description="Return full detail for a single OLT including its PON ports and connected-home count.",
            inputSchema={"type":"object","properties":{"olt_id":{"type":"string"}},"required":["olt_id"]},
        ),
        types.Tool(
            name="list_pon_ports",
            description="List PON ports, optionally filtered by olt_id, area_id, operator_code, or port_status (Live/Spare).",
            inputSchema={"type":"object","properties":{
                "olt_id":{"type":"string"},
                "area_id":{"type":"string"},
                "operator_code":{"type":"string"},
                "port_status":{"type":"string","enum":["Live","Spare"]}
            }},
        ),
        types.Tool(
            name="get_pon_port",
            description="Return full detail for a PON port including route summary (feeder m, distribution m, drop m, optical path check).",
            inputSchema={"type":"object","properties":{"pon_port_id":{"type":"string"}},"required":["pon_port_id"]},
        ),
        types.Tool(
            name="list_primary_splitters",
            description="List primary 1:8 splitters, optionally filtered by area_id, pon_port_id, or operator_code.",
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string"},
                "pon_port_id":{"type":"string"},
                "operator_code":{"type":"string"}
            }},
        ),
        types.Tool(
            name="list_odps",
            description="List ODPs (secondary splitters), optionally filtered by area_id, pon_port_id, primary_splitter_id, or operator_code.",
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string"},
                "pon_port_id":{"type":"string"},
                "primary_splitter_id":{"type":"string"},
                "operator_code":{"type":"string"}
            }},
        ),
        types.Tool(
            name="get_odp",
            description="Return full detail for a single ODP.",
            inputSchema={"type":"object","properties":{"odp_id":{"type":"string"}},"required":["odp_id"]},
        ),
        types.Tool(
            name="list_homes",
            description="List homes/drops, optionally filtered by area_id, pon_port_id, odp_id, or operator_code. Returns up to max_results records (default 50).",
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string"},
                "pon_port_id":{"type":"string"},
                "odp_id":{"type":"string"},
                "operator_code":{"type":"string"},
                "max_results":{"type":"integer","default":50}
            }},
        ),
        types.Tool(
            name="get_home",
            description="Return full detail for a single home/drop.",
            inputSchema={"type":"object","properties":{"home_id":{"type":"string"}},"required":["home_id"]},
        ),
        types.Tool(
            name="trace_fiber_path",
            description=(
                "Trace the logical fiber path from an OLT down to a specific home, "
                "returning each hop: OLT → PON port → primary splitter → ODP → home. "
                "Provide a home_id."
            ),
            inputSchema={"type":"object","properties":{"home_id":{"type":"string"}},"required":["home_id"]},
        ),
        types.Tool(
            name="get_topology_edges",
            description="Return topology edges (logical + physical), optionally filtered by area_id, source_asset_id, target_asset_id, or edge_type.",
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string"},
                "source_asset_id":{"type":"string"},
                "target_asset_id":{"type":"string"},
                "edge_type":{"type":"string"},
                "max_results":{"type":"integer","default":50}
            }},
        ),
        types.Tool(
            name="get_boq",
            description="Return the full Bill of Quantities split into active and passive equipment.",
            inputSchema={"type":"object","properties":{}},
        ),
        types.Tool(
            name="find_nearest_assets",
            description="Find the N nearest assets of a given type to a lat/lng coordinate.",
            inputSchema={"type":"object","properties":{
                "latitude":{"type":"number"},
                "longitude":{"type":"number"},
                "asset_type":{"type":"string","enum":["olt","primary_splitter","odp","home","pole"]},
                "n":{"type":"integer","default":5}
            },"required":["latitude","longitude","asset_type"]},
        ),
        types.Tool(
            name="search_asset",
            description="Search for any asset by partial ID match. Returns type, ID, area, and coordinates.",
            inputSchema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]},
        ),
        types.Tool(
            name="get_port_utilisation",
            description="Return utilisation statistics per area and per operator: live vs spare ports, connected homes vs capacity, spare home slots.",
            inputSchema={"type":"object","properties":{"area_id":{"type":"string"}}},
        ),
        types.Tool(
            name="get_cable_summary",
            description="Return cable distance breakdown (feeder, distribution, drop) per area and totals in metres and km.",
            inputSchema={"type":"object","properties":{"area_id":{"type":"string"}}},
        ),
        types.Tool(
            name="list_fiber_routes",
            description=(
                "Return actual fibre cable ROUTES with real polyline geometry for mapping, "
                "optionally filtered by cable_role (e.g. 'feeder', 'distribution', 'drop'), "
                "cable_type (e.g. 'ADSS', 'DROP WIRE'), or area_id. Each route includes a "
                "'path' (list of [lon, lat] points), cable_role, cable_type_name, deployment "
                "(Overhead/Underground) and segment_length_m. Also returns available_roles and "
                "available_types for building filters. Data: PLN IconPlus (Operator B) NET05."
            ),
            inputSchema={"type":"object","properties":{
                "cable_role":{"type":"string","description":"substring match, e.g. feeder / distribution / drop"},
                "cable_type":{"type":"string","description":"substring match, e.g. ADSS / DROP WIRE"},
                "area_id":{"type":"string"},
                "max_results":{"type":"integer","description":"cap returned routes (default 6000)"}}},
        ),
        types.Tool(
            name="project_consolidation",
            description=(
                "Business case for consolidating the TWO operators in an overlap area onto a single "
                "shared passive network. Retires the smaller operator's duplicate plant and migrates its "
                "homes onto the surviving network. Returns per-operator inventory, avoided duplicate asset "
                "value, one-time migration CAPEX, annual OPEX savings, 5-year net cash, NPV, payback in "
                "months, and project duration in months. Omit area_id to aggregate across all overlap areas. "
                "Exclusive (single-operator) areas return consolidation_applicable=false. All unit costs are "
                "documented modeling assumptions in USD and can be overridden."
            ),
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string","description":"e.g. MAL-AR-03. Omit for network-wide aggregate."},
                "pole_cost":{"type":"number","description":"Override USD per pole (default 150)."},
                "opex_pct":{"type":"number","description":"Override annual maintenance %% of passive value (default 0.08)."},
                "resplice_per_home":{"type":"number","description":"Override USD to migrate one home (default 45)."},
                "discount_rate":{"type":"number","description":"Override annual discount rate for NPV (default 0.10)."}
            }},
        ),
        types.Tool(
            name="list_sto_nodes",
            description=(
                "List the REAL Telkom Malang STO backbone nodes (source: Malang Sites workbook), "
                "with tier (1=core, 2=aggregation, 3=access), official name, DATEL, and coordinates. "
                "Optionally filter by tier. This is the actual network the synthetic twin is reconciled against."
            ),
            inputSchema={"type":"object","properties":{
                "tier":{"type":"integer","description":"1, 2, or 3. Omit for all tiers."}}},
        ),
        types.Tool(
            name="get_tier2_aggregation",
            description=(
                "Return the Tier-2 aggregation layer of the real Malang backbone: each Tier-2 aggregation "
                "STO with the Tier-3 access STOs that home onto it and their uplink distances, plus the "
                "Tier-1 core. This is the aggregation hierarchy added to the twin."
            ),
            inputSchema={"type":"object","properties":{}},
        ),
        types.Tool(
            name="reconcile_operator_a",
            description=(
                "Reconcile the Operator A digital twin against the actual Malang OLT/STO/Tier-3 data. "
                "For each Operator A twin OLT, returns the nearest real Tier-3 access STO (with match "
                "distance/confidence and top-3 candidates) and the full backhaul path up the hierarchy: "
                "Access OLT -> Tier-3 access STO -> Tier-2 aggregation STO -> Tier-1 core STO."
            ),
            inputSchema={"type":"object","properties":{
                "area_id":{"type":"string","description":"Optional: restrict to one area, e.g. MAL-AR-03."}}},
        ),
        types.Tool(
            name="get_data_source",
            description=(
                "Report which datastore is backing the twin ('spanner' when reading from the "
                "Cloud Spanner emulator, 'json' when using local fixtures) plus record counts."
            ),
            inputSchema={"type":"object","properties":{}},
        ),
    ]

@server.call_tool()
async def call_tool(name: str, arguments: dict):
    def ok(obj):
        return [types.TextContent(type="text", text=_j(obj))]

    if name == "get_dashboard":
        kpis = {r["Metric"]: {"value": r["Value"], "unit": r.get("Unit",""), "comment": r.get("Comment","")}
                for r in D["dashboard"] if r.get("Metric")}
        return ok({"dashboard": kpis})

    elif name == "list_areas":
        return ok({"areas": D["areas"]})

    elif name == "get_area":
        aid = arguments["area_id"]
        area = _area_idx.get(aid)
        if not area:
            return ok({"error": f"Area {aid} not found"})
        return ok({"area": area})

    elif name == "list_olts":
        rows = _filter(D["olts"],
                       area_id=arguments.get("area_id"),
                       operator_code=arguments.get("operator_code"))
        return ok({"count": len(rows), "olts": rows})

    elif name == "get_olt":
        oid = arguments["olt_id"]
        o = _olt_idx.get(oid)
        if not o:
            return ok({"error": f"OLT {oid} not found"})
        ports = [p for p in D["pon_ports"] if p["olt_id"] == oid]
        total_homes = sum(p.get("modeled_connected_homes", 0) or 0 for p in ports)
        return ok({"olt": o, "pon_ports": ports, "total_connected_homes": total_homes})

    elif name == "list_pon_ports":
        rows = _filter(D["pon_ports"],
                       olt_id=arguments.get("olt_id"),
                       area_id=arguments.get("area_id"),
                       operator_code=arguments.get("operator_code"),
                       port_status=arguments.get("port_status"))
        return ok({"count": len(rows), "pon_ports": rows})

    elif name == "get_pon_port":
        pid = arguments["pon_port_id"]
        p = _port_idx.get(pid)
        if not p:
            return ok({"error": f"PON port {pid} not found"})
        summary = _port_summary.get(pid, {})
        return ok({"pon_port": p, "route_summary": summary})

    elif name == "list_primary_splitters":
        rows = _filter(D["splitters"],
                       area_id=arguments.get("area_id"),
                       pon_port_id=arguments.get("pon_port_id"),
                       operator_code=arguments.get("operator_code"))
        return ok({"count": len(rows), "primary_splitters": rows})

    elif name == "list_odps":
        rows = _filter(D["odps"],
                       area_id=arguments.get("area_id"),
                       pon_port_id=arguments.get("pon_port_id"),
                       primary_splitter_id=arguments.get("primary_splitter_id"),
                       operator_code=arguments.get("operator_code"))
        return ok({"count": len(rows), "odps": rows})

    elif name == "get_odp":
        oid = arguments["odp_id"]
        o = _odp_idx.get(oid)
        if not o:
            return ok({"error": f"ODP {oid} not found"})
        homes = [h for h in D["homes"] if h.get("odp_id") == oid]
        return ok({"odp": o, "homes_served": len(homes), "homes": homes})

    elif name == "list_homes":
        rows = _filter(D["homes"],
                       area_id=arguments.get("area_id"),
                       pon_port_id=arguments.get("pon_port_id"),
                       odp_id=arguments.get("odp_id"),
                       operator_code=arguments.get("operator_code"))
        n = int(arguments.get("max_results") or 50)
        return ok({"count": len(rows), "homes": rows[:n], "truncated": len(rows) > n})

    elif name == "get_home":
        hid = arguments["home_id"]
        h = _home_idx.get(hid)
        if not h:
            return ok({"error": f"Home {hid} not found"})
        drop = next((c for c in D["drop_cables"] if c.get("home_id") == hid), None)
        return ok({"home": h, "drop_cable": drop})

    elif name == "trace_fiber_path":
        hid = arguments["home_id"]
        h = _home_idx.get(hid)
        if not h:
            return ok({"error": f"Home {hid} not found"})
        odp = _odp_idx.get(h.get("odp_id"))
        ps  = _ps_idx.get(odp.get("primary_splitter_id")) if odp else None
        port = _port_idx.get(h.get("pon_port_id"))
        olt  = _olt_idx.get(port.get("olt_id")) if port else None
        summary = _port_summary.get(h.get("pon_port_id"), {})
        path = [
            {"hop":1,"asset_type":"OLT",              "asset_id": olt.get("olt_id") if olt else None,   "lat": olt.get("latitude") if olt else None,    "lng": olt.get("longitude") if olt else None,    "operator": olt.get("operator") if olt else None},
            {"hop":2,"asset_type":"PON Port",          "asset_id": port.get("pon_port_id") if port else None, "splitter_ratio": port.get("splitter_ratio") if port else None},
            {"hop":3,"asset_type":"Primary Splitter",  "asset_id": ps.get("primary_splitter_id") if ps else None, "lat": ps.get("latitude") if ps else None, "lng": ps.get("longitude") if ps else None},
            {"hop":4,"asset_type":"ODP",               "asset_id": odp.get("odp_id") if odp else None,  "lat": odp.get("latitude") if odp else None,     "lng": odp.get("longitude") if odp else None,    "homes_served": odp.get("homes_served") if odp else None},
            {"hop":5,"asset_type":"Home",              "asset_id": hid,                                  "lat": h.get("latitude"),                         "lng": h.get("longitude"),                        "drop_length_m": h.get("drop_length_m")},
        ]
        return ok({
            "home_id": hid,
            "area": h.get("area_id"),
            "operator": h.get("operator"),
            "path": path,
            "optical_path_m": h.get("estimated_optical_path_m"),
            "10km_check": h.get("max_10km_path_check"),
            "feeder_m": summary.get("feeder_48p_m"),
            "distribution_m": summary.get("distribution_branch_m"),
            "drop_m": h.get("drop_length_m"),
        })

    elif name == "get_topology_edges":
        rows = D["topo_edges"]
        for k in ["area_id","source_asset_id","target_asset_id","edge_type"]:
            if arguments.get(k):
                rows = [r for r in rows if str(r.get(k,"")).upper() == str(arguments[k]).upper()]
        n = int(arguments.get("max_results") or 50)
        return ok({"count": len(rows), "edges": rows[:n], "truncated": len(rows) > n})

    elif name == "get_boq":
        return ok({"boq_active": D["boq_active"], "boq_passive": D["boq_passive"]})

    elif name == "find_nearest_assets":
        lat, lng = arguments["latitude"], arguments["longitude"]
        atype = arguments["asset_type"]
        n = int(arguments.get("n") or 5)
        pool_map = {
            "olt":              [(o["olt_id"],              o.get("latitude"),  o.get("longitude"),  "OLT")             for o in D["olts"]],
            "primary_splitter": [(s["primary_splitter_id"], s.get("latitude"),  s.get("longitude"),  "Primary Splitter") for s in D["splitters"]],
            "odp":              [(o["odp_id"],              o.get("latitude"),  o.get("longitude"),  "ODP")             for o in D["odps"]],
            "home":             [(h["home_id"],             h.get("latitude"),  h.get("longitude"),  "Home")            for h in D["homes"]],
            "pole":             [(p["pole_id"],             p.get("latitude"),  p.get("longitude"),  "Pole")            for p in D["poles"]],
        }
        pool = [(aid, alat, alng, atp) for aid, alat, alng, atp in pool_map.get(atype, []) if alat and alng]
        ranked = sorted(pool, key=lambda x: _haversine_m(lat, lng, x[1], x[2]))[:n]
        result = [{"asset_id":r[0],"asset_type":r[3],"latitude":r[1],"longitude":r[2],
                   "distance_m": round(_haversine_m(lat,lng,r[1],r[2]),1)} for r in ranked]
        return ok({"nearest": result})

    elif name == "search_asset":
        q = arguments["query"].upper()
        results = []
        for src, atype, lat_k, lng_k, id_k in [
            (D["olts"],       "OLT",              "latitude",  "longitude",  "olt_id"),
            (D["splitters"],  "Primary Splitter", "latitude",  "longitude",  "primary_splitter_id"),
            (D["odps"],       "ODP",              "latitude",  "longitude",  "odp_id"),
            (D["homes"],      "Home",             "latitude",  "longitude",  "home_id"),
            (D["pon_ports"],  "PON Port",         None,        None,         "pon_port_id"),
            (D["areas"],      "Area",             "anchor_latitude","anchor_longitude","area_id"),
        ]:
            for r in src:
                if q in str(r.get(id_k,"")).upper():
                    results.append({"asset_type":atype,"asset_id":r[id_k],
                                    "area_id": r.get("area_id"),
                                    "operator": r.get("operator"),
                                    "latitude": r.get(lat_k) if lat_k else None,
                                    "longitude": r.get(lng_k) if lng_k else None})
                    if len(results) >= 20:
                        break
            if len(results) >= 20:
                break
        return ok({"count": len(results), "results": results})

    elif name == "get_port_utilisation":
        aid = arguments.get("area_id")
        ports = _filter(D["pon_ports"], area_id=aid)
        live = [p for p in ports if p.get("port_status") == "Live"]
        spare = [p for p in ports if p.get("port_status") == "Spare"]
        connected = sum(p.get("modeled_connected_homes",0) or 0 for p in live)
        capacity  = sum(p.get("max_supported_homes",0) or 0 for p in live)
        spare_slots = sum(p.get("spare_capacity_homes",0) or 0 for p in live)
        util = round(connected/capacity*100, 1) if capacity else 0
        # per-area breakdown
        by_area = {}
        for p in ports:
            a = p.get("area_id","?")
            if a not in by_area:
                by_area[a] = {"live":0,"spare":0,"connected_homes":0,"capacity":0}
            if p.get("port_status")=="Live":
                by_area[a]["live"] += 1
                by_area[a]["connected_homes"] += p.get("modeled_connected_homes",0) or 0
                by_area[a]["capacity"] += p.get("max_supported_homes",0) or 0
            else:
                by_area[a]["spare"] += 1
        return ok({"total_live_ports": len(live), "total_spare_ports": len(spare),
                   "connected_homes": connected, "capacity_homes": capacity,
                   "spare_home_slots": spare_slots, "utilisation_pct": util,
                   "by_area": by_area})

    elif name == "get_cable_summary":
        aid = arguments.get("area_id")
        cables = _filter(D["cables"], area_id=aid)
        drops  = _filter(D["drop_cables"], area_id=aid)
        feeder_m = sum(c.get("segment_length_m",0) or 0 for c in cables
                       if "feeder" in str(c.get("route_stage","")).lower() or "feeder" in str(c.get("cable_role","")).lower())
        distrib_m= sum(c.get("segment_length_m",0) or 0 for c in cables
                       if "distribution" in str(c.get("route_stage","")).lower() or "branch" in str(c.get("route_stage","")).lower())
        drop_m   = sum(c.get("drop_length_m",0) or 0 for c in drops)
        total_m  = feeder_m + distrib_m + drop_m
        by_area = {}
        for c in cables:
            a = c.get("area_id","?")
            if a not in by_area:
                by_area[a] = {"feeder_m":0,"distribution_m":0}
            if "feeder" in str(c.get("route_stage","")).lower() or "feeder" in str(c.get("cable_role","")).lower():
                by_area[a]["feeder_m"] += c.get("segment_length_m",0) or 0
            else:
                by_area[a]["distribution_m"] += c.get("segment_length_m",0) or 0
        for d in drops:
            a = d.get("area_id","?")
            by_area.setdefault(a, {}).setdefault("drop_m", 0)
            by_area[a]["drop_m"] = by_area[a].get("drop_m",0) + (d.get("drop_length_m",0) or 0)
        return ok({"feeder_m": round(feeder_m,1), "feeder_km": round(feeder_m/1000,2),
                   "distribution_m": round(distrib_m,1), "distribution_km": round(distrib_m/1000,2),
                   "drop_m": round(drop_m,1), "drop_km": round(drop_m/1000,2),
                   "total_m": round(total_m,1), "total_km": round(total_m/1000,2),
                   "by_area": by_area})

    elif name == "list_fiber_routes":
        cables = [c for c in D["cables"] if c.get("path")]
        role_q = str(arguments.get("cable_role") or "").lower()
        type_q = str(arguments.get("cable_type") or "").lower()
        aid = arguments.get("area_id")
        rows = [c for c in cables
                if (not role_q or role_q in str(c.get("cable_role","")).lower())
                and (not type_q or type_q in str(c.get("cable_type_name","")).lower())
                and (not aid or c.get("area_id") == aid)]
        n = int(arguments.get("max_results") or 30000)
        avail_roles = sorted({c.get("cable_role") for c in cables if c.get("cable_role")})
        avail_types = sorted({c.get("cable_type_name") for c in cables if c.get("cable_type_name")})
        total_km = round(sum(c.get("segment_length_m",0) or 0 for c in rows)/1000, 2)
        return ok({"count": len(rows), "returned": min(len(rows), n),
                   "total_km": total_km,
                   "available_roles": avail_roles, "available_types": avail_types,
                   "routes": rows[:n]})

    elif name == "project_consolidation":
        c = dict(DEFAULT_COSTS)
        for k in ("pole_cost", "opex_pct", "resplice_per_home", "discount_rate"):
            if arguments.get(k) is not None:
                c[k] = float(arguments[k])
        aid = arguments.get("area_id")
        if aid:
            return ok({"assumptions_usd": c, **_consolidate_area(aid, c)})
        # Network-wide: aggregate across all applicable (overlap) areas
        cases = [_consolidate_area(a["area_id"], c) for a in D["areas"]]
        applic = [x for x in cases if x.get("consolidation_applicable")]
        agg = {
            "scope": "network-wide (all overlap areas)",
            "areas_consolidated": [x["area_id"] for x in applic],
            "areas_not_applicable": [x["area_id"] for x in cases if not x.get("consolidation_applicable")],
            "avoided_duplicate_passive_value_usd": round(sum(x["avoided_duplicate_passive_value_usd"] for x in applic)),
            "one_time_migration_capex_usd": round(sum(x["one_time_migration_capex_usd"] for x in applic)),
            "annual_opex_savings_usd": round(sum(x["annual_opex_savings_usd"] for x in applic)),
            "five_year_net_cash_usd": round(sum(x["five_year_net_cash_usd"] for x in applic)),
            "npv_5yr_usd": round(sum(x["npv_5yr_usd"] for x in applic)),
            "homes_migrated": sum(x["homes_migrated"] for x in applic),
            "poles_removed": sum(x["poles_removed"] for x in applic),
            "cable_km_removed": round(sum(x["cable_km_removed"] for x in applic), 2),
            "programme_duration_months": max([x["project_duration_months"] for x in applic], default=0),
        }
        tot_opex = agg["annual_opex_savings_usd"]
        agg["blended_payback_months"] = round(agg["one_time_migration_capex_usd"] / (tot_opex / 12), 1) if tot_opex else None
        return ok({"assumptions_usd": c, **agg, "by_area": applic})

    elif name == "list_sto_nodes":
        if not STO:
            return ok({"error": "malang_sto.json not found; run _build_sto.py to generate it."})
        tier = arguments.get("tier")
        alln = ([_sto_core] if _sto_core else []) + _sto_tier2 + _sto_tier3
        rows = [n for n in alln if tier is None or n.get("tier") == int(tier)]
        return ok({"source_file": STO.get("source_file"), "region": STO.get("region"),
                   "counts": STO.get("counts"), "count": len(rows), "nodes": rows})

    elif name == "get_tier2_aggregation":
        if not STO:
            return ok({"error": "malang_sto.json not found; run _build_sto.py to generate it."})
        return ok({"tier1_core": _sto_core, "tier2_aggregation": _tier2_aggregation_view()})

    elif name == "reconcile_operator_a":
        if not STO:
            return ok({"error": "malang_sto.json not found; run _build_sto.py to generate it."})
        rows = _reconcile_op_a()
        aid = arguments.get("area_id")
        if aid:
            rows = [r for r in rows if r["area_id"].upper() == str(aid).upper()]
        return ok({
            "source_file": STO.get("source_file"),
            "operator": "Operator A",
            "olts_reconciled": len(rows),
            "tier1_core": _sto_core["sto_code"] if _sto_core else None,
            "reconciliation": rows,
        })

    elif name == "get_data_source":
        return ok({
            "backend": DATA_BACKEND,
            "spanner": {
                "project": os.environ.get("SPANNER_PROJECT", "twin-project"),
                "instance": os.environ.get("SPANNER_INSTANCE", "twin-instance"),
                "database": os.environ.get("SPANNER_DATABASE", "twin"),
                "emulator_host": os.environ.get("SPANNER_EMULATOR_HOST"),
            } if DATA_BACKEND == "spanner" else None,
            "collection_counts": {k: (len(v) if isinstance(v, list) else 1) for k, v in D.items()},
            "sto_loaded": STO is not None,
        })

    return ok({"error": f"Unknown tool: {name}"})


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream,
                         server.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
