import zipfile, io, csv, os

ZIP = r"C:\Users\bartosch christian\Downloads\01 NET.zip"
z = zipfile.ZipFile(ZIP)
csvs = [n for n in z.namelist() if n.lower().endswith(".csv")]
for name in csvs:
    print("\n" + "=" * 100)
    print("FILE:", name)
    with z.open(name) as f:
        # read first ~8KB to get header + a few rows
        head = f.read(8192)
    text = head.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        print("  (empty)")
        continue
    # detect delimiter
    delim = ";" if lines[0].count(";") > lines[0].count(",") else ","
    print(f"  delimiter='{delim}'  header cols:")
    hdr = next(csv.reader([lines[0]], delimiter=delim))
    for i, c in enumerate(hdr):
        print(f"    [{i}] {c}")
    print("  --- sample rows ---")
    for ln in lines[1:4]:
        print("   ", ln[:240])
z.close()
