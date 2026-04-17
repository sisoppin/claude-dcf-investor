"""Model spec schema and validation.

The DCF builder consumes a single nested dict; this module documents and
validates that contract.

CONVENTIONS THE AGENT MUST FOLLOW:

  • Three different tax_rate fields exist — do not confuse them:
    - wacc.tax_rate            : the rate used to compute Kd_AT in WACC.
                                  Use the marginal rate (statutory) or the
                                  rate the company expects long-term.
    - actuals[FY].tax_rate     : effective tax rate for that historical year
                                  (= tax provision / pretax income).
    - scenarios.X.tax_rate     : projected steady-state effective rate for
                                  that scenario. Often == wacc.tax_rate.

  • Sign conventions for ALL line items in actuals[FY] and projections:
    - revenue, ebitda, da, capex   →  POSITIVE numbers
    - nwc_change                    →  POSITIVE means working-capital
                                       INVESTMENT (use of cash). The builder
                                       will subtract this in the FCFF bridge.
                                       If you read "Change in WC = −1,000"
                                       from a cashflow statement, pass
                                       nwc_change = +1,000.
    - net_cash                      →  Cash − Total debt. NEGATIVE means
                                       net debt position.

  • All percentage fields use DECIMAL form (0.10 = 10%, not 10).

  • Currency must be consistent across all fields in a single spec.
"""
from __future__ import annotations

from typing import Any


REQUIRED_TOP = ["company", "cmp", "shares_diluted_mn", "net_cash",
                "actuals", "wacc", "scenarios", "projection_years",
                "phase1_end_idx", "peers", "exit_multiple"]

REQUIRED_COMPANY = ["name", "ticker", "currency", "fy_end"]

REQUIRED_WACC = ["rf", "erp", "beta", "kd", "tax_rate",
                 "wt_equity", "wt_debt"]

REQUIRED_SCENARIO = ["rev_cagr_p1", "rev_cagr_p2", "ebitda_margin_terminal",
                     "tgr", "tax_rate", "capex_pct", "da_pct", "nwc_pct",
                     "rationale"]

REQUIRED_ACTUAL = ["revenue", "ebitda", "da", "capex", "nwc_change", "tax_rate"]

REQUIRED_PEER = ["name", "ev_ntm_rev", "ntm_rev_cagr", "ntm_ebitda_margin",
                 "ev_ntm_ebitda"]

REQUIRED_EXIT = ["type", "rationale", "bear", "base", "bull", "metric_year"]


def validate_spec(spec: dict[str, Any]) -> list[str]:
    """Return a list of validation errors (empty == valid)."""
    errors: list[str] = []

    for key in REQUIRED_TOP:
        if key not in spec:
            errors.append(f"missing top-level key: {key}")

    if errors:
        return errors  # don't dig deeper if top-level is broken

    for key in REQUIRED_COMPANY:
        if key not in spec["company"]:
            errors.append(f"company missing: {key}")

    for key in REQUIRED_WACC:
        if key not in spec["wacc"]:
            errors.append(f"wacc missing: {key}")

    if not spec["actuals"] or len(spec["actuals"]) < 2:
        errors.append("actuals must include at least 2 fiscal years")
    else:
        for year, vals in spec["actuals"].items():
            for k in REQUIRED_ACTUAL:
                if k not in vals:
                    errors.append(f"actuals[{year}] missing: {k}")

    for sc in ("bear", "base", "bull"):
        if sc not in spec["scenarios"]:
            errors.append(f"scenarios missing: {sc}")
            continue
        for k in REQUIRED_SCENARIO:
            if k not in spec["scenarios"][sc]:
                errors.append(f"scenarios.{sc} missing: {k}")

    if not spec["projection_years"] or len(spec["projection_years"]) < 5:
        errors.append("projection_years should have at least 5 years")

    p1 = spec.get("phase1_end_idx")
    if not isinstance(p1, int) or p1 < 1 or p1 >= len(spec.get("projection_years", [])):
        errors.append("phase1_end_idx must be a valid index within projection_years")

    if not spec.get("peers"):
        errors.append("peers is empty (provide 4-5)")
    else:
        for i, p in enumerate(spec["peers"]):
            for k in REQUIRED_PEER:
                if k not in p:
                    errors.append(f"peers[{i}] missing: {k}")

    for k in REQUIRED_EXIT:
        if k not in spec["exit_multiple"]:
            errors.append(f"exit_multiple missing: {k}")

    if spec["exit_multiple"].get("type") not in ("EV/Revenue", "EV/EBITDA"):
        errors.append("exit_multiple.type must be 'EV/Revenue' or 'EV/EBITDA'")

    wacc = spec.get("wacc", {})
    if all(k in wacc for k in ("rf", "beta", "erp")):
        ke_approx = wacc["rf"] + wacc["beta"] * wacc["erp"]
        for sc in ("bear", "base", "bull"):
            if sc not in spec.get("scenarios", {}):
                continue
            tgr = spec["scenarios"][sc].get("tgr", 0)
            if tgr >= ke_approx:
                errors.append(
                    f"scenarios.{sc}.tgr ({tgr:.2%}) >= implied Ke ({ke_approx:.2%})"
                    " — invalid GGM terminal value"
                )

    return errors


