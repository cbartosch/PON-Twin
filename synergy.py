"""
Network synergy analysis for the PON digital twin.

Answers "how much synergy for lever X in region Y" by combining:
  * REAL twin volumes (homes passed, OLT counts, FDT/FAT counts, route-km) pulled
    live from the loaded twin data D, and
  * SYNTHETIC estimate tables (synergy_assumptions.json) for the unit economics,
    duplication ratios, certainty scores and any driver the twin does not hold
    (aggregation switches, PE routers, BNG sessions, MSAN, field FTE, ...).

Every monetary answer consumes at least the synthetic unit-economics table, so
each result carries 'derived_from_synthetic': true and lists exactly which
synthetic tables were used, plus whether the underlying VOLUME was twin-grounded.
"""
import json
from pathlib import Path

_HERE = Path(__file__).parent
_LEVERS = None
_ASSUME = None


def _load():
    global _LEVERS, _ASSUME
    if _LEVERS is None:
        with open(_HERE / "synergy_levers.json", encoding="utf-8") as f:
            _LEVERS = json.load(f)
    if _ASSUME is None:
        with open(_HERE / "synergy_assumptions.json", encoding="utf-8") as f:
            _ASSUME = json.load(f)
    return _LEVERS, _ASSUME


def _num(x):
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


# ── region resolution ────────────────────────────────────────────────────────
def _resolve_areas(D, region):
    """Return (area_records, label). region may be:
       None / 'all'     -> every area
       'national'       -> national-footprint scope areas only
       'malang'         -> original Malang deep-detail areas
       'SBU-...'        -> that SBU's child areas
       an area_id       -> that single area
    """
    areas = D.get("areas", [])
    if region in (None, "", "all", "ALL"):
        return [a for a in areas if a.get("tier") != 2], "all footprint"
    r = str(region)
    if r.lower() == "national":
        return [a for a in areas if a.get("scope") == "national-footprint" and a.get("tier") != 2], "national footprint"
    if r.lower() == "malang":
        return [a for a in areas if a.get("scope") != "national-footprint" and a.get("tier") != 2], "Malang"
    # SBU rollup?
    sbu = next((a for a in areas if a.get("area_id") == r and a.get("tier") == 2), None)
    if sbu:
        kids = set(sbu.get("child_area_ids", []))
        return [a for a in areas if a.get("area_id") in kids], sbu.get("area_name", r)
    # single leaf area
    one = next((a for a in areas if a.get("area_id") == r), None)
    if one:
        return [one], one.get("area_name", r)
    return [], f"(unknown region {r})"


def _route_km_twin(D, area_ids):
    km = 0.0
    for c in D.get("cables", []):
        if c.get("area_id") in area_ids:
            km += _num(c.get("segment_length_m")) / 1000.0
    return km


