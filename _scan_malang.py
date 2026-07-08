import zipfile, csv, io, collections

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
z = zipfile.ZipFile(ZIP)

def entry(name_sub):
    for n in z.namelist():
        if name_sub in n and n.lower().endswith(".csv"):
            return n
    raise KeyError(name_sub)

def stream_lines(name):
    with z.open(name) as f:
        for raw in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
            yield raw.rstrip("\n")

# ---- NET07 ONT: find Malang homes (kabupaten col index 9) ----
ont = entry("NET07 ONT CPE/DRL-NET-07_v1.csv")
kab_counter = collections.Counter()
malang_olts = collections.Counter()
malang_fats = set()
malang_homes = 0
total = 0
for i, line in enumerate(stream_lines(ont)):
    if i == 0:
        continue
    total += 1
    row = next(csv.reader([line]))
    if len(row) < 12:
        continue
    kab = row[9].upper()
    if "MALANG" in kab or "BATU" == kab.replace("KOTA ", "").strip():
        kab_counter[kab] += 1
        malang_olts[row[1]] += 1
        malang_fats.add(row[3])
        malang_homes += 1
    if total % 500000 == 0:
        print(f"  ...scanned {total} ONT rows, malang so far {malang_homes}")

print("TOTAL ONT rows:", total)
print("Malang homes:", malang_homes)
print("Malang kabupaten breakdown:", dict(kab_counter))
print("Distinct Malang OLTs:", len(malang_olts))
print("Top Malang OLTs:", malang_olts.most_common(10))
print("Distinct Malang FATs (splitters):", len(malang_fats))
z.close()
