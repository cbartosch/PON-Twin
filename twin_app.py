"""
Malang PON Digital Twin — Streamlit front-end for the MCP server.
Talks to the SAME MCP server (cmd /c run_twin.bat) over stdio, exactly as an
AI agent would: list_tools() + call_tool(). No direct data access.
"""
import asyncio
import json
import os
import sys

import pandas as pd
import streamlit as st

# Load OpenAI credentials from the existing .env (project key).
try:
    from dotenv import load_dotenv
    for _envpath in (
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
        r"C:\Users\bartosch christian\E2E-Spanner\.env",
    ):
        if os.path.exists(_envpath):
            load_dotenv(_envpath, override=False)
            break
except Exception:
    pass

from mcp import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters

# ── Windows needs the Proactor loop for subprocess transports ────────────────
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

HERE = os.path.dirname(os.path.abspath(__file__))
SERVER_PY = os.path.join(HERE, "server.py")

# The MCP stdio client spawns the server with a SCRUBBED environment by default,
# which would drop SPANNER_EMULATOR_HOST / SPANNER_* and force the JSON fallback.
# Pass the full environment through so the server can reach the Spanner emulator.
_SPAWN_ENV = dict(os.environ)

# On Windows we spawn the MCP server through a .bat wrapper (Node/Store-Python
# spawn quirk); inside the Linux container we invoke python directly.
if sys.platform == "win32":
    BAT = os.path.join(HERE, "run_twin.bat")
    SERVER = StdioServerParameters(command="cmd", args=["/c", BAT], env=_SPAWN_ENV)
else:
    SERVER = StdioServerParameters(command=sys.executable, args=[SERVER_PY], env=_SPAWN_ENV)

OP_COLORS = {"Operator A": [37, 99, 235], "Operator B": [234, 88, 12]}

# ── MCP plumbing ─────────────────────────────────────────────────────────────
async def _list_tools():
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            resp = await s.list_tools()
            return [
                {"name": t.name, "description": t.description,
                 "schema": t.inputSchema or {"type": "object", "properties": {}}}
                for t in resp.tools
            ]

async def _call(name, args):
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            res = await s.call_tool(name, args)
            text = res.content[0].text if res.content else "{}"
            try:
                return json.loads(text)
            except Exception:
                return {"raw": text}

def run(coro):
    return asyncio.run(coro)

@st.cache_data(show_spinner=False)
def get_tools():
    return run(_list_tools())

@st.cache_data(show_spinner=False)
def call_tool(name, args_json):
    return run(_call(name, json.loads(args_json)))

def tool_call(name, args=None):
    return call_tool(name, json.dumps(args or {}, sort_keys=True))

def first_list(d):
    """Return the first list-of-dicts value found in a result dict."""
    if isinstance(d, dict):
        for k, v in d.items():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return k, v
    return None, None

# ── Page config ──────────────────────────────────────────────────────────────
st.set_page_config(page_title="Malang PON Digital Twin", page_icon="🌐", layout="wide")

st.markdown("""
<style>
  .block-container{padding-top:1.5rem;padding-bottom:1rem}
  [data-testid="stMetricValue"]{font-size:1.4rem}
  .stTabs [data-baseweb="tab"]{font-weight:600}
</style>
""", unsafe_allow_html=True)

st.title("🌐 Malang PON Digital Twin")
st.caption("Live front-end for the **pon-digital-twin** MCP server — every panel below is powered by real MCP tool calls.")

