"""Investigate whether NET05 hostnameA joins to the OLT hostnames used in NET07,
and whether feeder/distribution segments yield a real OLT/POP coordinate
(the ODF-side endpoint). Read-only analysis; writes nothing."""
import zipfile, csv, io, re, collections

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
ALLOWED = {"MALANG", "KAB. MALANG", "KOTA MALANG", "KOTA BATU"}
BBOX = dict(lat_min=-8.6, lat_max=-7.65, lng_min=112.2, lng_max=113.05)
z = zipfile.ZipFile(ZIP)
def entry(sub):
    return [n for n in z.namelist() if sub in n and n.lower().endswith(".csv")][0]

# 1) Malang OLT hostnames from NET07
ont = entry("NET07 ONT CPE/DRL-NET-07_v1.csv")
malang_olts = set()
with z.open(ont) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
    for i, row in enumerate(r):
        if i == 0 or len(row) < 13: continue
        if row[9].upper().strip() in ALLOWED:
            lat = row[6]; lon = row[7]
            try:
                if not (BBOX["lat_min"] <= float(lat) <= BBOX["lat_max"]): continue
            except Exception: continue
            malang_olts.add(row[1].strip())
print("Malang OLT hostnames (NET07):", len(malang_olts))

# 2) Scan NET05: how many rows' hostnameA is a Malang OLT? what b_location prefixes?
def coords(geom):
    pts = re.findall(r"(-?\d+\.\d+)\s+(-?\d+\.\d+)", geom or "")
    return [[float(lo), float(la)] for lo, la in pts]

net05 = entry("NET05 - Fibre Cable and segments/DRL_NET-05 Segment Cable_v3.csv")
matched = 0
bprefix = collections.Counter(); aprefix = collections.Counter()
access_bkt = collections.Counter()
per_olt_endpoints = collections.defaultdict(list)  # olt -> list of ODF-side endpoints
sample = []
with z.open(net05) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")
    for i, row in enumerate(r):
        if i == 0 or len(row) < 15: continue
        hostA = row[0].strip()
        if hostA not in malang_olts: continue
        matched += 1
        aloc, bloc = row[4].strip(), row[5].strip()
        aprefix[aloc.split("_")[0]] += 1
        bprefix[bloc.split("_")[0]] += 1
        access_bkt[row[13].strip()] += 1
        pts = coords(row[14])
        # ODF end: whichever endpoint corresponds to b_location ODF (assume last pt),
        # collect both ends for clustering analysis
        if pts:
            per_olt_endpoints[hostA].append((pts[0], pts[-1], bloc[:12], aloc[:12]))
        if len(sample) < 6:
            sample.append((hostA[:22], aloc[:18], bloc[:18], row[13].strip(),
                           row[10].strip(), pts[0] if pts else None, pts[-1] if pts else None))
print("NET05 rows with hostnameA in Malang OLTs:", matched)
print("a_location prefixes:", aprefix.most_common(8))
print("b_location prefixes:", bprefix.most_common(8))
print("core_access:", access_bkt.most_common())
print("OLTs with >=1 NET05 segment:", len(per_olt_endpoints), "/", len(malang_olts))
print("\nSample rows (hostA | a_loc | b_loc | access | type | first | last):")
for s in sample:
    print("  ", s)

# 3) For a few OLTs, check whether one endpoint clusters tightly (=> ODF/OLT site)
print("\nEndpoint clustering per OLT (does a common point exist?):")
shown = 0
for olt, segs in per_olt_endpoints.items():
    if len(segs) < 5: continue
    # round both endpoints; find most common rounded point across all endpoints
    cnt = collections.Counter()
    for a, b, bl, al in segs:
        cnt[(round(a[0], 4), round(a[1], 4))] += 1
        cnt[(round(b[0], 4), round(b[1], 4))] += 1
    top, freq = cnt.most_common(1)[0]
    print(f"  {olt[:24]:24} segs={len(segs):3} top_point={top} freq={freq} "
          f"({100*freq/(2*len(segs)):.0f}% of endpoints)")
    shown += 1
    if shown >= 12: break
z.close()
