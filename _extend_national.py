"""Extend the Malang PON digital twin to PLN IconPlus's full national footprint.

Sources (in ~/Downloads):
  - DRL_NET-01_OLT_v2 (1) - 260715.xlsx   : 5,104 OLT sites nationwide
  - DRL_ServingArea_Polygon.gdb.zip       : 355,702 FAT serving-area polygons
                                             (secondary splitters), 292,687 FDTs

Design:
  * Preserve existing Malang full-detail data (homes/poles/cables/odps).
  * Add national layers as LIGHTWEIGHT point records (no polygon geometry,
    which would be ~40M vertices / GBs):
      - olts       += 5,104 real OLT sites
      - splitters  += FDT primary splitters (unique fdt_id, keyed primary_splitter_id)
      - odps       += FAT secondary splitters (355,702)
      - areas      += KP-level national areas + SBU tier-2 rollups
  * Everything tagged operator "Operator B" / scope "national-footprint" so the
    original Malang deep-dive records stay distinguishable.
"""
import os, json, re, unicodedata, collections, sys

DL = os.path.expanduser("~/Downloads")
# summary noted a space in the filename
XLSX = os.path.join(DL, "DRL_NET-01_OLT_v2 (1) - 260715.xlsx")
GDB  = "zip://" + os.path.join(DL, "DRL_ServingArea_Polygon.gdb.zip")
HERE = os.path.dirname(os.path.abspath(__file__))
PON  = os.path.join(HERE, "pon_data.json")


def slug(s):
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").upper()
    return s or "UNKNOWN"


def ratio_homes(r):
    try:
        return int(str(r).split(":")[-1].strip())
    except Exception:
        return 8


