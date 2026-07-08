import asyncio, json, importlib.util, os
spec = importlib.util.spec_from_file_location("twin_server", os.path.join(os.path.dirname(__file__), "server.py"))
srv = importlib.util.module_from_spec(spec); spec.loader.exec_module(srv)

async def call(name, args):
    r = await srv.call_tool(name, args)
    return json.loads(r[0].text)

async def main():
    for aid in ["MAL-AR-01", "MAL-AR-03"]:
        r = await call("project_consolidation", {"area_id": aid})
        print(f"=== {aid} ({r.get('archetype')}) applicable={r.get('consolidation_applicable')} ===")
        if r.get("consolidation_applicable"):
            for k in ["surviving_operator","retiring_operator","avoided_duplicate_passive_value_usd",
                      "one_time_migration_capex_usd","annual_opex_savings_usd","payback_months",
                      "npv_5yr_usd","project_duration_months","homes_migrated","poles_removed","cable_km_removed"]:
                print(f"   {k}: {r[k]}")
        else:
            print("  ", r.get("note"))
        print()
    net = await call("project_consolidation", {})
    print("=== NETWORK-WIDE ===")
    for k in ["areas_consolidated","avoided_duplicate_passive_value_usd","one_time_migration_capex_usd",
              "annual_opex_savings_usd","five_year_net_cash_usd","npv_5yr_usd","blended_payback_months",
              "programme_duration_months","homes_migrated","poles_removed","cable_km_removed"]:
        print(f"   {k}: {net[k]}")

asyncio.run(main())
