import asyncio, json, importlib.util, os

spec = importlib.util.spec_from_file_location(
    "twin_server", os.path.join(os.path.dirname(__file__), "server.py"))
srv = importlib.util.module_from_spec(spec)
spec.loader.exec_module(srv)

async def call(name, args):
    res = await srv.call_tool(name, args)
    return json.loads(res[0].text)

async def main():
    p = await call("trace_fiber_path", {"home_id": "HH-A-MAL-AR-01-P01-S01-H05"})
    print("=== trace_fiber_path  home=HH-A-MAL-AR-01-P01-S01-H05 ===")
    print(f'  area={p.get("area")}  operator={p.get("operator")}  '
          f'optical_path_m={p.get("optical_path_m")}  10km={p.get("10km_check")}')
    for h in p.get("path", []):
        print(f'    hop {h["hop"]}: {h["asset_type"]:<17} {h.get("asset_id")}')

    c = await call("get_cable_summary", {})
    print("\n=== get_cable_summary (network total) ===")
    for k in ["feeder_km", "distribution_km", "drop_km", "total_km"]:
        print(f"  {k}: {c.get(k)}")

    n = await call("find_nearest_assets",
                   {"latitude": -7.9655, "longitude": 112.6005, "asset_type": "odp", "n": 3})
    print("\n=== find_nearest_assets  near OLT-A-01  (top 3 ODPs) ===")
    for a in n.get("nearest", []):
        print(f'    {a["asset_id"]}  {a["distance_m"]} m')

asyncio.run(main())