def main():
    import pandas as pd
    import fiona

    with open(PON, encoding="utf-8") as f:
        D = json.load(f)

    # ---- track areas we build (KP level) + SBU tier-2 parents ----
    areas = {}          # area_id -> record
    sbu_children = collections.defaultdict(set)
    olt_by_area = collections.Counter()
    fdt_by_area = collections.Counter()
    fat_by_area = collections.Counter()
    homes_by_area = collections.Counter()
    area_lat = collections.defaultdict(float)
    area_lon = collections.defaultdict(float)
    area_n   = collections.Counter()

    def area_id_for(sbu, kp):
        aid = "ICON-" + slug(kp)
        sbu_clean = isinstance(sbu, str) and sbu.strip() not in ("", "c") and slug(sbu) != "UNSPECIFIED"
        if aid in areas and sbu_clean and areas[aid]["tier2_parent_code"] == "SBU-UNSPECIFIED":
            # upgrade a provisionally-orphaned area to its real SBU parent
            old = areas[aid]["tier2_parent_code"].replace("SBU-", "")
            sbu_children[old].discard(aid)
            areas[aid]["tier2_parent_code"] = "SBU-" + slug(sbu)
            areas[aid]["tier2_parent_name"] = str(sbu).title()
            areas[aid]["witel"] = str(sbu).title()
            sbu_children[slug(sbu)].add(aid)
        if aid not in areas:
            areas[aid] = {
                "area_id": aid,
                "area_name": str(kp).title(),
                "sto_name_official": None,
                "archetype": "Operator B national footprint",
                "tier": 3,
                "tier2_parent_code": "SBU-" + slug(sbu),
                "tier2_parent_name": str(sbu).title(),
                "datel": str(kp).title(),
                "witel": str(sbu).title(),
                "anchor_latitude": None,
                "anchor_longitude": None,
                "operator_A_live_ports": 0, "operator_A_spare_ports": 0,
                "operator_B_live_ports": 0, "operator_B_spare_ports": 0,
                "connected_homes_operator_A": 0,
                "connected_homes_operator_B": 0,
                "dominance_test": "Operator B only",
                "scope": "national-footprint",
                "notes": f"PLN IconPlus footprint area (KP={kp}, SBU={sbu}).",
            }
            sbu_children[slug(sbu)].add(aid)
        return aid

    # ================= OLTs =================
    print("reading OLT xlsx ...", flush=True)
    df = pd.read_excel(XLSX)
    new_olts = []
    for _, r in df.iterrows():
        sbu = r.get("namaSbu"); kp = r.get("namaKp")
        if not isinstance(kp, str) or kp.strip() in ("", "c"):
            kp = "UNSPECIFIED"
        if not isinstance(sbu, str) or sbu.strip() in ("", "c"):
            sbu = "UNSPECIFIED"
        aid = area_id_for(sbu, kp)
        lat = r.get("geo_lat"); lon = r.get("geo_lon")
        host = str(r.get("hostname") or "").strip()
        oid = str(r.get("site_id") or host)
        olt_by_area[aid] += 1
        if lat == lat and lon == lon:  # not NaN
            area_lat[aid] += float(lat); area_lon[aid] += float(lon); area_n[aid] += 1
        new_olts.append({
            "olt_id": "B-" + oid + "-" + slug(host)[:24],
            "operator": "Operator B", "operator_code": "B",
            "area_id": aid, "area_name": str(kp).title(),
            "archetype": "Operator B national footprint",
            "latitude": float(lat) if lat == lat else None,
            "longitude": float(lon) if lon == lon else None,
            "olt_role": "Access OLT",
            "deployment_status": "Actual (PLN IconPlus)",
            "site_type": "PLN IconPlus OLT",
            "technology": str(r.get("cek data mas sidik") or "GPON"),
            "hostname": host,
            "geo_source": "DRL_NET-01_OLT_v2",
            "status_ping": r.get("statusPing"),
            "status_device": r.get("statusDevice"),
            "sbu": str(sbu).title(),
            "upe_hostname": str(r.get("HOSTNAME UPE ") or "").strip() or None,
            "scope": "national-footprint",
            "notes": "Actual Operator B OLT (PLN IconPlus), national footprint.",
        })
    print(f"  OLTs: {len(new_olts)}", flush=True)

    # ================= FAT / FDT serving areas =================
    # NOTE: 355,702 FAT polygons -> 655k point records would push pon_data.json to
    # ~267MB (over GitHub's 100MB limit) and overload the RAM-backed Spanner emulator.
    # We iterate the GDB only to AGGREGATE per-area rollups (OLT/FDT/FAT/home counts +
    # centroid). Full per-splitter geometry stays in the source GDB. FDT ids are
    # deduped in a set (cheap) purely for the primary-splitter count.
    print("reading serving-area GDB (355k features) for area rollups ...", flush=True)
    src = fiona.open(GDB, layer="DRL_FAT_Cov250")
    fdt_seen = set()
    fdt_seen_by_area = collections.defaultdict(set)
    new_odps = []       # kept empty at national scale (aggregates only)
    fdt_records = []    # kept empty at national scale (aggregates only)
    n = 0
    for feat in src:
        p = feat["properties"]
        sbu = p.get("namaSbu") or "UNSPECIFIED"
        kp  = p.get("namaKp") or "UNSPECIFIED"
        aid = area_id_for(sbu, kp)
        lat = p.get("lat"); lng = p.get("lng")
        ratio = p.get("splitter_ratio") or "1:8"
        hs = ratio_homes(ratio)
        fdt_id = p.get("fdt_id") or "-"
        fat_by_area[aid] += 1
        homes_by_area[aid] += hs
        if lat is not None and lng is not None:
            area_lat[aid] += float(lat); area_lon[aid] += float(lng); area_n[aid] += 1
        if fdt_id and fdt_id != "-":
            fdt_seen.add(fdt_id)
            fdt_seen_by_area[aid].add(fdt_id)
        n += 1
        if n % 50000 == 0:
            print(f"  ...{n} features", flush=True)
    for aid, s in fdt_seen_by_area.items():
        fdt_by_area[aid] = len(s)
    total_fdt = len(fdt_seen)
    print(f"  FAT features: {n}  unique FDT: {total_fdt}", flush=True)

    # ================= finalize areas =================
    for aid, a in areas.items():
        if area_n[aid]:
            a["anchor_latitude"] = round(area_lat[aid] / area_n[aid], 6)
            a["anchor_longitude"] = round(area_lon[aid] / area_n[aid], 6)
        a["olt_count"] = olt_by_area[aid]
        a["primary_splitter_count"] = fdt_by_area[aid]
        a["fat_count"] = fat_by_area[aid]
        a["connected_homes_operator_B"] = homes_by_area[aid]
        a["connected_homes_total"] = homes_by_area[aid]

    # SBU tier-2 rollup areas
    for sbu_code, kids in sbu_children.items():
        aid = "SBU-" + sbu_code
        name = next((areas[k]["tier2_parent_name"] for k in kids), sbu_code.title())
        lat = [areas[k]["anchor_latitude"] for k in kids if areas[k]["anchor_latitude"] is not None]
        lon = [areas[k]["anchor_longitude"] for k in kids if areas[k]["anchor_longitude"] is not None]
        areas[aid] = {
            "area_id": aid, "area_name": name,
            "archetype": "Operator B SBU aggregation", "tier": 2,
            "anchor_latitude": round(sum(lat)/len(lat), 6) if lat else None,
            "anchor_longitude": round(sum(lon)/len(lon), 6) if lon else None,
            "child_area_ids": sorted(kids),
            "olt_count": sum(olt_by_area[k] for k in kids),
            "primary_splitter_count": sum(fdt_by_area[k] for k in kids),
            "fat_count": sum(fat_by_area[k] for k in kids),
            "connected_homes_operator_B": sum(homes_by_area[k] for k in kids),
            "scope": "national-footprint",
            "notes": f"SBU aggregation rollup of {len(kids)} footprint areas.",
        }

    # ================= merge into D =================
    D["olts"].extend(new_olts)
    # splitters/odps not extended at national scale (aggregates carried on areas)
    existing_area_ids = {a.get("area_id") for a in D["areas"]}
    for aid, a in areas.items():
        if aid not in existing_area_ids:
            D["areas"].append(a)

    # national dashboard summary
    D["national_footprint"] = {
        "operator": "PLN IconPlus (Operator B)",
        "source_olt_file": os.path.basename(XLSX),
        "source_servingarea_file": "DRL_ServingArea_Polygon.gdb.zip",
        "sbu_count": len(sbu_children),
        "kp_area_count": len(sbu_children) and len([a for a in areas if a.startswith("ICON-")]),
        "olts": len(new_olts),
        "primary_splitters_fdt": total_fdt,
        "secondary_splitters_fat": n,
        "homes_served_estimate": sum(homes_by_area.values()),
        "granularity": "area-rollup",
        "note": "National footprint carried as OLT points + SBU/KP area rollups "
                "(OLT/FDT/FAT/home counts). Per-FAT polygon geometry (355,702 "
                "features) stays in source GDB DRL_ServingArea_Polygon.gdb.zip; "
                "not seeded to keep pon_data.json <100MB and emulator light. "
                "Malang retains full asset detail (homes/poles/cables/odps).",
    }

    # backup + write
    bak = PON + ".bak5"
    if not os.path.exists(bak):
        os.replace(PON, bak) if False else None
    with open(PON + ".bak5", "w", encoding="utf-8") as f:
        json.dump(json.load(open(PON, encoding="utf-8")), f)  # snapshot old
    with open(PON, "w", encoding="utf-8") as f:
        json.dump(D, f, ensure_ascii=False)

    print("\n=== extended pon_data.json ===", flush=True)
    print("size MB:", round(os.path.getsize(PON) / 1e6, 1))
    print({k: (len(v) if isinstance(v, list) else "dict") for k, v in D.items()})


if __name__ == "__main__":
    main()
