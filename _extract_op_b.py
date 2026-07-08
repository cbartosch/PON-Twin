"""Stream 01 NET.zip, scope to Malang, and emit op_b_real.json mapped to the twin
schema. Replaces synthetic Operator B. Real source: PLN IconPlus FTTH DRL."""
import zipfile, csv, io, json, math, os, re, collections

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "op_b_real.json")

ALLOWED_KAB = {"MALANG", "KAB. MALANG", "KOTA MALANG", "KOTA BATU"}
ANCHORS = {  # from pon_data.json areas
    "MAL-AR-01": (-7.9655, 112.6005), "MAL-AR-02": (-7.9555, 112.6605),
    "MAL-AR-03": (-7.98, 112.6304),   "MAL-AR-04": (-8.005, 112.645),
}
BBOX = dict(lat_min=-8.6, lat_max=-7.65, lng_min=112.2, lng_max=113.05)

z = zipfile.ZipFile(ZIP)
def entry(sub):
    for n in z.namelist():
        if sub in n and n.lower().endswith(".csv"):
            return n
    raise KeyError(sub)
def rows(name, delim):
    with z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter=delim)
        for i, row in enumerate(r):
            yield i, row
def f2(x):
    try: return float(str(x).strip().strip('"'))
    except Exception: return None
def nearest_area(lat, lon):
    best, bd = None, 1e18
    for aid, (la, lo) in ANCHORS.items():
        d = (la-lat)**2 + (lo-lon)**2
        if d < bd: bd, best = d, aid
    return best
def strip_port(fat):
    return re.sub(r"_\d+$", "", fat or "")

