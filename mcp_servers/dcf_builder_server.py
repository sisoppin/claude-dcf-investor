"""MCP server: DCF model builder.

Exposes three tools:
  - get_model_spec_template()          → returns the empty spec dict
  - validate_model_spec(spec)          → returns list of validation errors
  - build_dcf_model(spec, output_path) → builds the 5-sheet xlsx, returns path

The agent should:
  1. Research → fill the spec
  2. Call validate_model_spec, fix any errors
  3. Call build_dcf_model
  4. Use present_files (or the file_editor MCP) to deliver the .xlsx
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from mcp_servers.dcf.builder import DCFBuilder
from mcp_servers.dcf.spec import get_template, validate_spec

mcp = FastMCP("dcf_builder")

# Default output dir (same as file_editor workspace if env set)
WORKSPACE = os.environ.get("WORKSPACE_PATH", "./workspace")


def _coerce_spec(spec: Any) -> dict | None:
    """Some LLMs serialize nested dicts as JSON strings. Accept both."""
    if isinstance(spec, dict):
        return spec
    if isinstance(spec, str):
        try:
            parsed = json.loads(spec)
            return parsed if isinstance(parsed, dict) else None
        except json.JSONDecodeError:
            return None
    return None


@mcp.tool()
def get_model_spec_template() -> str:
    """Return an empty DCF model spec the agent should fill in.

    Returns the schema as a JSON string with comments on each field
    (in the field name itself / nearby).
    """
    template = get_template()
    return json.dumps(template, indent=2, default=str)


@mcp.tool()
def validate_model_spec(spec: Any) -> str:
    """Validate a DCF model spec. Returns the list of errors, or
    'OK' if the spec is valid. Accepts spec as either a dict or a
    JSON-encoded string (some LLMs serialize nested objects).
    """
    spec_d = _coerce_spec(spec)
    if spec_d is None:
        return ("ERROR: spec must be a JSON object (or a string containing "
                 "valid JSON). Call get_model_spec_template() to see the schema.")
    errors = validate_spec(spec_d)
    if not errors:
        return "OK — spec is valid and ready to build."
    return "Validation errors:\n" + "\n".join(f"  - {e}" for e in errors)


@mcp.tool()
def build_dcf_model(spec: Any, output_filename: str = "dcf_model.xlsx") -> str:
    """Build the complete 5-sheet DCF valuation xlsx.

    Sheets produced:
      1. Cover            — Bear/Base/Bull summary, color legend, observations
      2. Assumptions      — all inputs (blue), WACC build, scenarios, peers
      3. DCF              — 7 sections (revenue → reverse DCF)
      4. Returns_DCF      — teal: IRR matrix, exit = DCF intrinsic
      5. Returns_Multiple — dark red: multiple-based IRR + synthesis A vs B

    Args:
      spec: complete DCF model spec (dict or JSON string — see
            get_model_spec_template). Must validate cleanly.
      output_filename: filename only (no directory); written to WORKSPACE_PATH

    Returns the absolute path to the generated file.
    """
    spec_d = _coerce_spec(spec)
    if spec_d is None:
        return ("ERROR: spec must be a JSON object (or a string containing "
                 "valid JSON). Call get_model_spec_template() to see the schema.")

    # always validate first
    errors = validate_spec(spec_d)
    if errors:
        return ("REFUSING TO BUILD — spec has validation errors:\n" +
                "\n".join(f"  - {e}" for e in errors) +
                "\n\nFix the spec and call build_dcf_model again.")

    # Sandbox the output path inside WORKSPACE
    safe_name = Path(output_filename).name   # strip directory traversal
    if not safe_name or safe_name == ".xlsx":
        safe_name = "dcf_model.xlsx"
    if not safe_name.endswith(".xlsx"):
        safe_name += ".xlsx"
    out_dir = Path(WORKSPACE).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / safe_name

    DCFBuilder(spec_d, str(out_path)).build()
    return f"Built: {out_path}"


@mcp.tool()
def explain_spec_field(field: str) -> str:
    """Explain what a top-level spec field expects.

    field ∈ {company, cmp, shares_diluted_mn, net_cash, actuals, wacc,
             scenarios, projection_years, phase1_end_idx, peers,
             exit_multiple, estimated_flags, key_observations}
    """
    docs = {
        "company": "dict: name, ticker, currency (e.g. 'INR'/'USD'), fy_end (e.g. 'Mar'/'Dec')",
        "cmp": "float: current market price per share, in company currency",
        "shares_diluted_mn": "float: fully diluted shares outstanding, in millions",
        "net_cash": "float: Cash & equivalents − Total debt. Negative = net debt position.",
        "actuals": "dict: at least 2 fiscal years (e.g. 'FY23', 'FY24'). "
                   "Each year has: revenue, ebitda, da, capex, nwc_change, "
                   "tax_rate, interest, avg_debt.",
        "wacc": "dict: rf, erp, beta, kd, tax_rate, wt_equity, wt_debt, "
                "source_notes. Ke and WACC are computed by formulas in xlsx.",
        "scenarios": "dict with bear/base/bull keys. Each: rev_cagr_p1, "
                     "rev_cagr_p2, ebitda_margin_terminal, tgr, tax_rate, "
                     "capex_pct, da_pct, nwc_pct, rationale (string).",
        "projection_years": "list of strings, ≥5 entries, e.g. "
                            "['FY26','FY27',...,'FY35'].",
        "phase1_end_idx": "int: index where Phase 1 CAGR ends and Phase 2 "
                          "begins. e.g. 5 means projection_years[0..4] use "
                          "rev_cagr_p1, [5..end] use rev_cagr_p2.",
        "peers": "list of dicts with: name, ev_ntm_rev, ntm_rev_cagr, "
                 "ntm_ebitda_margin, ev_ntm_ebitda. Provide 4-5 peers.",
        "exit_multiple": "dict: type ('EV/Revenue' or 'EV/EBITDA'), rationale, "
                         "bear, base, bull (multiple values), metric_year "
                         "(which forecast year to apply the multiple on, "
                         "e.g. 'FY30').",
        "estimated_flags": "list of strings flagging any input you couldn't "
                           "source from filings, e.g. ['beta: ESTIMATED — "
                           "basis: 2y weekly regression on Yahoo data'].",
        "key_observations": "list of strings — bullet observations for the "
                            "Cover sheet.",
    }
    return docs.get(field, f"Unknown field: {field}. Valid fields: {list(docs)}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