def get_template() -> dict[str, Any]:
    """Return an empty template the agent can fill in."""
    return {
        "company": {
            "name": "",
            "ticker": "",
            "currency": "INR",   # or USD
            "fy_end": "Mar"      # or "Dec"
        },
        "cmp": 0.0,
        "shares_diluted_mn": 0.0,
        "net_cash": 0.0,         # cash & equivalents − total debt; can be negative
        "actuals": {
            # at least 2 entries, e.g. "FY23", "FY24"
            "FY23": {
                "revenue": 0, "ebitda": 0, "da": 0, "capex": 0,
                "nwc_change": 0, "tax_rate": 0.25,
                "interest": 0, "avg_debt": 0  # used to compute Kd
            },
            "FY24": {
                "revenue": 0, "ebitda": 0, "da": 0, "capex": 0,
                "nwc_change": 0, "tax_rate": 0.25,
                "interest": 0, "avg_debt": 0
            }
        },
        "wacc": {
            "rf": 0.07,           # 10-yr govt bond yield
            "erp": 0.075,         # equity risk premium (Damodaran)
            "beta": 1.0,
            "kd": 0.085,          # pre-tax cost of debt
            "tax_rate": 0.252,
            "wt_equity": 0.85,
            "wt_debt": 0.15,
            "source_notes": ""
        },
        "scenarios": {
            "bear": {
                "rev_cagr_p1": 0.05, "rev_cagr_p2": 0.03,
                "ebitda_margin_terminal": 0.15,
                "tgr": 0.03,
                "tax_rate": 0.252, "capex_pct": 0.04, "da_pct": 0.03,
                "nwc_pct": 0.02,
                "rationale": ""
            },
            "base": {
                "rev_cagr_p1": 0.10, "rev_cagr_p2": 0.06,
                "ebitda_margin_terminal": 0.20,
                "tgr": 0.04,
                "tax_rate": 0.252, "capex_pct": 0.04, "da_pct": 0.03,
                "nwc_pct": 0.02,
                "rationale": ""
            },
            "bull": {
                "rev_cagr_p1": 0.15, "rev_cagr_p2": 0.09,
                "ebitda_margin_terminal": 0.25,
                "tgr": 0.05,
                "tax_rate": 0.252, "capex_pct": 0.04, "da_pct": 0.03,
                "nwc_pct": 0.02,
                "rationale": ""
            }
        },
        # 10-year explicit forecast typical
        "projection_years": ["FY26", "FY27", "FY28", "FY29", "FY30",
                             "FY31", "FY32", "FY33", "FY34", "FY35"],
        "phase1_end_idx": 5,    # first 5 use Phase 1 CAGR, rest Phase 2
        "peers": [
            {"name": "", "ev_ntm_rev": 0, "ntm_rev_cagr": 0,
             "ntm_ebitda_margin": 0, "ev_ntm_ebitda": 0}
        ],
        "exit_multiple": {
            "type": "EV/EBITDA",          # or "EV/Revenue"
            "rationale": "",
            "bear": 0, "base": 0, "bull": 0,
            "metric_year": "FY30"        # which forecast year to apply on
        },
        "estimated_flags": [],            # ["beta: ESTIMATED — basis: ..."]
        "key_observations": []            # ["bullet 1", "bullet 2", ...]
    }
