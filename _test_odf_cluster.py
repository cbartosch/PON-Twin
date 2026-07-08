"""Salvage test: restrict each Malang OLT's NET05 segments to the Malang bbox,
then check whether the ODF-side endpoints of its DISTRIBUTION feeders cluster
tightly enough to define a real OLT/POP coordinate."""
import zipfile, csv, io, re, collections

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
ALLOWED = {"MALANG", "KAB. MALANG", "KOTA MALANG", "KOTA BATU"}
BBOX = dict(lat_min=-8.6, lat_max=-7.65, lng_min=112.2, lng_max=113.05)
def inbox(lat, lon):
    return BBOX["lat_min"] <= lat <= BBOX["lat_max"] and BBOX["lng_min"] <= lon <= BBOX["lng_max"]
z = zipfile.ZipFile(ZIP)
def entry(sub):
    return [n for n in z.namelist() if sub in n and n.lower().endswith(".csv")][0]

ont = entry("NET07 ONT CPE/DRL-NET-07_v1.csv")
malang_olts = set()
with z.open(ont) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
    for i, row in enumerate(r):
        if i == 0 or len(row) < 13: continue
        if row[9].upper().strip() in ALLOWED:
            try: lat = float(row[6])
            except Exception: continue
            if inbox(lat, float(row[7])): malang_olts.add(row[1].strip())

def coords(geom):
    return [[float(lo), float(la)] for lo, la in re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", geom or "")]

net05 = entry("NET05 - Fibre Cable and segments/DRL_NET-05 Segment Cable_v3.csv")
# per OLT: collect ODF-side endpoints of Distribution segments within bbox
odf_pts = collections.defaultdict(list)
with z.open(net05) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")
    for i, row in enumerate(r):
        if i == 0 or len(row) < 15: continue
        hostA = row[0].strip()
        if hostA not in malang_olts: continue
        if row[13].strip().lower() != "distribution": continue
        if not row[5].strip().upper().startswith("ODF"): continue
        pts = coords(row[14])
        if not pts: continue
        # b_location = ODF; geom ordered a->b so ODF end = last point
        end = pts[-1]
        if inbox(end[1], end[0]):
            odf_pts[hostA].append((round(end[0], 4), round(end[1], 4)))

n_tight = n_loose = 0
print("olt | distr-seg | dominant ODF share | point")
for olt, pts in sorted(odf_pts.items(), key=lambda kv: -len(kv[1]))[:25]:
    c = collections.Counter(pts)
    top, freq = c.most_common(1)[0]
    share = freq / len(pts)
    tight = share >= 0.5
    n_tight += tight; n_loose += (not tight)
    print(f"  {olt[:22]:22} {len(pts):4} {share*100:4.0f}%  {top}  distinct_ODF={len(c)}")
print(f"\nOLTs with distribution segments in bbox: {len(odf_pts)} / {len(malang_olts)}")
print(f"Tight (>=50% one ODF): {sum(1 for p in odf_pts.values() if collections.Counter(p).most_common(1)[0][1]/len(p)>=0.5)}"
      f"  Loose: {sum(1 for p in odf_pts.values() if collections.Counter(p).most_common(1)[0][1]/len(p)<0.5)}")
z.close()
