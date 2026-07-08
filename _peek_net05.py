import zipfile, csv, io
ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
z = zipfile.ZipFile(ZIP)
name = [n for n in z.namelist() if "NET05" in n and n.lower().endswith(".csv")][0]
print("FILE:", name)
with z.open(name) as f:
    r = csv.reader(io.TextIOWrapper(f, encoding="utf-8", errors="replace"), delimiter="|")
    for i, row in enumerate(r):
        if i == 0:
            for k, c in enumerate(row):
                print(f"  [{k}] {c}")
            print("  --- sample rows ---")
        elif i <= 4:
            print("  ", [f"{k}:{v[:28]}" for k, v in enumerate(row)])
        else:
            break
z.close()
