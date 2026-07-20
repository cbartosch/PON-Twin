"""Dashboard cleanup + operator relabel.

1. Drop the top-row KPI tiles that are Malang-only or A-national/B-Malang mixes
   with no clean national value (each already has a correct operator-specific
   national row). 'OLTs' (13,864 = national A+B) is kept.
2. Relabel operator display names everywhere in pon_data.json string VALUES:
   "Operator A" -> "Telkom", "Operator B" -> "Iconnect". JSON keys and
   operator_code ("A"/"B") are untouched, so app logic keeps working.

Reads/writes pon_data.json (backup .bak12).  Run: python _relabel_operators.py
"""
import json
import os
import shutil

HERE = os.path.dirname(os.path.abspath(__file__))
PON = os.path.join(HERE, "pon_data.json")

DROP_TILES = {
    "Areas", "Live PON ports", "Spare PON ports", "Connected homes",
    "Primary splitters", "ODPs / secondary splitters", "Aerial poles",
}
RENAME = [("Operator A", "Telkom"), ("Operator B", "Iconnect")]


def relabel(x):
    if isinstance(x, str):
        for a, b in RENAME:
            x = x.replace(a, b)
        return x
    if isinstance(x, list):
        return [relabel(v) for v in x]
    if isinstance(x, dict):
        # rename string VALUES only, never keys
        return {k: relabel(v) for k, v in x.items()}
    return x


def main():
    d = json.load(open(PON, encoding="utf-8"))

    before = len(d["dashboard"])
    d["dashboard"] = [r for r in d["dashboard"] if r.get("Metric") not in DROP_TILES]
    # make the Malang-only design metric explicit
    for r in d["dashboard"]:
        if r.get("Metric") == "Max modeled optical path":
            r["Metric"] = "Max modeled optical path (Malang)"
        if r.get("Metric") == "OLTs":
            r["Comment"] = "8,516 Telkom (NET-02) + 5,348 Iconnect (PLN IconPlus)"
    dropped = before - len(d["dashboard"])

    d = relabel(d)

    shutil.copyfile(PON, PON + ".bak12")
    json.dump(d, open(PON, "w", encoding="utf-8"), ensure_ascii=False)
    print(f"dropped {dropped} KPI tiles; dashboard now {len(d['dashboard'])} rows (backup .bak12)")
    print("dashboard metrics now:")
    for r in d["dashboard"]:
        m = r.get("Metric", "")
        if not str(m).startswith(("AMP", "BNR", "BUR", "BTU", "DNO", "DPT", "GD", "GKW",
                                  "KPO", "LW", "NGT", "PGK", "PKS", "SBM", "SBP", "SGS",
                                  "SWJ", "TMP", "TU")):
            print(f"  {m} = {r.get('Value')} {r.get('Unit')}")


if __name__ == "__main__":
    main()
