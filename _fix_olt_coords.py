"""Repair corrupted Telkom (NET-02) OLT coordinates found by the audit.

The Telkom coordinate ingest left 693 OLTs outside the Indonesia bbox
(lat -11..6, lng 95..141). Three failure modes, each handled conservatively:

  1. SWAPPED  - lat/lng reversed; valid when transposed  -> swap in place.
  2. DECIMAL  - a field lost its decimal point (e.g. -44604205 == -4.4604205);
                divide by powers of ten until it lands in range. Only applied
                when the resulting (lat,lng) pair is a valid Indonesia point.
  3. UNRECOVERABLE - 1.0/1.0 placeholders, lat==lng duplication, or anything
                that neither swap nor decimal-shift can rescue -> null both
                fields (the OLT keeps all counts/BoQ; it is simply not plotted).

Counts, BoQ, dashboard, and national_footprint are untouched. Only per-OLT
latitude/longitude are edited. Reads/writes pon_data.json (backup .bak14).
Run: python _fix_olt_coords.py
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")

LAT = (-11.0, 6.0)
LNG = (95.0, 141.0)


def inbox(lat, lng):
    return (lat is not None and lng is not None
            and LAT[0] <= lat <= LAT[1] and LNG[0] <= lng <= LNG[1])


def shift_into(v, lo, hi):
    """Try dividing |v| by powers of ten until it falls in [lo,hi]. Preserve sign."""
    if v is None:
        return None
    sign = -1.0 if v < 0 else 1.0
    a = abs(float(v))
    for _ in range(12):
        if lo <= sign * a <= hi:
            return round(sign * a, 7)
        if a < abs(lo) and a < abs(hi):
            break
        a /= 10.0
    return None


def main():
    d = json.load(open(PON, encoding="utf-8"))
    olts = d["olts"]

    n_swap = n_decimal = n_null = 0
    for o in olts:
        lat, lng = o.get("latitude"), o.get("longitude")
        if lat is None or lng is None or inbox(lat, lng):
            continue

        # 1. swapped
        if inbox(lng, lat):
            o["latitude"], o["longitude"] = lng, lat
            n_swap += 1
            continue

        # unrecoverable: placeholder or duplicated single value
        if (lat == 1.0 and lng == 1.0) or lat == lng:
            o["latitude"] = o["longitude"] = None
            n_null += 1
            continue

        # 2. decimal shift (try both orientations)
        rl, rg = shift_into(lat, *LAT), shift_into(lng, *LNG)
        if inbox(rl, rg):
            o["latitude"], o["longitude"] = rl, rg
            n_decimal += 1
            continue
        # maybe fields are also swapped AND decimal-broken
        rl2, rg2 = shift_into(lng, *LAT), shift_into(lat, *LNG)
        if inbox(rl2, rg2):
            o["latitude"], o["longitude"] = rl2, rg2
            n_decimal += 1
            continue

        # 3. unrecoverable
        o["latitude"] = o["longitude"] = None
        n_null += 1

    remaining = sum(1 for o in olts if o.get("latitude") is not None
                    and o.get("longitude") is not None
                    and not inbox(o["latitude"], o["longitude"]))
    nogeo = sum(1 for o in olts if o.get("latitude") is None or o.get("longitude") is None)

    shutil.copyfile(PON, PON + ".bak14")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)

    print("Coordinate repair (backup .bak14):")
    print(f"  swapped (lat/lng transposed): {n_swap}")
    print(f"  decimal-point recovered:      {n_decimal}")
    print(f"  nulled (unrecoverable):       {n_null}")
    print(f"  still out-of-box (should be 0): {remaining}")
    print(f"  OLTs now without coordinates:   {nogeo}")


if __name__ == "__main__":
    main()