# Connection check
with st.sidebar:
    st.header("MCP Connection")
    try:
        tools = get_tools()
        st.success(f"Connected · {len(tools)} tools")
        try:
            _src = tool_call("get_data_source")
            _be = _src.get("backend", "json")
            if _be == "spanner":
                sp = _src.get("spanner", {}) or {}
                st.info(f"🗄️ Datastore: **Spanner emulator** "
                        f"(`{sp.get('instance')}/{sp.get('database')}`)")
            else:
                st.warning("🗄️ Datastore: **JSON fixtures** (Spanner not connected)")
        except Exception:
            pass
        with st.expander("Available tools"):
            for t in tools:
                st.markdown(f"**`{t['name']}`**  \n{t['description'][:90]}")
    except Exception as e:
        st.error(f"Could not reach MCP server:\n\n{e}")
        st.stop()
    if st.button("🔄 Clear cache / reconnect"):
        st.cache_data.clear()
        st.rerun()

    st.divider()
    st.header("LLM (Ask tab)")
    _default_key = os.environ.get("OPENAI_API_KEY", "")
    api_key = st.text_input("OpenAI API key", type="password",
                            value=_default_key,
                            help="Used only by the 💬 Ask tab for tool-use. "
                                 "Loaded from .env if present.")
    if _default_key:
        st.caption("✓ Key loaded from .env")
    model_id = st.text_input("Model", value=os.environ.get("OPENAI_MODEL", "gpt-5.4"))

(tab_dash, tab_areas, tab_consol, tab_recon, tab_trace, tab_map,
 tab_boq, tab_chat, tab_explore) = st.tabs(
    ["📊 Dashboard", "🗺️ Areas & Utilisation", "💵 Consolidation",
     "🔗 Reconciliation", "🔍 Fiber Path Tracer", "📍 Map", "📦 BoQ",
     "💬 Ask (LLM)", "🛠️ Tool Explorer"]
)

# ── Dashboard ────────────────────────────────────────────────────────────────
with tab_dash:
    st.subheader("Network KPIs")
    dash = tool_call("get_dashboard").get("dashboard", {})
    items = list(dash.items())
    cols = st.columns(4)
    for i, (metric, info) in enumerate(items):
        with cols[i % 4]:
            val = info.get("value")
            try:
                val = f"{float(val):,.0f}" if float(val) == int(float(val)) else f"{float(val):,.1f}"
            except (TypeError, ValueError):
                val = str(val)
            st.metric(metric, f"{val} {info.get('unit','')}".strip())
    st.divider()
    st.caption("via `get_dashboard`")

# ── Areas & Utilisation ──────────────────────────────────────────────────────
with tab_areas:
    st.subheader("Areas")
    areas = tool_call("list_areas").get("areas", [])
    adf = pd.DataFrame(areas)
    if not adf.empty:
        show = [c for c in ["area_id","area_name","archetype","area_live_ports_total",
                            "connected_homes_total","dominance_test"] if c in adf.columns]
        st.dataframe(adf[show], use_container_width=True, hide_index=True)

    st.subheader("Port Utilisation")
    area_ids = ["(all)"] + [a["area_id"] for a in areas]
    sel = st.selectbox("Area", area_ids, key="util_area")
    args = {} if sel == "(all)" else {"area_id": sel}
    u = tool_call("get_port_utilisation", args)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Live ports", u.get("total_live_ports"))
    c2.metric("Spare ports", u.get("total_spare_ports"))
    c3.metric("Connected homes", f"{u.get('connected_homes',0):,}")
    c4.metric("Utilisation", f"{u.get('utilisation_pct',0)}%")
    if u.get("by_area"):
        st.dataframe(pd.DataFrame(u["by_area"]).T, use_container_width=True)

    st.subheader("Cable distance per area")
    cs = tool_call("get_cable_summary")
    ba = cs.get("by_area", {})
    if ba:
        cdf = pd.DataFrame(ba).T.fillna(0)
        cdf = cdf.rename(columns={"feeder_m": "Feeder", "distribution_m": "Distribution", "drop_m": "Drop"})
        for c in ["Feeder", "Distribution", "Drop"]:
            if c in cdf.columns:
                cdf[c] = cdf[c] / 1000.0  # km
        st.bar_chart(cdf[[c for c in ["Feeder", "Distribution", "Drop"] if c in cdf.columns]])
        st.caption("Stacked cable length by area (km)")
    st.caption("via `list_areas` + `get_port_utilisation` + `get_cable_summary`")