def twin_drivers(D, region=None):
    """Extract volume drivers for a region, tagging each as twin- or synthetic-sourced."""
    _, ASSUME = _load()
    areas, label = _resolve_areas(D, region)
    area_ids = {a.get("area_id") for a in areas}

    homes = 0.0
    fdt = fat = 0.0
    for a in areas:
        hb = a.get("connected_homes_operator_B")
        homes += _num(hb if hb is not None else a.get("connected_homes_total"))
        fdt += _num(a.get("primary_splitter_count"))
        fat += _num(a.get("fat_count"))

    olts = sum(1 for o in D.get("olts", [])
               if o.get("area_id") in area_ids and o.get("operator_code") == "B")
    # distinct SBU parents + leaf area count for synthetic estimators
    sbu_count = len({a.get("tier2_parent_code") for a in areas if a.get("tier2_parent_code")}) or 1
    area_count = len(areas) or 1

    route_km = _route_km_twin(D, area_ids)
    route_km_source = "twin"
    if route_km <= 0:  # no cable geometry for this region -> synthetic proxy
        route_km = fat * 0.35
        route_km_source = "synthetic"

    est = ASSUME["table_3_synthetic_volumes"]["estimators"]
    drivers = {
        "homes_passed":       {"value": round(homes),          "source": "twin"},
        "olts":               {"value": olts,                  "source": "twin"},
        "fdt_count":          {"value": round(fdt),            "source": "twin"},
        "fat_count":          {"value": round(fat),            "source": "twin"},
        "route_km":           {"value": round(route_km, 1),    "source": route_km_source},
        "broadband_subs":     {"value": round(homes),          "source": "twin_proxy",
                               "note": "connected homes used as subscriber-session proxy"},
        # synthetic-volume drivers (formula on twin counts, synthetic coefficients)
        "agg_switches":       {"value": round(olts / 8),       "source": "synthetic", "formula": est["agg_switches"]["formula"]},
        "transport_circuits": {"value": round(olts * 1.5),     "source": "synthetic", "formula": est["transport_circuits"]["formula"]},
        "pe_routers":         {"value": round(sbu_count * 4),  "source": "synthetic", "formula": est["pe_routers"]["formula"]},
        "msan_sites":         {"value": round(area_count * 0.4),"source": "synthetic", "formula": est["msan_sites"]["formula"]},
        "field_fte":          {"value": round(olts * 0.5),     "source": "synthetic", "formula": est["field_fte"]["formula"]},
        "fault_events":       {"value": round(olts * 3),       "source": "synthetic", "formula": est["fault_events"]["formula"]},
        "addressable_spend":  {"value": round(olts * 0.9, 1),  "source": "synthetic", "formula": est["addressable_spend"]["formula"],
                               "unit": "IDR bn/yr"},
        "none":               {"value": 1,                     "source": "synthetic", "note": "fixed programme-level pool"},
    }
    return {
        "region": region or "all",
        "region_label": label,
        "area_count": area_count,
        "sbu_count": sbu_count,
        "drivers": drivers,
    }


def _certainty(scores, weights):
    return round(sum(_num(scores.get(k)) * _num(w) for k, w in weights.items()), 4)


def analyze_lever(D, lever_id, region=None, overrides=None):
    LEVERS, ASSUME = _load()
    lev = next((l for l in LEVERS["levers"] if l["lever_id"] == lever_id), None)
    if not lev:
        return {"error": f"Unknown lever_id '{lever_id}'",
                "valid_lever_ids": [l["lever_id"] for l in LEVERS["levers"]]}

    ue = ASSUME["table_2_unit_economics"]["levers"][lever_id]
    illus = ASSUME["table_4_illustrative_model"]["levers"][lever_id]
    weights = ASSUME["table_1_certainty_weights"]["weights"]
    overrides = overrides or {}

    dr = twin_drivers(D, region)
    driver_name = lev["twin_driver"] if lev["twin_driver"] != "none" else "none"
    dinfo = dr["drivers"].get(driver_name, {"value": 0, "source": "synthetic"})
    volume = dinfo["value"]
    volume_source = dinfo["source"]

    applicability = float(overrides.get("applicability_ratio", ue["applicability_ratio"]))
    unit_value = float(overrides.get("unit_value_idr_bn", ue["unit_value_idr_bn"]))
    cta_ratio = float(overrides.get("cost_to_achieve_ratio", ue["cost_to_achieve_ratio"]))

    gross = volume * applicability * unit_value
    cta = gross * cta_ratio
    net = gross - cta
    certainty = _certainty(illus["scores"], weights)
    bankable = net * certainty
    risk = net - bankable

    twin_grounded = volume_source in ("twin", "twin_proxy", "twin_partial")
    synthetic_tables = ["table_1_certainty_weights", "table_2_unit_economics", "table_4_illustrative_model"]
    if not twin_grounded or volume_source == "synthetic":
        synthetic_tables.append("table_3_synthetic_volumes")

    return {
        "lever_id": lever_id,
        "bucket": lev["bucket"],
        "lever": lev["lever"],
        "region": dr["region"],
        "region_label": dr["region_label"],
        "calculation_logic": lev["calculation_logic"],
        "twin_evidence": {
            "driver": driver_name,
            "driver_volume": volume,
            "driver_source": volume_source,
            "twin_grounded_volume": twin_grounded,
        },
        "synthetic_inputs": {
            "applicability_ratio": applicability,
            "unit_value_idr_bn": unit_value,
            "unit_desc": ue["unit_desc"],
            "cost_to_achieve_ratio": cta_ratio,
            "confidence": ue["confidence"],
            "rationale": ue["rationale"],
        },
        "estimate_idr_bn": {
            "gross_synergy": round(gross, 2),
            "cost_to_achieve": round(cta, 2),
            "net_synergy": round(net, 2),
            "certainty_score": certainty,
            "bankable_synergy": round(bankable, 2),
            "risk_exposure": round(risk, 2),
        },
        "workbook_illustrative_idr_bn": {
            "gross_synergy": illus["gross_idr_bn"],
            "cost_to_achieve": illus["cost_to_achieve_idr_bn"],
            "status": illus["status"],
        },
        "derived_from_synthetic": True,
        "synthetic_tables_used": synthetic_tables,
        "flag": ("ESTIMATE - monetary figures use SYNTHETIC unit economics"
                 + ("" if twin_grounded else "; volume driver is ALSO synthetic (no twin data)")),
    }


