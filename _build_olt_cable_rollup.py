"""Extend the cable/ODP model from Malang to ALL national PLN IconPlus (Operator B)
OLTs -- analytics-grade rollup (Option B).

Every national B OLT gets a compact `cable_model` derived from the real IconPlus
plant, WITHOUT seeding 1.06M cable segments / 355k FAT points into Spanner (which
would blow the 100MB git limit and the RAM-backed emulator). Instead we attribute
plant to OLTs SPATIALLY (nearest OLT by coordinate), because the source hostnames
are masked and do not join cleanly:

  * NET05 (01 NET.zip, 1.06M fibre segments, WKT geometry) -> route-km by role
    (distribution/feeder, access/drop, backbone/core), segment counts.
  * DRL_ServingArea_Polygon.gdb (355,702 FAT serving areas) -> ODP count +
    homes-passed estimate (from splitter_ratio) per OLT.

Each segment/FAT is assigned to the nearest B OLT via a 0.05 deg grid index
(fallback to a wider ring if the tight ring is empty; dropped only if no OLT is
within ~11 km). Per-OLT rollups are also aggregated to the area records and a
national cable summary. Malang OLTs keep their existing full segment geometry in
D["cables"]; this only ADDS the rollup fields.

Writes pon_data.json.bak7.  Run:  python _build_olt_cable_rollup.py [--dry-run]
"""
import argparse
import collections
import io
import json
import math
import os
import re
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")
DL = os.path.expanduser("~/Downloads")
NET_ZIP = os.path.join(DL, "01 NET.zip")
GDB = "zip://" + os.path.join(DL, "DRL_ServingArea_Polygon.gdb.zip")

CELL = 0.05                     # grid cell size in degrees (~5.5 km)
NUM = re.compile(r"[-+]?\d*\.?\d+")
# NET05's length columns contain corrupt outliers (e.g. a "DROP WIRE" logged as
# 22,785 km); ~69 rows inject hundreds of thousands of bogus km. Real segments are
# sub-km to a few km, so cap at 20 km and take the smallest plausible candidate.
MAX_SEG_M = 20_000.0


def segment_length_m(cols):
    """Pick a plausible length from measured/calculated/spatial columns (7,8,6)."""
    cands = []
    for k in (7, 8, 6):
        try:
            v = float(cols[k])
        except (ValueError, IndexError):
            continue
        if 0 < v <= MAX_SEG_M:
            cands.append(v)
    return min(cands) if cands else 0.0


def role_bucket(core_access):
    r = (core_access or "").strip().upper()
    if r.startswith("DISTRIBUTION"):
        return "distribution"
    if r.startswith("BACKBONE") or r.startswith("CORE"):
        return "backbone_core"
    return "access"             # Access / drop wires (default)


def ratio_homes(r):
    try:
        return int(str(r).split(":")[-1].strip())
    except Exception:
        return 8