# ── Consolidation ────────────────────────────────────────────────────────────
with tab_consol:
    st.subheader("Operator consolidation business case")
    st.caption("Merge the two operators in an overlap area onto one shared passive network — "
               "retire duplicate plant, migrate homes, and project cost / savings / time.")
    areas_c = tool_call("list_areas").get("areas", [])
    opts = ["(network-wide)"] + [a["area_id"] for a in areas_c]
    csel = st.selectbox("Scope", opts, key="consol_area")
    colA, colB = st.columns(2)
    with colA:
        pole_cost = st.number_input("Pole cost (USD)", value=150.0, step=10.0)
        opex_pct = st.number_input("Annual OPEX % of passive value", value=0.08, step=0.01, format="%.2f")
    with colB:
        resplice = st.number_input("Re-splice per home (USD)", value=45.0, step=5.0)
        disc = st.number_input("Discount rate", value=0.10, step=0.01, format="%.2f")
    if st.button("Project consolidation", type="primary"):
        args = {"pole_cost": pole_cost, "opex_pct": opex_pct,
                "resplice_per_home": resplice, "discount_rate": disc}
        if csel != "(network-wide)":
            args["area_id"] = csel
        r = tool_call("project_consolidation", args)
        if r.get("consolidation_applicable") is False:
            st.warning(r.get("note", "Not applicable."))
        else:
            if csel == "(network-wide)":
                st.markdown(f"**Areas consolidated:** {', '.join(r.get('areas_consolidated', []))}")
                mig = r["one_time_migration_capex_usd"]; opex = r["annual_opex_savings_usd"]
                avoided = r["avoided_duplicate_passive_value_usd"]
                pay = r.get("blended_payback_months"); dur = r.get("programme_duration_months")
                npv = r["npv_5yr_usd"]; homes = r["homes_migrated"]
            else:
                st.markdown(f"**{csel}** · surviving **Operator {r['surviving_operator']}**, "
                            f"retiring **Operator {r['retiring_operator']}**")
                mig = r["one_time_migration_capex_usd"]; opex = r["annual_opex_savings_usd"]
                avoided = r["avoided_duplicate_passive_value_usd"]
                pay = r.get("payback_months"); dur = r.get("project_duration_months")
                npv = r["npv_5yr_usd"]; homes = r["homes_migrated"]
            m = st.columns(4)
            m[0].metric("Avoided duplicate value", f"${avoided:,.0f}")
            m[1].metric("Migration CAPEX", f"${mig:,.0f}")
            m[2].metric("Annual OPEX savings", f"${opex:,.0f}")
            m[3].metric("Payback", f"{pay} mo" if pay else "—")
            m2 = st.columns(4)
            m2[0].metric("5-yr NPV", f"${npv:,.0f}")
            m2[1].metric("Duration", f"{dur} mo")
            m2[2].metric("Homes migrated", f"{homes:,}")
            m2[3].metric("Poles removed", f"{r['poles_removed']:,}")
            if r.get("inventory_by_operator"):
                st.markdown("**Inventory by operator**")
                st.dataframe(pd.DataFrame(r["inventory_by_operator"]).T,
                             use_container_width=True)
            with st.expander("Assumptions & full result"):
                st.json(r)
    st.caption("via `project_consolidation`")

