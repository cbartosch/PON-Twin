"""Extract compact national mapping points from the DRL serving-area GDB.

Produces national_points.json with lightweight lat/lng points so the twin UI can
render the FULL PLN IconPlus footprint (ODPs/FAT access points + FDT primary
splitters) across Indonesia. This file is NOT seeded into Spanner (it would bloat
the RAM-backed emulator); the app/server load it directly from disk.

Kept minimal (lat, lng, area, sbu, ratio) to stay well under the git file limit.
"""
import os, json, re, unicodedata, collections
import fiona

DL = os.path.expanduser("~/Downloads")
GDB = "zip://" + os.path.join(DL, "DRL_ServingArea_Polygon.gdb.zip")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "national_points.json")


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return (re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()) or "UNKNOWN"


def main():
    src = fiona.open(GDB, layer="DRL_FAT_Cov250")
    odps = []
    per_sbu = collections.Counter()
    n = 0
    for feat in src:
        p = feat["properties"]
        lat = p.get("lat"); lng = p.get("lng")
        if lat is None or lng is None:
            continue
        sbu = slug(p.get("namaSbu") or "UNSPECIFIED")
        kp = slug(p.get("namaKp") or "UNSPECIFIED")
        # round coords to 5 dp (~1.1 m) to shrink the file
        la = round(float(lat), 5); lo = round(float(lng), 5)
        odps.append({"lat": la, "lng": lo, "area": "ICON-" + kp, "sbu": sbu})
        per_sbu[sbu] += 1
        n += 1
        if n % 50000 == 0:
            print(f"  ...{n}", flush=True)

    data = {
        "meta": {
            "source": "DRL_ServingArea_Polygon.gdb.zip (DRL_FAT_Cov250)",
            "operator": "PLN IconPlus (Iconnect)",
            "note": "Compact national ODP/FAT mapping points. Not seeded to Spanner. "
                    "Coords rounded to 5 dp. Polygon geometry omitted.",
            "odp_count": len(odps),
            "per_sbu": dict(per_sbu),
        },
        "odps": odps,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", OUT, "size MB:", round(os.path.getsize(OUT) / 1e6, 1))
    print("odps:", len(odps))


if __name__ == "__main__":
    main()