def summary(D, region=None):
    LEVERS, _ = _load()
    rows = [analyze_lever(D, l["lever_id"], region) for l in LEVERS["levers"]]
    tot = {k: 0.0 for k in ("gross_synergy", "cost_to_achieve", "net_synergy",
                            "bankable_synergy", "risk_exposure")}
    for r in rows:
        for k in tot:
            tot[k] += r["estimate_idr_bn"][k]
    dr = twin_drivers(D, region)
    any_synth_vol = any(not r["twin_evidence"]["twin_grounded_volume"] for r in rows)
    return {
        "region": dr["region"],
        "region_label": dr["region_label"],
        "currency": "IDR bn",
        "twin_volume_snapshot": {
            "homes_passed": dr["drivers"]["homes_passed"]["value"],
            "iconnet_olts": dr["drivers"]["olts"]["value"],
            "primary_splitters_fdt": dr["drivers"]["fdt_count"]["value"],
            "fat_serving_areas": dr["drivers"]["fat_count"]["value"],
        },
        "portfolio_totals_idr_bn": {k: round(v, 1) for k, v in tot.items()},
        "levers": [
            {
                "lever_id": r["lever_id"], "bucket": r["bucket"], "lever": r["lever"],
                "driver": r["twin_evidence"]["driver"],
                "driver_volume": r["twin_evidence"]["driver_volume"],
                "twin_grounded_volume": r["twin_evidence"]["twin_grounded_volume"],
                "gross": r["estimate_idr_bn"]["gross_synergy"],
                "net": r["estimate_idr_bn"]["net_synergy"],
                "certainty": r["estimate_idr_bn"]["certainty_score"],
                "bankable": r["estimate_idr_bn"]["bankable_synergy"],
                "risk": r["estimate_idr_bn"]["risk_exposure"],
            } for r in rows
        ],
        "derived_from_synthetic": True,
        "flag": ("All monetary figures are ESTIMATES using SYNTHETIC unit-economics tables"
                 + ("; some lever volumes are also synthetic (no twin data)" if any_synth_vol else "")
                 + ". Replace with audited data before decisions."),
    }


def catalogue():
    LEVERS, ASSUME = _load()
    return {
        "meta": LEVERS["meta"],
        "certainty_weights": ASSUME["table_1_certainty_weights"]["weights"],
        "levers": [
            {k: l[k] for k in ("lever_id", "bucket", "lever", "relevant_asset",
                               "opportunity", "calculation_logic", "primary_data_required",
                               "twin_driver", "timing", "owner", "base_treatment", "notes")}
            for l in LEVERS["levers"]
        ],
    }
