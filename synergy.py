"""
Network synergy analysis for the PON digital twin.

Answers "how much synergy for lever X in region Y" by combining:
  * REAL twin volumes (homes passed, OLT counts, FDT/FAT counts, route-km) pulled
    live from the loaded twin data D,
  * REAL benchmark unit economics from the Indonesian OLT & fiber-works cost sheet
    (costs.json) for the levers that sheet genuinely covers, and
  * SYNTHETIC estimate tables (synergy_assumptions.json) for the unit economics,
    duplication ratios, certainty scores and any driver the twin does not hold
    (aggregation switches, PE routers, BNG sessions, MSAN, field FTE, ...).

Cost grounding: because costs.json is specifically an OLT + fiber-works benchmark,
it can ground only the OLT-side levers -- 'olt_retire_redundant' (real annual O&M
avoided per retired OLT as the value driver + real per-OLT decommission as the
cost-to-achieve) and 'olt_reuse_xgspon' (real per-OLT relocation as the
cost-to-achieve). The aggregation / transport / PE / BNG / MSAN / NOC / procurement
levers have no analogue in this sheet and remain synthetic. Each result reports a
per-input source map (real_cost_sheet / synthetic / override) and a 'cost_basis'
of real_benchmark / mixed / synthetic so real and estimated money never blur.
"""
import json
from pathlib import Path

_HERE = Path(__file__).parent
_LEVERS = None
_ASSUME = None
_COSTS = None
_IDR_BN = 1e9  # costs.json is in whole IDR; synergy model works in IDR billions


def _load():
    global _LEVERS, _ASSUME, _COSTS
    if _LEVERS is None:
        with open(_HERE / "synergy_levers.json", encoding="utf-8") as f:
            _LEVERS = json.load(f)
    if _ASSUME is None:
        with open(_HERE / "synergy_assumptions.json", encoding="utf-8") as f:
            _ASSUME = json.load(f)
    if _COSTS is None:
        p = _HERE / "costs.json"
        _COSTS = json.load(open(p, encoding="utf-8")) if p.exists() else {}
    return _LEVERS, _ASSUME


