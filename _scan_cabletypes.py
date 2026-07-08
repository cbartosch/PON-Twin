import zipfile, csv, io, collections, re
ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
BBOX = dict(lat_min=-8.6, lat_max=-7.65, lng_min=112.2, lng_max=113.05)
z = zipfile.ZipFile(ZIP)
name = [n for n in z.namelist() if "NET05" in n and n.lower().endswith(".csv")][0]

def first_coord(geom):
    m = re.search(r"([0-9.]+)\s+(-?[0-9.]+)", geom or "")
    if not m: return None, None
    return float(m.group(1)), float(m.group(2))  # lon, lat

types = collections.Counter(); access = collections.Counter(); oh = collections.Counter()
malang = 0
with z.open(name) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")
    for i, row in enumerate(r):
        if i == 0 or len(row) < 15: continue
        lon, lat = first_coord(row[14])
        if lat is None: continue
        if not (BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lng_min"] <= lon <= BBOX["lng_max"]):
            continue
        malang += 1
        types[row[10].strip().upper()] += 1
        access[row[13].strip()] += 1
        oh[row[12].strip()] += 1
print("Malang bbox cable segments:", malang)
print("cable_type_name:", types.most_common())
print("core_access:", access.most_common())
print("overhead_underground:", oh.most_common())
z.close()