# ── Fiber Path Tracer ────────────────────────────────────────────────────────
with tab_recon:
    st.subheader("Operator A ↔ actual Malang STO backbone")
    st.caption("Reconciles the synthetic Operator A twin against the real Telkom "
               "Malang OLT/STO/Tier-3 data and shows the Tier-2 aggregation hierarchy "
               "now included in the twin.")

    rec = tool_call("reconcile_operator_a")
    if rec.get("error"):
        st.error(rec["error"])
    else:
        st.markdown(f"**Core (Tier 1):** `{rec.get('tier1_core')}` · "
                    f"**Operator A OLTs reconciled:** {rec.get('olts_reconciled')}")
        rows = rec.get("reconciliation", [])
        if rows:
            df = pd.DataFrame([{
                "Twin OLT": r["twin_olt_id"],
                "Area": r["area_name"],
                "Matched Tier-3 STO": f'{r["matched_tier3_code"]} — {r["matched_tier3_name"]}',
                "Match km": r["match_distance_km"],
                "Confidence": r["match_confidence"],
                "Tier-2 aggregation": r.get("tier2_aggregation_code"),
                "Tier-2 link km": r.get("tier2_link_km"),
                "Tier-1 core": r.get("tier1_core_code"),
            } for r in rows])
            st.dataframe(df, use_container_width=True, hide_index=True)

            st.markdown("**Backhaul paths** (Access OLT → Tier-3 → Tier-2 → Tier-1):")
            for r in rows:
                path = " → ".join(
                    f'{h["id"]}' + (f' ({h.get("name")})' if h.get("name") else "")
                    for h in r["backhaul_path"])
                st.markdown(f'- `{r["area_id"]}` · {path}')
            with st.expander("Match candidates (top 3 nearest Tier-3 per OLT)"):
                for r in rows:
                    cands = ", ".join(f'{c["sto_code"]} {c["distance_km"]}km'
                                      for c in r.get("candidates_top3", []))
                    st.markdown(f'**{r["twin_olt_id"]}**: {cands}')

    st.divider()
    st.subheader("Tier-2 aggregation layer")
    agg = tool_call("get_tier2_aggregation")
    if agg.get("error"):
        st.error(agg["error"])
    else:
        core = agg.get("tier1_core") or {}
        st.caption(f"Tier-1 core: `{core.get('sto_code')}` — {core.get('sto_name_official')}")
        arows = []
        for g in agg.get("tier2_aggregation", []):
            arows.append({
                "Tier-2 STO": f'{g["sto_code"]} — {g["sto_name_official"]}',
                "Access (Tier-3) count": len(g.get("tier3_children", [])),
                "Tier-3 children": ", ".join(c["sto_code"] for c in g.get("tier3_children", [])),
            })
        if arows:
            st.dataframe(pd.DataFrame(arows), use_container_width=True, hide_index=True)

with tab_trace:
    st.subheader("Trace fiber path OLT → Home")
    default_home = "HH-A-MAL-AR-01-P01-S01-H05"
    home_id = st.text_input("Home ID", value=default_home)
    if st.button("Trace", type="primary"):
        p = tool_call("trace_fiber_path", {"home_id": home_id})
        if p.get("error"):
            st.error(p["error"])
        else:
            m1, m2, m3 = st.columns(3)
            m1.metric("Area", p.get("area"))
            m2.metric("Optical path", f"{p.get('optical_path_m')} m")
            m3.metric("10 km check", p.get("10km_check"))
            path = p.get("path", [])
            st.markdown("#### Hops")
            for h in path:
                st.markdown(
                    f"**{h['hop']}. {h['asset_type']}** — `{h.get('asset_id')}`"
                )
            pts = [{"lat": h.get("lat"), "lon": h.get("lng"),
                    "label": h["asset_type"]} for h in path if h.get("lat")]
            if pts:
                import pydeck as pdk
                pdf = pd.DataFrame(pts)
                line = [{"path": [[x["lon"], x["lat"]] for x in pts]}]
                st.pydeck_chart(pdk.Deck(
                    map_style=None,
                    initial_view_state=pdk.ViewState(
                        latitude=pdf["lat"].mean(), longitude=pdf["lon"].mean(),
                        zoom=13, pitch=0),
                    layers=[
                        pdk.Layer("PathLayer", data=line, get_path="path",
                                  get_width=6, get_color=[59,130,246], width_min_pixels=3),
                        pdk.Layer("ScatterplotLayer", data=pdf,
                                  get_position="[lon, lat]", get_radius=40,
                                  get_fill_color=[234,88,12], pickable=True),
                    ],
                    tooltip={"text": "{label}"},
                ))
    st.caption("via `trace_fiber_path`")

