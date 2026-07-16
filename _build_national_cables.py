"""Extract the national IconPlus cable-route skeleton from the NET05 dump.

01 NET.zip / NET05 holds 1.06M fibre segments WITH LINESTRING geometry across all
11 SBUs. Rendering every segment (incl. ~908k tiny Access drop wires) is neither
feasible over the twin nor useful at national zoom, so we keep only the meaningful
network skeleton — Distribution/feeder + Backbone/Core routes — into a compact
national_cables.json (paths as [lng,lat] rounded to 5 dp).

Like national_points.json this file is read directly from disk by the UI; it is
NOT seeded to Spanner and NOT served over MCP.
"""
import os, io, json, re, zipfile, collections

DL = os.path.expanduser("~/Downloads")
ZIP = os.path.join(DL, "01 NET.zip")
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "national_cables.json")

# Keep the network skeleton only (drop the ~908k Access drop wires).
KEEP_ROLES = {"DISTRIBUTION", "BACKBONE", "CORE"}
NUM = re.compile(r"[-+]?\d*\.?\d+")


def norm_role(s):
    s = (s or "").strip().upper()
    if s.startswith("DISTRIBUTION"):
        return "Distribution / Feeder"
    if s.startswith("BACKBONE"):
        return "Backbone"
    if s.startswith("CORE"):
        return "Core"
    if s.startswith("ACCESS"):
        return "Access"
    return s.title() or "Unknown"


def keep(role_raw):
    r = (role_raw or "").strip().upper()
    return any(r.startswith(k) for k in KEEP_ROLES)


def parse_linestring(g):
    """WKT 'LINESTRING (lng lat, lng lat, ...)' -> [[lng,lat],...] rounded 5dp."""
    if not g or "(" not in g:
        return None
    body = g[g.index("(") + 1: g.rindex(")")]
    pts = []
    for pair in body.split(","):
        nums = NUM.findall(pair)
        if len(nums) >= 2:
            pts.append([round(float(nums[0]), 5), round(float(nums[1]), 5)])
    return pts if len(pts) >= 2 else None


def main():
    z = zipfile.ZipFile(ZIP)
    name = [x for x in z.namelist() if "NET05" in x and "Segment" in x][0]
    t = io.TextIOWrapper(z.open(name), encoding="utf-8", errors="replace")
    hdr = t.readline().rstrip("\n").split("|")
    ix = {c: i for i, c in enumerate(hdr)}
    i_role, i_geom, i_sbu = ix["core_access"], ix["geom"], ix["namaSbu"]
    i_type = ix.get("cable_type_name", -1)
    i_len = ix.get("cable_measured_length", -1)

    cables, per_sbu, per_role = [], collections.Counter(), collections.Counter()
    n = 0
    for line in t:
        n += 1
        if n % 200000 == 0:
            print(f"  ...scanned {n}, kept {len(cables)}", flush=True)
        r = line.rstrip("\n").split("|")
        if len(r) <= i_geom or not keep(r[i_role]):
            continue
        path = parse_linestring(r[i_geom])
        if not path:
            continue
        role = norm_role(r[i_role])
        sbu = (r[i_sbu].strip() if len(r) > i_sbu else "") or "UNSPECIFIED"
        rec = {"path": path, "role": role, "sbu": sbu}
        if i_type >= 0 and len(r) > i_type and r[i_type].strip():
            rec["cable_type"] = r[i_type].strip()
        if i_len >= 0 and len(r) > i_len:
            try:
                rec["len_m"] = round(float(r[i_len]), 1)
            except ValueError:
                pass
        cables.append(rec)
        per_sbu[sbu] += 1
        per_role[role] += 1

    data = {
        "meta": {
            "source": "01 NET.zip / NET05 - Fibre Cable and segments (DRL_NET-05 Segment Cable_v3)",
            "operator": "PLN IconPlus (Operator B)",
            "note": "National cable-route skeleton (Distribution/feeder + Backbone/Core only; "
                    "~908k Access drop wires excluded). Coords rounded to 5 dp. Not seeded to Spanner.",
            "segments_scanned": n,
            "cable_count": len(cables),
            "per_role": dict(per_role),
            "per_sbu": dict(per_sbu),
        },
        "cables": cables,
    }
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    print("wrote", OUT, "size MB:", round(os.path.getsize(OUT) / 1e6, 1))
    print("cables:", len(cables), "roles:", dict(per_role))


if __name__ == "__main__":
    main()
