import json, os, tempfile
path = os.path.join(tempfile.gettempdir(), "twin_demo.jsonl")
ids = {}
for line in open(path, encoding="utf-8"):
    line = line.strip()
    if not line:
        continue
    try:
        m = json.loads(line)
    except Exception:
        continue
    if "result" in m and "content" in m["result"]:
        ids[m["id"]] = json.loads(m["result"]["content"][0]["text"])

d = ids.get(2, {}).get("dashboard", {})
print("=== get_dashboard (network scale) ===")
for k in ["Areas", "OLTs", "Live PON ports", "Connected homes total", "Aerial poles"]:
    if k in d:
        print(f'  {k}: {d[k]["value"]} {d[k]["unit"]}')

u = ids.get(3, {})
print("\n=== get_port_utilisation  area=MAL-AR-03 ===")
for k in ["total_live_ports", "total_spare_ports", "connected_homes", "capacity_homes", "utilisation_pct"]:
    print(f"  {k}: {u.get(k)}")

p = ids.get(4, {})
print("\n=== trace_fiber_path  home=HH-A-MAL-AR-01-P01-S01-H05 ===")
print(f'  area={p.get("area")}  operator={p.get("operator")}  optical_path_m={p.get("optical_path_m")}  10km={p.get("10km_check")}')
for h in p.get("path", []):
    print(f'    hop {h["hop"]}: {h["asset_type"]:<17} {h.get("asset_id")}')

c = ids.get(5, {})
print("\n=== get_cable_summary (network total) ===")
for k in ["feeder_km", "distribution_km", "drop_km", "total_km"]:
    print(f"  {k}: {c.get(k)}")