# ── Map ──────────────────────────────────────────────────────────────────────
with tab_map:
    st.subheader("Asset map")
    import pydeck as pdk
    show_olts = st.checkbox("OLTs", True)
    show_odps = st.checkbox("ODPs", True)
    show_homes = st.checkbox("Homes (sampled)", False)
    show_sto = st.checkbox("STO backbone (Tier 1/2/3 + aggregation links)", True)
    show_recon = st.checkbox("Operator A reconciliation links (OLT → Tier-3)", True)
    show_fiber = st.checkbox("Fibre cable routes (by cable type)", False)

    # Cable-role colours for the fibre route layer.
    ROLE_COLOR = {"Distribution / Feeder": [37, 99, 235], "Drop / Access": [16, 185, 129],
                  "Access": [16, 185, 129]}
    route_filter = None
    if show_fiber:
        meta = tool_call("list_fiber_routes", {"max_results": 1}) or {}
        roles = meta.get("available_roles", []) or ["Distribution / Feeder", "Drop / Access"]
        route_filter = st.multiselect(
            "Cable types to show", roles, default=roles,
            help="Filter fibre routes by cable role/type (PLN IconPlus NET05).")

    # Tier colours: T1 core = red, T2 aggregation = amber, T3 access = teal.
    TIER_COLOR = {1: [220, 38, 38], 2: [245, 158, 11], 3: [13, 148, 136]}
    TIER_RADIUS = {1: 280, 2: 190, 3: 110}

    layers, all_lat, all_lon = [], [], []

    if show_olts:
        olts = tool_call("list_olts").get("olts", [])
        odf = pd.DataFrame([o for o in olts if o.get("latitude")])
        if not odf.empty:
            odf["color"] = odf["operator"].map(lambda o: OP_COLORS.get(o, [150,150,150]))
            all_lat += odf["latitude"].tolist(); all_lon += odf["longitude"].tolist()
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=odf,
                get_position="[longitude, latitude]", get_radius=120,
                get_fill_color="color", pickable=True))

    if show_odps:
        odps = tool_call("list_odps").get("odps", [])
        oddf = pd.DataFrame([o for o in odps if o.get("latitude")])
        if not oddf.empty:
            all_lat += oddf["latitude"].tolist(); all_lon += oddf["longitude"].tolist()
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=oddf,
                get_position="[longitude, latitude]", get_radius=30,
                get_fill_color=[16,185,129], pickable=True))

    if show_homes:
        homes = tool_call("list_homes", {"max_results": 1000}).get("homes", [])
        hdf = pd.DataFrame([h for h in homes if h.get("latitude")])
        if not hdf.empty:
            all_lat += hdf["latitude"].tolist(); all_lon += hdf["longitude"].tolist()
            layers.append(pdk.Layer(
                "ScatterplotLayer", data=hdf,
                get_position="[longitude, latitude]", get_radius=12,
                get_fill_color=[148,163,184]))

    if show_fiber and route_filter:
        fr = tool_call("list_fiber_routes", {"max_results": 30000}).get("routes", [])
        fr = [r for r in fr if r.get("cable_role") in route_filter and r.get("path")]
        if fr:
            fdf = pd.DataFrame([{
                "path": r["path"], "color": ROLE_COLOR.get(r.get("cable_role"), [148, 163, 184]),
                "label": f'{r.get("cable_type_name")} · {r.get("cable_role")} · '
                         f'{r.get("segment_length_m")} m',
                "operator": "", "area_id": r.get("area_id"),
            } for r in fr])
            for r in fr:
                if r.get("from_latitude"):
                    all_lat.append(r["from_latitude"]); all_lon.append(r["from_longitude"])
            layers.append(pdk.Layer(
                "PathLayer", data=fdf, get_path="path", get_color="color",
                get_width=3, width_min_pixels=1, width_max_pixels=4,
                cap_rounded=True, joint_rounded=True, opacity=0.75, pickable=True))

    _code_ll = {}   # sto_code -> (lat, lon) for drawing links
    if show_sto or show_recon:
        sto_nodes = tool_call("list_sto_nodes").get("nodes", [])
        for n in sto_nodes:
            if n.get("latitude") is not None:
                _code_ll[n["sto_code"]] = (n["latitude"], n["longitude"])

    if show_sto and _code_ll:
        ndf = pd.DataFrame([n for n in sto_nodes if n.get("latitude") is not None])
        ndf["color"] = ndf["tier"].map(lambda t: TIER_COLOR.get(t, [150, 150, 150]))
        ndf["radius"] = ndf["tier"].map(lambda t: TIER_RADIUS.get(t, 300))
        ndf["label"] = ndf.apply(lambda r: f'T{r["tier"]} {r["sto_code"]} — {r["sto_name_official"]}', axis=1)
        all_lat += ndf["latitude"].tolist(); all_lon += ndf["longitude"].tolist()

        # Aggregation links: Tier-3 -> its Tier-2 parent, and every Tier-2 -> Tier-1 core.
        links = []
        core = tool_call("get_tier2_aggregation").get("tier1_core") or {}
        core_ll = (core.get("latitude"), core.get("longitude")) if core else (None, None)
        for n in sto_nodes:
            if n.get("tier") == 3 and n.get("tier2_parent") in _code_ll:
                f = _code_ll[n["sto_code"]]; t = _code_ll[n["tier2_parent"]]
                links.append({"from": [f[1], f[0]], "to": [t[1], t[0]], "color": [120, 120, 120]})
            if n.get("tier") == 2 and core_ll[0] is not None:
                f = _code_ll[n["sto_code"]]
                links.append({"from": [f[1], f[0]], "to": [core_ll[1], core_ll[0]], "color": [220, 38, 38]})
        if links:
            layers.append(pdk.Layer(
                "LineLayer", data=pd.DataFrame(links),
                get_source_position="from", get_target_position="to",
                get_color="color", get_width=2))
        layers.append(pdk.Layer(
            "ScatterplotLayer", data=ndf,
            get_position="[longitude, latitude]", get_radius="radius",
            radius_min_pixels=4, radius_max_pixels=14,
            get_fill_color="color", opacity=0.7, stroked=True,
            get_line_color=[255, 255, 255], line_width_min_pixels=1, pickable=True))

    if show_recon:
        rec = tool_call("reconcile_operator_a").get("reconciliation", [])
        rlinks = []
        for r in rec:
            t3 = _code_ll.get(r["matched_tier3_code"])
            if t3 and r.get("twin_latitude") is not None:
                rlinks.append({
                    "from": [r["twin_longitude"], r["twin_latitude"]],
                    "to": [t3[1], t3[0]],
                    "label": f'{r["twin_olt_id"]} → {r["matched_tier3_code"]} ({r["match_distance_km"]} km)'})
                all_lat += [r["twin_latitude"], t3[0]]; all_lon += [r["twin_longitude"], t3[1]]
        if rlinks:
            layers.append(pdk.Layer(
                "LineLayer", data=pd.DataFrame(rlinks),
                get_source_position="from", get_target_position="to",
                get_color=[37, 99, 235], get_width=3, pickable=True))

    if layers and all_lat:
        zoom = 10.5 if (show_sto or show_recon) else 12.5
        st.pydeck_chart(pdk.Deck(
            map_style=None,
            initial_view_state=pdk.ViewState(
                latitude=sum(all_lat)/len(all_lat),
                longitude=sum(all_lon)/len(all_lon),
                zoom=zoom, pitch=0),
            layers=layers,
            tooltip={"text": "{label}{operator} {area_id}"},
        ))
    st.markdown(
        "<span style='color:#dc2626'>●</span> Tier-1 core &nbsp; "
        "<span style='color:#f59e0b'>●</span> Tier-2 aggregation &nbsp; "
        "<span style='color:#0d9488'>●</span> Tier-3 access &nbsp; "
        "<span style='color:#2563eb'>▬</span> Op A reconciliation link &nbsp; "
        "<span style='color:#2563eb'>▬</span> Distribution/feeder fibre &nbsp; "
        "<span style='color:#10b981'>▬</span> Drop/access fibre",
        unsafe_allow_html=True)
    st.caption("via `list_olts`, `list_odps`, `list_homes`, `list_sto_nodes`, "
               "`get_tier2_aggregation`, `reconcile_operator_a`")