# ---- 1) NET07 ONT → Malang homes + referenced OLTs/FATs ----------------------
ont = entry("NET07 ONT CPE/DRL-NET-07_v1.csv")
homes, olt_ref, fat_ref, fat_base = [], collections.Counter(), set(), set()
olt_pts = collections.defaultdict(lambda: [0.0, 0.0, 0])  # sum_lat, sum_lon, n
olt_conn = collections.Counter()  # connected homes per OLT (proxy for homeconnected)
for i, row in rows(ont, ","):
    if i == 0 or len(row) < 13: continue
    kab = row[9].upper().strip()
    if kab not in ALLOWED_KAB: continue
    lat, lon = f2(row[6]), f2(row[7])
    if lat is None or lon is None: continue
    if not (BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lng_min"] <= lon <= BBOX["lng_max"]):
        continue  # drop dirty rows labelled Malang but geolocated elsewhere (e.g. Klaten)
    olt, fat = row[1].strip(), row[3].strip()
    olt_ref[olt] += 1; fat_ref.add(fat); fat_base.add(strip_port(fat))
    p = olt_pts[olt]; p[0] += lat; p[1] += lon; p[2] += 1
    if row[12].strip().upper() == "AKTIF": olt_conn[olt] += 1
    homes.append({
        "home_id": f'HH-B-{row[0].strip().strip(chr(34))}',
        "operator": "Operator B", "operator_code": "B",
        "area_id": nearest_area(lat, lon),
        "latitude": lat, "longitude": lon,
        "olt_hostname": olt, "fat_id": fat, "fat_port": row[4].strip(),
        "ont_brand": row[5].strip(),
        "kabupaten": row[9].strip(), "kecamatan": row[10].strip(), "kelurahan": row[11].strip(),
        "service_status": row[12].strip(), "isolir": row[13].strip() if len(row) > 13 else "",
        "connected": row[12].strip().upper() == "AKTIF",
        "deployment_status": "Actual (PLN IconPlus)",
    })
print(f"[1] Malang homes: {len(homes)}  OLTs referenced: {len(olt_ref)}  FATs: {len(fat_ref)}")
MALANG_OLTS = set(olt_ref)

# ---- 2) NET01 OLT → real B OLTs ---------------------------------------------
olt_geo = {}
for i, row in rows(entry("NET01 OLT & Aggregation/DRL_NET-01_OLT_v1.csv"), "|"):
    if i == 0 or len(row) < 8: continue
    host = row[1].strip().strip('"')
    if host in MALANG_OLTS:
        olt_geo[host] = {"lat": f2(row[6]), "lon": f2(row[7]),
                         "statusPing": row[3].strip().strip('"'), "statusDevice": row[4].strip().strip('"'),
                         "namaSbu": row[5].strip().strip('"'), "site_id": row[0].strip().strip('"')}
print(f"[2] OLT geo matched: {len(olt_geo)} / {len(MALANG_OLTS)}")

# ---- 3) NET02 ports → live/spare per OLT ------------------------------------
ports = collections.defaultdict(lambda: {"live": 0, "spare": 0, "total": 0})
for i, row in rows(entry("NET02 - Active OLT Equipment/DRL_NET-02 OLT port R1_v1.csv"), ","):
    if i == 0 or len(row) < 11: continue
    host = row[0].strip()
    if host not in MALANG_OLTS: continue
    st = row[10].strip().lower()
    p = ports[host]; p["total"] += 1
    if st == "up": p["live"] += 1
    else: p["spare"] += 1
print(f"[3] OLTs with port data: {len(ports)}")

# ---- 4) NET04 splitters → ODP/splitter layer --------------------------------
splitters = []
for i, row in rows(entry("NET04 Splitters/DRL_NET-04_Splitter_v1.csv"), "|"):
    if i == 0 or len(row) < 6: continue
    sid, host = row[0].strip(), row[4].strip()
    if not (sid in fat_ref or sid in fat_base or host in MALANG_OLTS): continue
    lat, lon = f2(row[2]), f2(row[3])
    if lat is None or lon is None: continue
    if not (BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lng_min"] <= lon <= BBOX["lng_max"]):
        continue
    splitters.append({
        "odp_id": sid, "operator": "Operator B", "operator_code": "B",
        "splitter_ratio": row[1].strip(), "latitude": lat, "longitude": lon,
        "olt_hostname": host, "fdt_id": row[5].strip(),
        "area_id": nearest_area(lat, lon), "deployment_status": "Actual (PLN IconPlus)",
    })
print(f"[4] Malang splitters/ODPs: {len(splitters)}")

# ---- 5) NET09 homepass/connected per OLT ------------------------------------
hp = collections.defaultdict(lambda: {"homepass": 0, "homeconnected": 0})
for i, row in rows(entry("NET09 - Homepassed/DRL_NET-09_HP_HC_v1.csv"), ","):
    if i == 0 or len(row) < 6: continue
    host = row[1].strip()
    if host not in MALANG_OLTS: continue
    hp[host]["homepass"] += int(f2(row[4]) or 0)
    hp[host]["homeconnected"] += int(f2(row[5]) or 0)
print(f"[5] OLTs with homepass data: {len(hp)}")

# ---- 6) NET05 cables → aggregate km (drop vs distribution/feeder) -----------
cab = {"drop_m": 0.0, "dist_m": 0.0, "n": 0}
for i, row in rows(entry("NET05 - Fibre Cable and segments/DRL_NET-05 Segment Cable_v3.csv"), "|"):
    if i == 0 or len(row) < 14: continue
    hostA, aloc = row[0].strip(), row[4].strip()
    if not (hostA in MALANG_OLTS or aloc in fat_ref or strip_port(aloc) in fat_base): continue
    m = f2(row[7]) or f2(row[6]) or 0
    typ = (row[10] or "").upper()
    cab["n"] += 1
    if "DROP" in typ: cab["drop_m"] += m
    else: cab["dist_m"] += m
print(f"[6] Malang B cable segments: {cab['n']}  drop_km={cab['drop_m']/1000:.1f} dist_km={cab['dist_m']/1000:.1f}")

# ---- 7) NET06 poles → count in Malang bbox + sample for map -----------------
pole_count = 0; pole_sample = []
for i, row in rows(entry("NET06 Ducts and poles/DRL_NET-06_PolesFTTH_v1.csv"), "|"):
    if i == 0 or len(row) < 7: continue
    lat, lon = f2(row[5]), f2(row[6])
    if lat is None or lon is None: continue
    if BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lng_min"] <= lon <= BBOX["lng_max"]:
        pole_count += 1
        if len(pole_sample) < 2000:
            pole_sample.append({"pole_id": row[3].strip(), "latitude": lat, "longitude": lon,
                                "operator_code": "B", "area_id": nearest_area(lat, lon),
                                "category": row[4].strip(), "owner": row[7].strip()})
print(f"[7] Malang bbox poles: {pole_count} (sampled {len(pole_sample)})")

# ---- Build OLT records ------------------------------------------------------
olts = []
for host, cnt in olt_ref.items():
    g = olt_geo.get(host, {})
    p = ports.get(host, {"live": 0, "spare": 0, "total": 0})
    h = hp.get(host, {"homepass": 0, "homeconnected": 0})
    lat, lon = g.get("lat"), g.get("lon")
    geo_src = "NET01"
    if lat is None or lon is None:  # anonymised hostnames don't join NET01 -> use home centroid
        pt = olt_pts.get(host)
        if pt and pt[2] > 0:
            lat, lon = round(pt[0] / pt[2], 6), round(pt[1] / pt[2], 6)
            geo_src = "home_centroid"
    conn = olt_conn.get(host, 0)
    olts.append({
        "olt_id": f"B-{host}", "hostname": host, "operator": "Operator B", "operator_code": "B",
        "site_id": g.get("site_id"),
        "latitude": lat, "longitude": lon, "geo_source": geo_src,
        "area_id": nearest_area(lat, lon) if lat and lon else None,
        "live_pon_ports": p["live"], "spare_pon_ports": p["spare"],
        "total_pon_ports": p["total"],
        "connected_homes": cnt, "homepass": h["homepass"] or cnt,
        "homeconnected": h["homeconnected"] or conn,
        "status_ping": g.get("statusPing"), "status_device": g.get("statusDevice"),
        "namaSbu": g.get("namaSbu"),
        "olt_role": "Access OLT", "deployment_status": "Actual (PLN IconPlus)",
        "site_type": "PLN IconPlus OLT", "technology": "GPON",
    })

out = {
    "source": "01 NET.zip (PLN IconPlus FTTH DRL), scoped to Malang region",
    "scope_kabupaten": sorted(ALLOWED_KAB),
    "counts": {"olts": len(olts), "splitters_odps": len(splitters), "homes": len(homes),
               "cable_segments": cab["n"], "poles_bbox": pole_count},
    "olts": olts, "splitters": splitters, "homes": homes,
    "cable_summary": {"drop_km": round(cab["drop_m"]/1000, 2), "distribution_km": round(cab["dist_m"]/1000, 2),
                      "total_km": round((cab["drop_m"]+cab["dist_m"])/1000, 2), "segments": cab["n"]},
    "poles": {"count_bbox": pole_count, "sample": pole_sample},
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)
z.close()
print("\nWrote", OUT)
print("SUMMARY:", json.dumps(out["counts"]), "| homes connected:",
      sum(1 for h in homes if h["connected"]))
