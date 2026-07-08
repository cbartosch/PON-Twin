"""Extract real Operator B (PLN IconPlus) fibre cable ROUTES from NET05, scoped
to Malang bbox, with real polyline geometry + cable type/role, for map display.
Keeps ALL distribution/feeder routes; samples drop/access routes. Assigns each
route to its nearest STO Tier-3 area. Writes op_b_cables.json."""
import zipfile, csv, io, json, os, re, collections, random

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "op_b_cables.json")
BBOX = dict(lat_min=-8.6, lat_max=-7.65, lng_min=112.2, lng_max=113.05)
DROP_SAMPLE = 1_000_000       # effectively no cap: keep all drop/access routes
random.seed(42)

sto = json.load(open(os.path.join(HERE, "malang_sto.json"), encoding="utf-8"))
T3 = sto["tier3_access"]
def nearest_sto3(lat, lon):
    best, bd = None, 1e18
    for t in T3:
        dd = (t["latitude"] - lat) ** 2 + (t["longitude"] - lon) ** 2
        if dd < bd: bd, best = dd, t["sto_code"]
    return best

def coords(geom):
    pts = re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", geom or "")
    return [[float(lo), float(la)] for lo, la in pts]

def decimate(path, maxn=12):
    if len(path) <= maxn: return path
    step = len(path) / maxn
    out = [path[int(i * step)] for i in range(maxn)]
    out[-1] = path[-1]
    return out

def role_of(core_access, ctype):
    ca = (core_access or "").strip().lower()
    if ca == "distribution": return "Distribution / Feeder"
    if "DROP" in (ctype or "").upper(): return "Drop / Access"
    return "Access"

z = zipfile.ZipFile(ZIP)
name = [n for n in z.namelist() if "NET05" in n and n.lower().endswith(".csv")][0]

dist_routes, drop_routes = [], []
drop_seen = 0
with z.open(name) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")
    for i, row in enumerate(r):
        if i == 0 or len(row) < 15: continue
        path = coords(row[14])
        if not path: continue
        lon0, lat0 = path[0]
        if not (BBOX["lat_min"] <= lat0 <= BBOX["lat_max"] and BBOX["lng_min"] <= lon0 <= BBOX["lng_max"]):
            continue
        ctype = row[10].strip().upper()
        role = role_of(row[13], ctype)
        length = None
        for k in (7, 8, 6):
            try: length = float(row[k]); break
            except Exception: pass
        p = decimate(path)
        rec = {
            "segment_id": row[2].strip() or f"B-CABL-{i}",
            "operator": "Operator B", "operator_code": "B",
            "area_id": nearest_sto3(lat0, lon0),
            "cable_role": role, "cable_type_name": ctype or "UNKNOWN",
            "deployment": (row[12] or "").strip().title(),
            "segment_length_m": round(length, 1) if length else None,
            "path": p,
            "from_longitude": p[0][0], "from_latitude": p[0][1],
            "to_longitude": p[-1][0], "to_latitude": p[-1][1],
        }
        if role == "Distribution / Feeder":
            dist_routes.append(rec)
        else:
            drop_seen += 1
            if len(drop_routes) < DROP_SAMPLE:
                drop_routes.append(rec)
            elif random.random() < DROP_SAMPLE / drop_seen:  # reservoir sampling
                drop_routes[random.randrange(DROP_SAMPLE)] = rec
z.close()

routes = dist_routes + drop_routes
by_role = collections.Counter(x["cable_role"] for x in routes)
by_type = collections.Counter(x["cable_type_name"] for x in routes)
out = {
    "source": "01 NET.zip NET05 (PLN IconPlus), Malang bbox, real geometry",
    "counts": {"total_routes": len(routes), "distribution_feeder": len(dist_routes),
               "drop_access_kept": len(drop_routes), "drop_access_total": drop_seen},
    "by_role": dict(by_role), "by_type": dict(by_type),
    "routes": routes,
}
json.dump(out, open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print("Wrote", OUT)
print("counts:", out["counts"])
print("by_role:", out["by_role"])
print("by_type:", out["by_type"])