# ── BoQ ──────────────────────────────────────────────────────────────────────
with tab_boq:
    st.subheader("Bill of Quantities")
    boq = tool_call("get_boq")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Active equipment**")
        bdf = pd.DataFrame(boq.get("boq_active", []))
        if not bdf.empty:
            cols = [c for c in ["item","unit","quantity"] if c in bdf.columns]
            st.dataframe(bdf[cols], use_container_width=True, hide_index=True)
    with c2:
        st.markdown("**Passive equipment**")
        pdf = pd.DataFrame(boq.get("boq_passive", []))
        if not pdf.empty:
            cols = [c for c in ["item","unit","quantity"] if c in pdf.columns]
            st.dataframe(pdf[cols], use_container_width=True, hide_index=True)
    st.caption("via `get_boq`")

# ── Ask (LLM tool-use) ───────────────────────────────────────────────────────
with tab_chat:
    st.subheader("Ask the digital twin")
    st.caption("Natural-language questions. The LLM chooses and calls the MCP tools, "
               "then answers from the results.")

    SYS = (
        "You are an analyst for the Malang 4-area PON fiber network digital twin. "
        "Answer questions by calling the provided tools, which query a live inventory/topology "
        "model (OLTs, PON ports, splitters, ODPs, homes, poles, cables) and a consolidation "
        "business-case engine. Areas MAL-AR-01/02 are single-operator; MAL-AR-03/04 are overlap "
        "areas where operators can be consolidated. Prefer calling tools over guessing. Give "
        "concise, quantitative answers with units (USD, m/km, months). When you cite money or "
        "distances, name the tool you used."
    )

    # Build OpenAI function-calling tool schemas from the live MCP tool list.
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": (t["description"] or "")[:1024],
                "parameters": t["schema"] or {"type": "object", "properties": {}},
            },
        }
        for t in tools
    ]

    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []

    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["display"])

    prompt = st.chat_input("e.g. What's the payback for consolidating MAL-AR-03?")
    if prompt:
        with st.chat_message("user"):
            st.markdown(prompt)
        st.session_state.chat_history.append({"role": "user", "display": prompt})

        if not api_key:
            with st.chat_message("assistant"):
                st.warning("Enter an OpenAI API key in the sidebar (or set OPENAI_API_KEY "
                           "in .env) to use this tab.")
            st.session_state.chat_history.append(
                {"role": "assistant", "display": "_(no API key provided)_"})
        else:
            from openai import OpenAI
            client = OpenAI(api_key=api_key)

            def _create(msgs):
                """Model-agnostic call: gpt-5/o-series use max_completion_tokens and
                reject custom sampling params, so retry cleanly if the API rejects one."""
                base = dict(model=model_id, tools=openai_tools,
                            tool_choice="auto", messages=msgs)
                for kwargs in (
                    {**base, "max_completion_tokens": 1500},
                    {**base, "max_tokens": 1500},
                    base,
                ):
                    try:
                        return client.chat.completions.create(**kwargs)
                    except Exception as err:
                        if "max_tokens" in str(err) or "max_completion_tokens" in str(err):
                            continue
                        raise
                raise RuntimeError("Model rejected token-limit parameters")

            messages = [{"role": "system", "content": SYS},
                        {"role": "user", "content": prompt}]
            tool_trace = []
            answer = "_(no text response)_"
            with st.chat_message("assistant"):
                with st.status("Thinking & calling tools…", expanded=True) as status:
                    try:
                        for _ in range(8):  # bounded tool-use loop
                            msg = _create(messages).choices[0].message

                            if msg.tool_calls:
                                # Append a clean assistant turn: only the fields the
                                # API needs to pair the tool results back.
                                messages.append({
                                    "role": "assistant",
                                    "content": msg.content or "",
                                    "tool_calls": [
                                        {
                                            "id": tc.id,
                                            "type": "function",
                                            "function": {
                                                "name": tc.function.name,
                                                "arguments": tc.function.arguments or "{}",
                                            },
                                        }
                                        for tc in msg.tool_calls
                                    ],
                                })
                                for tc in msg.tool_calls:
                                    try:
                                        args = json.loads(tc.function.arguments or "{}")
                                    except Exception:
                                        args = {}
                                    st.write(f"🛠️ `{tc.function.name}` {json.dumps(args)}")
                                    tool_trace.append(tc.function.name)
                                    out = tool_call(tc.function.name, args)
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tc.id,
                                        "content": json.dumps(out)[:12000],
                                    })
                            else:
                                answer = msg.content or answer
                                break
                        status.update(label=f"Done · tools used: {', '.join(tool_trace) or 'none'}",
                                      state="complete", expanded=False)
                    except Exception as e:
                        status.update(label="Error", state="error")
                        st.error(str(e))
                st.markdown(answer)
            st.session_state.chat_history.append({"role": "assistant", "display": answer})

    if st.session_state.chat_history and st.button("Clear chat"):
        st.session_state.chat_history = []
        st.rerun()

