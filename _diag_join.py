import zipfile, csv, io

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
z = zipfile.ZipFile(ZIP)
def entry(sub):
    for n in z.namelist():
        if sub in n and n.lower().endswith(".csv"):
            return n
    raise KeyError(sub)
def rows(name, delim, n=6):
    with z.open(name) as f:
        r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter=delim)
        for i, row in enumerate(r):
            if i > n: break
            yield i, row

# collect a few Malang OLT hostnames from NET07
ont = entry("NET07 ONT CPE/DRL-NET-07_v1.csv")
sample_olts = set()
ALLOWED = {"MALANG","KAB. MALANG","KOTA MALANG","KOTA BATU"}
with z.open(ont) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"))
    for i,row in enumerate(r):
        if i==0 or len(row)<13: continue
        if row[9].upper().strip() in ALLOWED:
            sample_olts.add(row[1].strip())
        if len(sample_olts)>=8 and i>2000: break
print("Sample NET07 OLT names:", list(sample_olts)[:8])

for label, sub, delim in [
    ("NET01","NET01 OLT & Aggregation/DRL_NET-01_OLT_v1.csv","|"),
    ("NET09","NET09 - Homepassed/DRL_NET-09_HP_HC_v1.csv",","),
]:
    print("\n==== "+label+" ====")
    for i,row in rows(entry(sub), delim):
        if i==0:
            print("HDR:", [f"[{k}]{c}" for k,c in enumerate(row)])
        else:
            print(i, row[:10])
z.close()