def _cost_grounded(lever_id):
    """Real per-unit economics (IDR bn) from the benchmark cost sheet (costs.json)
    for the levers it genuinely covers. Returns None when the lever has no real-cost
    analogue in an OLT/fiber-works sheet, so it stays synthetic.

    - unit_value_idr_bn ...... real value driver per unit (only where the sheet holds it)
    - cta_idr_bn_per_unit .... real one-time cost-to-achieve per unit
    """
    der = (_COSTS or {}).get("derived", {})
    if not der:
        return None
    if lever_id == "olt_retire_redundant":
        return {
            "unit_value_idr_bn": der["annual_om_per_olt_full_idr"] / _IDR_BN,
            "unit_value_desc": "annual O&M run-rate avoided per retired OLT (full O&M basis, real cost sheet)",
            "value_kind": "annual_run_rate",
            "cta_idr_bn_per_unit": der["olt_decommission_per_olt_idr"] / _IDR_BN,
            "grounded": "full",  # both value driver and cost-to-achieve are real
            "source_items": ["annual_om_per_olt_full_idr", "olt_decommission_per_olt_idr"],
        }
    if lever_id == "olt_reuse_xgspon":
        return {
            # avoided new-purchase value is NOT in a works cost sheet -> keep synthetic unit_value
            "cta_idr_bn_per_unit": der["olt_relocate_per_olt_idr"] / _IDR_BN,
            "value_kind": "one_time",
            "grounded": "cost_to_achieve_only",
            "source_items": ["olt_relocate_per_olt_idr"],
        }
    return None


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

    ground = _cost_grounded(lever_id)

    # Applicability is always a planning estimate (share of the driver actually addressable).
    applicability = float(overrides.get("applicability_ratio", ue["applicability_ratio"]))
    appl_source = "override" if "applicability_ratio" in overrides else "synthetic"
    effective_units = volume * applicability

    # --- value driver (unit_value) : real cost sheet > override > synthetic table ---
    if "unit_value_idr_bn" in overrides:
        unit_value, unit_value_source, unit_desc = float(overrides["unit_value_idr_bn"]), "override", ue["unit_desc"]
        value_kind = ue.get("value_kind", "lump")
    elif ground and "unit_value_idr_bn" in ground:
        unit_value, unit_value_source, unit_desc = ground["unit_value_idr_bn"], "real_cost_sheet", ground["unit_value_desc"]
        value_kind = ground["value_kind"]
    else:
        unit_value, unit_value_source, unit_desc = float(ue["unit_value_idr_bn"]), "synthetic", ue["unit_desc"]
        value_kind = ue.get("value_kind", "lump")

    gross = effective_units * unit_value

    # --- cost-to-achieve : override ratio > real per-unit > synthetic ratio ---
    if "cost_to_achieve_ratio" in overrides:
        cta_ratio = float(overrides["cost_to_achieve_ratio"])
        cta, cta_source = gross * cta_ratio, "override"
        cta_basis = {"ratio_of_gross": cta_ratio}
    elif ground and "cta_idr_bn_per_unit" in ground:
        cta_per_unit = ground["cta_idr_bn_per_unit"]
        cta, cta_source = effective_units * cta_per_unit, "real_cost_sheet"
        cta_basis = {"per_unit_idr_bn": round(cta_per_unit, 6), "addressable_units": round(effective_units, 2)}
    else:
        cta_ratio = float(ue["cost_to_achieve_ratio"])
        cta, cta_source = gross * cta_ratio, "synthetic"
        cta_basis = {"ratio_of_gross": cta_ratio}

    net = gross - cta
    certainty = _certainty(illus["scores"], weights)
    bankable = net * certainty
    risk = net - bankable

    twin_grounded = volume_source in ("twin", "twin_proxy", "twin_partial")

    # cost_basis: are the unit economics (value + CTA) real, mixed, or synthetic?
    real_flags = [unit_value_source == "real_cost_sheet", cta_source == "real_cost_sheet"]
    if all(real_flags):
        cost_basis = "real_benchmark"
    elif any(real_flags):
        cost_basis = "mixed"
    else:
        cost_basis = "synthetic"
    # applicability is always an estimate, so any answer still carries a synthetic input
    any_synthetic = (unit_value_source == "synthetic" or cta_source == "synthetic"
                     or appl_source == "synthetic" or not twin_grounded)

    synthetic_tables = ["table_1_certainty_weights", "table_4_illustrative_model"]
    if unit_value_source == "synthetic" or cta_source == "synthetic":
        synthetic_tables.insert(1, "table_2_unit_economics")
    if not twin_grounded or volume_source == "synthetic":
        synthetic_tables.append("table_3_synthetic_volumes")

    cost_note = {
        "real_benchmark": "Unit economics grounded in the real Indonesian OLT/fiber-works cost sheet (costs.json)",
        "mixed": "Cost-to-achieve grounded in the real cost sheet; value driver is a SYNTHETIC estimate",
        "synthetic": "Unit economics are SYNTHETIC estimates (no analogue in the OLT/fiber-works cost sheet)",
    }[cost_basis]
    flag = (cost_note
            + ("; applicability ratio is a planning estimate" if appl_source == "synthetic" else "")
            + ("" if twin_grounded else "; volume driver is ALSO synthetic (no twin data)"))

    return {
        "lever_id": lever_id,
        "bucket": lev["bucket"],
        "lever": lev["lever"],
        "region": dr["region"],
        "region_label": dr["region_label"],
        "calculation_logic": lev["calculation_logic"],
        "cost_basis": cost_basis,
        "twin_evidence": {
            "driver": driver_name,
            "driver_volume": volume,
            "driver_source": volume_source,
            "twin_grounded_volume": twin_grounded,
            "addressable_units": round(effective_units, 2),
        },
        "inputs": {
            "applicability_ratio": applicability,
            "unit_value_idr_bn": round(unit_value, 6),
            "unit_desc": unit_desc,
            "value_kind": value_kind,
            "cost_to_achieve_basis": cta_basis,
            "confidence": ue["confidence"],
            "rationale": ue["rationale"],
        },
        "input_sources": {
            "applicability_ratio": appl_source,
            "unit_value": unit_value_source,
            "cost_to_achieve": cta_source,
            "volume": volume_source,
        },
        "cost_sheet_items_used": ground["source_items"] if ground else [],
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
        "derived_from_synthetic": any_synthetic,
        "synthetic_tables_used": synthetic_tables,
        "flag": flag,
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
    cost_basis_counts = {}
    for r in rows:
        cost_basis_counts[r["cost_basis"]] = cost_basis_counts.get(r["cost_basis"], 0) + 1
    grounded_ids = [r["lever_id"] for r in rows if r["cost_basis"] in ("real_benchmark", "mixed")]
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
        "cost_grounding": {
            "cost_basis_counts": cost_basis_counts,
            "cost_grounded_levers": grounded_ids,
            "cost_source": (_COSTS or {}).get("meta", {}).get("title", "n/a"),
            "note": ("Real cost sheet is an OLT & fiber-works benchmark, so it grounds only the "
                     "OLT-side levers; other levers keep synthetic unit economics."),
        },
        "levers": [
            {
                "lever_id": r["lever_id"], "bucket": r["bucket"], "lever": r["lever"],
                "driver": r["twin_evidence"]["driver"],
                "driver_volume": r["twin_evidence"]["driver_volume"],
                "twin_grounded_volume": r["twin_evidence"]["twin_grounded_volume"],
                "cost_basis": r["cost_basis"],
                "gross": r["estimate_idr_bn"]["gross_synergy"],
                "net": r["estimate_idr_bn"]["net_synergy"],
                "certainty": r["estimate_idr_bn"]["certainty_score"],
                "bankable": r["estimate_idr_bn"]["bankable_synergy"],
                "risk": r["estimate_idr_bn"]["risk_exposure"],
            } for r in rows
        ],
        "derived_from_synthetic": True,
        "flag": (f"{len(grounded_ids)} of {len(rows)} levers grounded in the real cost sheet "
                 f"({', '.join(grounded_ids) or 'none'}); the rest use SYNTHETIC unit economics"
                 + ("; some lever volumes are also synthetic (no twin data)" if any_synth_vol else "")
                 + ". Applicability ratios remain planning estimates. Replace with audited data before decisions."),
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