# ── Tool Explorer (generic) ──────────────────────────────────────────────────
with tab_explore:
    st.subheader("Run any MCP tool")
    names = [t["name"] for t in tools]
    tname = st.selectbox("Tool", names)
    tdef = next(t for t in tools if t["name"] == tname)
    st.caption(tdef["description"])

    schema = tdef["schema"]
    props = schema.get("properties", {})
    required = set(schema.get("required", []))
    args = {}
    if props:
        st.markdown("**Arguments**")
        for pname, pspec in props.items():
            label = pname + (" *" if pname in required else "")
            ptype = pspec.get("type")
            enum = pspec.get("enum")
            if enum:
                choice = st.selectbox(label, ["(none)"] + list(enum), key=f"ex_{tname}_{pname}")
                if choice != "(none)":
                    args[pname] = choice
            elif ptype == "integer":
                default = pspec.get("default", 0)
                v = st.number_input(label, value=int(default), step=1, key=f"ex_{tname}_{pname}")
                if v:
                    args[pname] = int(v)
            elif ptype == "number":
                v = st.text_input(label, key=f"ex_{tname}_{pname}")
                if v.strip():
                    args[pname] = float(v)
            else:
                v = st.text_input(label, key=f"ex_{tname}_{pname}")
                if v.strip():
                    args[pname] = v.strip()

    if st.button("▶ Run tool", type="primary", key=f"run_{tname}"):
        result = tool_call(tname, args)
        key, lst = first_list(result)
        if lst:
            st.success(f"{len(lst)} rows in `{key}`")
            st.dataframe(pd.DataFrame(lst), use_container_width=True)
            other = {k: v for k, v in result.items() if k != key}
            if other:
                st.json(other)
        else:
            st.json(result)