class OltGrid:
    """Nearest-OLT lookup over B OLT coordinates using a lat/lng grid."""

    def __init__(self, olts):
        self.olts = olts
        self.grid = collections.defaultdict(list)
        for i, o in enumerate(olts):
            self.grid[(int(o["latitude"] // CELL), int(o["longitude"] // CELL))].append(i)

    def _search(self, la, lo, rings):
        cy, cx = int(la // CELL), int(lo // CELL)
        best_i, best_d = None, 1e18
        for dy in range(-rings, rings + 1):
            for dx in range(-rings, rings + 1):
                for i in self.grid.get((cy + dy, cx + dx), ()):
                    o = self.olts[i]
                    d = (o["latitude"] - la) ** 2 + (o["longitude"] - lo) ** 2
                    if d < best_d:
                        best_d, best_i = d, i
        return best_i

    def nearest(self, la, lo):
        i = self._search(la, lo, 1)
        if i is None:               # widen once to ~11 km before giving up
            i = self._search(la, lo, 2)
        return i


def scan_net05(grid, n_olts):
    """Return per-OLT-index dict of route-km by role + segment counts."""
    roll = collections.defaultdict(lambda: {
        "km_distribution": 0.0, "km_access": 0.0, "km_backbone_core": 0.0,
        "seg_distribution": 0, "seg_access": 0, "seg_backbone_core": 0})
    z = zipfile.ZipFile(NET_ZIP)
    name = [n for n in z.namelist() if "NET05" in n and n.lower().endswith(".csv")][0]
    matched = missed = bad = 0
    with z.open(name) as f:
        t = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
        next(t)
        for ln, line in enumerate(t, 1):
            if ln % 200000 == 0:
                print(f"  NET05 ...{ln:,} scanned, {matched:,} matched", flush=True)
            c = line.rstrip("\n").split("|")
            if len(c) < 15:
                bad += 1
                continue
            g = c[14]
            if "(" not in g:
                bad += 1
                continue
            nums = NUM.findall(g[g.index("(") + 1:])
            if len(nums) < 2:
                bad += 1
                continue
            lo, la = float(nums[0]), float(nums[1])   # LINESTRING is (lng lat, ...)
            length = segment_length_m(c)              # min plausible of cols 7,8,6 (<=20km)
            i = grid.nearest(la, lo)
            if i is None:
                missed += 1
                continue
            matched += 1
            b = role_bucket(c[13])
            roll[i][f"km_{b}"] += length / 1000.0
            roll[i][f"seg_{b}"] += 1
    z.close()
    print(f"  NET05 done: matched={matched:,} no-OLT={missed:,} bad_geom={bad:,}")
    return roll


def scan_serving_area(grid):
    """Return per-OLT-index dict of ODP count + homes-passed estimate."""
    import fiona
    roll = collections.defaultdict(lambda: {"odps": 0, "homes": 0})
    src = fiona.open(GDB, layer="DRL_FAT_Cov250")
    matched = missed = 0
    for n, feat in enumerate(src, 1):
        if n % 50000 == 0:
            print(f"  FAT ...{n:,} scanned, {matched:,} matched", flush=True)
        p = feat["properties"]
        la, lo = p.get("lat"), p.get("lng")
        if la is None or lo is None:
            continue
        i = grid.nearest(float(la), float(lo))
        if i is None:
            missed += 1
            continue
        matched += 1
        roll[i]["odps"] += 1
        roll[i]["homes"] += ratio_homes(p.get("splitter_ratio") or "1:8")
    print(f"  FAT done: matched={matched:,} no-OLT={missed:,}")
    return roll


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-fat", action="store_true", help="cables only (skip serving-area GDB)")
    args = ap.parse_args()

    d = json.load(open(PON, encoding="utf-8"))
    b_olts = [o for o in d["olts"]
              if o.get("operator_code") == "B"
              and o.get("latitude") is not None and o.get("longitude") is not None]
    print(f"B OLTs with coords: {len(b_olts)} / "
          f"{sum(1 for o in d['olts'] if o.get('operator_code') == 'B')}")
    grid = OltGrid(b_olts)

    print("Scanning NET05 fibre segments (1.06M) ...")
    cab = scan_net05(grid, len(b_olts))

    fat = {} if args.skip_fat else (
        print("Scanning serving-area FAT (355k) ...") or scan_serving_area(grid))

    # --- write per-OLT cable_model + roll up to areas + national summary --------
    area_roll = collections.defaultdict(lambda: collections.Counter())
    nat = collections.Counter()
    covered = 0
    for i, o in enumerate(b_olts):
        cm = cab.get(i)
        fm = fat.get(i) if fat else None
        if not cm and not fm:
            o["cable_model"] = {"status": "no_plant_within_11km", "geo_basis": "nearest-OLT spatial join"}
            continue
        cm = cm or {"km_distribution": 0.0, "km_access": 0.0, "km_backbone_core": 0.0,
                    "seg_distribution": 0, "seg_access": 0, "seg_backbone_core": 0}
        km_total = cm["km_distribution"] + cm["km_access"] + cm["km_backbone_core"]
        seg_total = cm["seg_distribution"] + cm["seg_access"] + cm["seg_backbone_core"]
        odp = fm["odps"] if fm else None
        homes = fm["homes"] if fm else None
        o["cable_model"] = {
            "route_km_distribution": round(cm["km_distribution"], 2),
            "route_km_access": round(cm["km_access"], 2),
            "route_km_backbone_core": round(cm["km_backbone_core"], 2),
            "route_km_total": round(km_total, 2),
            "segment_count": seg_total,
            "odp_count": odp,
            "homes_passed_est": homes,
            "source": "NET05 fibre segments + DRL serving-area FAT (PLN IconPlus)",
            "geo_basis": "nearest-OLT spatial join (hostnames masked; coords used)",
        }
        covered += 1
        aid = o.get("area_id")
        if aid:
            ar = area_roll[aid]
            ar["route_km_distribution"] += cm["km_distribution"]
            ar["route_km_access"] += cm["km_access"]
            ar["route_km_backbone_core"] += cm["km_backbone_core"]
            ar["route_km_total"] += km_total
            ar["segment_count"] += seg_total
            if odp:
                ar["odp_count"] += odp
            if homes:
                ar["homes_passed_est"] += homes
        nat["route_km_total"] += km_total
        nat["route_km_distribution"] += cm["km_distribution"]
        nat["route_km_access"] += cm["km_access"]
        nat["route_km_backbone_core"] += cm["km_backbone_core"]
        nat["segment_count"] += seg_total
        if odp:
            nat["odp_count"] += odp
        if homes:
            nat["homes_passed_est"] += homes

    # attach area rollups onto area records
    a_by_id = {a["area_id"]: a for a in d["areas"]}
    for aid, ar in area_roll.items():
        a = a_by_id.get(aid)
        if not a:
            continue
        a["operator_B_cable_model"] = {
            "route_km_distribution": round(ar["route_km_distribution"], 1),
            "route_km_access": round(ar["route_km_access"], 1),
            "route_km_backbone_core": round(ar["route_km_backbone_core"], 1),
            "route_km_total": round(ar["route_km_total"], 1),
            "segment_count": int(ar["segment_count"]),
            "odp_count": int(ar["odp_count"]) or None,
            "homes_passed_est": int(ar["homes_passed_est"]) or None,
        }

    d.setdefault("national_footprint", {})["operator_B_cable_model"] = {
        "olts_with_plant": covered,
        "olts_total_b": sum(1 for o in d["olts"] if o.get("operator_code") == "B"),
        "route_km_total": round(nat["route_km_total"], 1),
        "route_km_distribution": round(nat["route_km_distribution"], 1),
        "route_km_access": round(nat["route_km_access"], 1),
        "route_km_backbone_core": round(nat["route_km_backbone_core"], 1),
        "segment_count": int(nat["segment_count"]),
        "odp_count": int(nat["odp_count"]) or None,
        "homes_passed_est": int(nat["homes_passed_est"]) or None,
        "method": ("Per-OLT rollup of real IconPlus plant (NET05 segments + serving-area "
                   "FAT) attributed to the nearest B OLT by coordinate. Full geometry is "
                   "NOT seeded (kept in source); this is the analytics-grade cable model."),
    }

    # --- surface the national B footprint on the dashboard (mirror Operator A) --
    nfb = d["national_footprint"]["operator_B_cable_model"]
    dash = d.get("dashboard", [])
    relabel = {
        "Operator B OLTs (actual)": ("Operator B OLTs in Malang",
                                      "PLN IconPlus FTTH, granular twin (Malang kabupaten)"),
        "Operator B ODPs (actual)": ("Operator B ODPs in Malang", "NET04 splitters (Malang)"),
        "Operator B homes (actual)": ("Operator B homes in Malang", "NET07 ONT (Malang kabupaten)"),
        "Operator B drop cable (actual)": ("Operator B drop cable in Malang", "NET05 aggregate (Malang)"),
        "Operator B distribution cable (actual)": ("Operator B distribution cable in Malang",
                                                   "NET05 aggregate (Malang)"),
    }
    have_national = any(r.get("Metric") == "Operator B OLTs (national)" for r in dash)
    for r in dash:
        m = r.get("Metric")
        if m in relabel:
            r["Metric"], r["Comment"] = relabel[m]
        elif m == "Live PON ports":
            r["Comment"] = "Operator A (national) + Operator B (Malang) live ports"
        elif m == "Spare PON ports":
            r["Comment"] = "Operator A (national) + Operator B (Malang) spare ports"
    if not have_national:
        nat_rows = [
            {"Metric": "Operator B OLTs (national)", "Value": nfb["olts_total_b"], "Unit": "ea",
             "Comment": f"PLN IconPlus national; {nfb['olts_with_plant']:,} with modeled plant within ~11km"},
            {"Metric": "Operator B ODPs (national)", "Value": nfb["odp_count"], "Unit": "ea",
             "Comment": "DRL serving-area FAT, nearest-OLT spatial join"},
            {"Metric": "Operator B homes passed (national, est)", "Value": nfb["homes_passed_est"], "Unit": "home",
             "Comment": "Estimated from FAT splitter_ratio"},
            {"Metric": "Operator B route-km (national)", "Value": nfb["route_km_total"], "Unit": "km",
             "Comment": (f"NET05 fibre: access {nfb['route_km_access']:,.0f} + distribution "
                         f"{nfb['route_km_distribution']:,.0f} + bb/core {nfb['route_km_backbone_core']:,.0f}")},
        ]
        idx = next((i for i, r in enumerate(dash) if r.get("Metric") == "Area"), len(dash))
        d["dashboard"] = dash[:idx] + nat_rows + dash[idx:]

    print(f"\nOLTs given a cable_model: {covered} / {len(b_olts)}")
    print(f"National route-km: total={nat['route_km_total']:,.0f} "
          f"(dist={nat['route_km_distribution']:,.0f} access={nat['route_km_access']:,.0f} "
          f"bb/core={nat['route_km_backbone_core']:,.0f})")
    print(f"National ODPs attributed: {nat['odp_count']:,}  homes est: {nat['homes_passed_est']:,}")

    if args.dry_run:
        print("\n[dry-run] pon_data.json NOT written.")
        return
    shutil.copyfile(PON, PON + ".bak7")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"\nWrote {PON} (backup pon_data.json.bak7).")


if __name__ == "__main__":
    main()
