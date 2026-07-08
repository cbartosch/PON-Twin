import asyncio, json, importlib.util, os
spec = importlib.util.spec_from_file_location("twin_server", os.path.join(os.path.dirname(__file__), "server.py"))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

async def call(name, args=None):
    r = await srv.call_tool(name, args or {})
    return json.loads(r[0].text)

async def main():
    t = await call("list_sto_nodes")
    print("STO counts:", t["counts"])
    agg = await call("get_tier2_aggregation")
    print("\n=== TIER 2 AGGREGATION ===  core:", agg["tier1_core"]["sto_code"])
    for g in agg["tier2_aggregation"]:
        kids = ", ".join(f'{c["sto_code"]}({c["link_km"]}km)' for c in g["tier3_children"])
        print(f'  {g["sto_code"]} {g["sto_name_official"]}: {len(g["tier3_children"])} access -> [{kids}]')
    r = await call("reconcile_operator_a")
    print(f'\n=== RECONCILE OPERATOR A ===  {r["olts_reconciled"]} OLTs, core {r["tier1_core"]}')
    for x in r["reconciliation"]:
        print(f'  {x["twin_olt_id"]} ({x["area_name"]})')
        print(f'     T3 {x["matched_tier3_code"]} {x["match_distance_km"]}km [{x["match_confidence"]}]  '
              f'T2 {x["tier2_aggregation_code"]}  T1 {x["tier1_core_code"]}')
        print(f'     path: {" -> ".join(str(h["id"]) for h in x["backhaul_path"])}')

asyncio.run(main())
