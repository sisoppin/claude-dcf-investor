"""MCP server: financial research tools.

Provides the agent with the data it needs to fill the DCF model spec:
  - get_quote(ticker)              → CMP, shares, beta, market cap
  - get_financials(ticker)         → income/balance/cashflow last 4y
  - get_company_profile(ticker)    → sector, industry, summary
  - get_peer_multiples(tickers)    → EV/Rev, EV/EBITDA, margins
  - get_treasury_yield(country)    → 10y govt bond yield (Rf)
  - get_damodaran_erp(country)     → equity risk premium (ERP)
  - search_financials_web(query)   → fallback web search returning text

Uses yfinance for global tickers (Indian use .NS suffix, e.g. RELIANCE.NS;
US use bare ticker, e.g. AAPL). Falls back to DuckDuckGo + URL fetch when
yfinance lacks data.

NOTE: yfinance requires network access at runtime. If no network, the
search_financials_web tool can still pull from any source the user has
proxied through.
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("finance")


# =====================================================================
# Lazy imports — yfinance can be slow to load
# =====================================================================
def _yf():
    import yfinance as yf  # type: ignore
    return yf


def _normalize_ticker(ticker: str) -> str:
    """Apply common suffix conventions:
       - Indian ticker without dot → assume NSE (.NS)
       - US ticker → bare
    """
    t = ticker.strip().upper()
    # if user already gave a suffix, keep it
    if "." in t:
        return t
    # Heuristic: if ticker is all letters and length ≥ 1, treat as US bare
    return t


# =====================================================================
# Quote / profile
# =====================================================================
@mcp.tool()
def get_quote(ticker: str) -> str:
    """Live or last-close quote, plus shares outstanding, beta, market cap.

    For Indian stocks use the .NS suffix (e.g. RELIANCE.NS, TCS.NS).
    For US stocks use the bare ticker (e.g. AAPL, MSFT).
    """
    try:
        yf = _yf()
        t = yf.Ticker(_normalize_ticker(ticker))
        info = t.info or {}
        result = {
            "ticker": ticker,
            "currency": info.get("currency"),
            "current_price": info.get("currentPrice") or info.get("regularMarketPrice"),
            "previous_close": info.get("previousClose"),
            "market_cap": info.get("marketCap"),
            "shares_outstanding": info.get("sharesOutstanding"),
            "implied_shares_outstanding": info.get("impliedSharesOutstanding"),
            "float_shares": info.get("floatShares"),
            "beta": info.get("beta"),
            "trailing_pe": info.get("trailingPE"),
            "forward_pe": info.get("forwardPE"),
            "trailing_eps": info.get("trailingEps"),
            "book_value": info.get("bookValue"),
            "long_name": info.get("longName"),
            "exchange": info.get("exchange"),
        }
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def get_company_profile(ticker: str) -> str:
    """Sector, industry, business summary, country."""
    try:
        yf = _yf()
        info = yf.Ticker(_normalize_ticker(ticker)).info or {}
        return json.dumps({
            "name": info.get("longName"),
            "sector": info.get("sector"),
            "industry": info.get("industry"),
            "country": info.get("country"),
            "website": info.get("website"),
            "summary": info.get("longBusinessSummary"),
            "employees": info.get("fullTimeEmployees"),
        }, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# =====================================================================
# Financial statements
# =====================================================================
def _df_to_dict(df) -> dict[str, Any]:
    """Convert a yfinance DataFrame (line items × dates) to year→{item:value}."""
    if df is None or df.empty:
        return {}
    out: dict[str, Any] = {}
    for col in df.columns:
        year_key = str(col)[:10]  # ISO date
        out[year_key] = {}
        for idx in df.index:
            val = df.loc[idx, col]
            try:
                if val is None or (hasattr(val, "isna") and bool(val.isna())):
                    out[year_key][str(idx)] = None
                else:
                    out[year_key][str(idx)] = float(val)
            except Exception:
                out[year_key][str(idx)] = None
    return out


@mcp.tool()
def get_financials(ticker: str, statement: str = "all") -> str:
    """Income statement, balance sheet, and cash flow (last 4 fiscal years).

    statement ∈ {"income", "balance", "cashflow", "all"}
    """
    try:
        yf = _yf()
        t = yf.Ticker(_normalize_ticker(ticker))
        result: dict[str, Any] = {"ticker": ticker}
        if statement in ("income", "all"):
            result["income_statement"] = _df_to_dict(t.financials)
        if statement in ("balance", "all"):
            result["balance_sheet"] = _df_to_dict(t.balance_sheet)
        if statement in ("cashflow", "all"):
            result["cash_flow"] = _df_to_dict(t.cashflow)
        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def derive_actuals(ticker: str) -> str:
    """Convenience: extract the exact line items the DCF spec needs from
    the last 2 fiscal years (revenue, ebitda, da, capex, nwc_change,
    tax_rate, interest, avg_debt). Best-effort — fields may be missing.
    """
    try:
        yf = _yf()
        t = yf.Ticker(_normalize_ticker(ticker))
        inc = t.financials
        bs = t.balance_sheet
        cf = t.cashflow

        def col_year(c) -> str:
            return str(c)[:10]

        def get(df, *names) -> dict[str, float]:
            """Return {year: value} for first matching label."""
            out = {}
            if df is None or df.empty:
                return out
            for name in names:
                if name in df.index:
                    for col in df.columns:
                        v = df.loc[name, col]
                        try:
                            out[col_year(col)] = float(v)
                        except Exception:
                            pass
                    if out:
                        return out
            return out

        revenue = get(inc, "Total Revenue", "Operating Revenue", "Revenue")
        operating_income = get(inc, "Operating Income", "EBIT")
        da = get(cf, "Depreciation And Amortization",
                  "Depreciation Amortization Depletion",
                  "Depreciation")
        net_income = get(inc, "Net Income", "Net Income Common Stockholders")
        tax_provision = get(inc, "Tax Provision", "Income Tax Expense")
        pretax = get(inc, "Pretax Income", "Income Before Tax")
        interest = get(inc, "Interest Expense")
        capex = get(cf, "Capital Expenditure")
        ch_wc = get(cf, "Change In Working Capital", "Changes In Working Capital")

        cash = get(bs, "Cash And Cash Equivalents",
                    "Cash Cash Equivalents And Short Term Investments",
                    "Cash And Short Term Investments")
        total_debt = get(bs, "Total Debt", "Long Term Debt And Capital Lease Obligation")

        # Derive EBITDA = EBIT + D&A
        years = sorted(set(revenue) | set(operating_income), reverse=True)[:4]
        actuals: dict[str, dict[str, Any]] = {}
        for y in years:
            ebit = operating_income.get(y)
            da_y = da.get(y)
            ebitda = (ebit + da_y) if (ebit is not None and da_y is not None) else None
            etr = None
            if pretax.get(y) and tax_provision.get(y):
                try:
                    etr = tax_provision[y] / pretax[y]
                except ZeroDivisionError:
                    etr = None
            actuals[y] = {
                "revenue": revenue.get(y),
                "ebit": ebit,
                "da": da_y,
                "ebitda": ebitda,
                "capex": abs(capex.get(y, 0)) if capex.get(y) is not None else None,
                "nwc_change": -ch_wc.get(y) if ch_wc.get(y) is not None else None,
                "tax_rate": etr,
                "interest": abs(interest.get(y, 0)) if interest.get(y) is not None else None,
                "cash": cash.get(y),
                "total_debt": total_debt.get(y),
                "net_cash": ((cash.get(y) or 0) - (total_debt.get(y) or 0))
                            if (cash.get(y) is not None or total_debt.get(y) is not None)
                            else None,
            }
        return json.dumps({
            "ticker": ticker,
            "actuals": actuals,
            "notes": "All values in reporting currency. NULL = not found in yfinance; "
                     "fallback to filings or screener.in/SEC EDGAR. "
                     "EBITDA derived as EBIT + D&A. tax_rate is effective rate.",
        }, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# =====================================================================
# Beta / peer multiples
# =====================================================================
@mcp.tool()
def compute_beta(ticker: str, benchmark: str = "auto",
                  period: str = "2y", interval: str = "1wk") -> str:
    """Compute beta = Cov(R_stock, R_mkt) / Var(R_mkt).

    benchmark='auto' picks ^NSEI for .NS tickers, ^GSPC for US (SPX),
    ^FTSE for UK, etc. Override with any yahoo index symbol.
    """
    try:
        yf = _yf()
        t = _normalize_ticker(ticker)
        if benchmark == "auto":
            if t.endswith(".NS") or t.endswith(".BO"):
                benchmark = "^NSEI"
            elif t.endswith(".L"):
                benchmark = "^FTSE"
            elif t.endswith(".HK"):
                benchmark = "^HSI"
            else:
                benchmark = "^GSPC"
        data = yf.download([t, benchmark], period=period, interval=interval,
                            progress=False, auto_adjust=True)
        if data.empty:
            return f"ERROR: no price data for {t} or {benchmark}"
        prices = data["Close"]
        rets = prices.pct_change().dropna()
        if len(rets) < 10:
            return f"ERROR: insufficient observations ({len(rets)})"
        cov = rets[t].cov(rets[benchmark])
        var = rets[benchmark].var()
        beta = cov / var if var else None
        return json.dumps({
            "ticker": ticker, "benchmark": benchmark,
            "period": period, "interval": interval,
            "n_obs": len(rets),
            "beta": float(beta) if beta is not None else None,
        }, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def get_peer_multiples(tickers: list[str]) -> str:
    """For each ticker return market cap, EV, revenue, EBITDA, and the
    multiples EV/Revenue and EV/EBITDA. NTM data is not free-tier; this
    returns trailing.
    """
    try:
        yf = _yf()
        out = []
        for tk in tickers:
            try:
                info = yf.Ticker(_normalize_ticker(tk)).info or {}
                ev = info.get("enterpriseValue")
                rev = info.get("totalRevenue")
                ebitda = info.get("ebitda")
                row = {
                    "name": info.get("longName") or tk,
                    "ticker": tk,
                    "currency": info.get("currency"),
                    "market_cap": info.get("marketCap"),
                    "enterprise_value": ev,
                    "revenue_ttm": rev,
                    "ebitda_ttm": ebitda,
                    "ev_revenue_ttm": (ev / rev) if (ev and rev) else None,
                    "ev_ebitda_ttm": (ev / ebitda) if (ev and ebitda) else None,
                    "ebitda_margin_ttm": (ebitda / rev) if (ebitda and rev) else None,
                    "rev_growth_ttm": info.get("revenueGrowth"),
                    "trailing_pe": info.get("trailingPE"),
                    "forward_pe": info.get("forwardPE"),
                }
                out.append(row)
            except Exception as inner:
                out.append({"ticker": tk, "error": str(inner)})
        return json.dumps({"peers": out, "note": "TTM multiples; for NTM use "
                            "analyst forecasts from filings."},
                          indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# =====================================================================
# Macro inputs
# =====================================================================
_TREASURY_TICKERS = {
    # country -> Yahoo symbol for 10y govt bond yield
    "US":     "^TNX",        # CBOE 10y Treasury Note Yield (in pct, ÷10 for raw)
    "INDIA":  "INDIAVIX",    # placeholder, see fallback
    "UK":     "^TNX",        # not perfect; UK gilt not directly on yahoo free
    "JAPAN":  "^TNX",
}

_DAMODARAN_ERP = {
    # rough static fallback (Damodaran updates monthly).
    # Always cross-check at https://pages.stern.nyu.edu/~adamodar/
    "US":     0.0500,
    "INDIA":  0.0721,
    "UK":     0.0530,
    "JAPAN":  0.0535,
    "CHINA":  0.0625,
    "BRAZIL": 0.0860,
}


@mcp.tool()
def get_treasury_yield(country: str = "US") -> str:
    """10-year govt bond yield. US is reliable via yfinance ^TNX.
    For India and others, returns guidance to use search_financials_web.
    """
    country = country.upper()
    try:
        if country == "US":
            yf = _yf()
            data = yf.Ticker("^TNX").history(period="5d")
            if data.empty:
                return f"ERROR: no data for ^TNX"
            yld_pct = float(data["Close"].iloc[-1])  # in percent
            return json.dumps({
                "country": "US", "tenor": "10y",
                "yield_pct": yld_pct,
                "yield_decimal": yld_pct / 100.0,
                "source": "Yahoo ^TNX (CBOE 10y Treasury Note Yield Index)",
                "as_of": str(data.index[-1])[:10],
            }, indent=2)
        else:
            return json.dumps({
                "country": country,
                "yield_pct": None,
                "note": f"No reliable yfinance source for {country} 10y. Use "
                         f"search_financials_web('current 10 year government bond "
                         f"yield {country}') to fetch from RBI / official source.",
            }, indent=2)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def get_damodaran_erp(country: str = "US") -> str:
    """Equity risk premium (Damodaran). NOTE: this returns a STATIC
    fallback value; you SHOULD fetch the latest from
    https://pages.stern.nyu.edu/~adamodar/ for production work.
    """
    country = country.upper()
    erp = _DAMODARAN_ERP.get(country)
    return json.dumps({
        "country": country,
        "erp": erp,
        "source": "static fallback (Jul-2026 vintage approx.)",
        "note": "FLAG this as [ESTIMATED — basis: static Damodaran fallback] "
                 "in the model unless you've verified the live value.",
    }, indent=2)


# =====================================================================
# Web fallback
# =====================================================================
@mcp.tool()
def search_financials_web(query: str, num_results: int = 5) -> str:
    """Fallback web search for financial data not available via yfinance
    (e.g. India 10y G-Sec yield, screener.in summary, recent investor deck).
    """
    try:
        from duckduckgo_search import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if not results:
            return f"No results for: {query}"
        out = [f"Search: {query}\n"]
        for i, r in enumerate(results, 1):
            out.append(f"{i}. {r.get('title', 'No title')}")
            out.append(f"   {r.get('href', '')}")
            out.append(f"   {r.get('body', '')[:300]}")
            out.append("")
        return "\n".join(out)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def fetch_url_text(url: str, max_chars: int = 8000) -> str:
    """Fetch and return cleaned text from a URL (for screener.in,
    investor presentations, etc.)."""
    try:
        import httpx
        from bs4 import BeautifulSoup
        with httpx.Client(timeout=15, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; "
                                                  "DCFAgent/1.0)"}) as c:
            resp = c.get(url)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        # collapse multiple newlines
        lines = [l for l in (ln.strip() for ln in text.splitlines()) if l]
        cleaned = "\n".join(lines)[:max_chars]
        return f"URL: {url}\n\n{cleaned}"
    except Exception as e:
        return f"ERROR fetching {url}: {type(e).__name__}: {e}"


# =====================================================================
# SEC EDGAR — official US company facts (free, no key, structured XBRL)
# =====================================================================
# SEC requires a User-Agent identifying the requester. Set FINANCE_UA env
# var or this default will be sent. Don't hammer (rate limit ~10 req/sec).
_SEC_UA = os.environ.get(
    "FINANCE_UA",
    "DCFAgent/1.0 (contact: dcf-agent@example.com)"
)

# Common XBRL tags we care about. SEC tags vary by reporting standard
# (us-gaap vs ifrs-full). We try multiple aliases.
_SEC_TAGS = {
    "revenue":       ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                       "SalesRevenueNet", "SalesRevenueGoodsNet"],
    "operating_income": ["OperatingIncomeLoss"],
    "net_income":    ["NetIncomeLoss"],
    "depreciation":  ["DepreciationDepletionAndAmortization",
                       "DepreciationAndAmortization", "Depreciation"],
    "capex":         ["PaymentsToAcquirePropertyPlantAndEquipment",
                       "PaymentsForCapitalImprovements"],
    "interest_expense": ["InterestExpense", "InterestExpenseDebt"],
    "income_tax":    ["IncomeTaxExpenseBenefit"],
    "pretax_income": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                       "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "cash":          ["CashAndCashEquivalentsAtCarryingValue", "Cash"],
    "long_term_debt": ["LongTermDebt", "LongTermDebtNoncurrent"],
    "short_term_debt": ["ShortTermBorrowings", "DebtCurrent"],
    "shares_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "shares_outstanding": ["CommonStockSharesOutstanding"],
}


def _sec_get(url: str) -> dict | None:
    """GET a SEC URL with the required User-Agent."""
    import httpx
    headers = {"User-Agent": _SEC_UA, "Accept": "application/json"}
    with httpx.Client(timeout=20, follow_redirects=True, headers=headers) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.json()


def _sec_ticker_to_cik(ticker: str) -> str | None:
    """Resolve a US ticker to a 10-digit CIK via SEC's mapping."""
    try:
        data = _sec_get("https://www.sec.gov/files/company_tickers.json")
        if not data:
            return None
        for entry in data.values():
            if entry.get("ticker", "").upper() == ticker.upper():
                cik = str(entry["cik_str"]).zfill(10)
                return cik
        return None
    except Exception:
        return None


@mcp.tool()
def get_sec_company_facts(ticker: str, years: int = 4) -> str:
    """SEC EDGAR XBRL company facts for a US ticker — the gold standard.

    Returns annual values for revenue, operating income, net income, D&A,
    capex, interest expense, taxes, debt, cash, and diluted shares — all
    sourced directly from filed 10-K/10-Q XBRL data (not scraped).

    Limited to US companies that file with the SEC.
    """
    try:
        cik = _sec_ticker_to_cik(ticker)
        if not cik:
            return (f"ERROR: ticker '{ticker}' not found in SEC EDGAR ticker "
                     f"list. Use a US ticker symbol (e.g. AAPL, MSFT). "
                     f"For non-US, use yfinance tools.")

        url = f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
        data = _sec_get(url)
        if not data:
            return f"ERROR: no XBRL data for CIK {cik}"

        company_name = data.get("entityName", ticker)
        facts = data.get("facts", {})
        # try us-gaap first, fall back to ifrs-full
        ns = "us-gaap" if "us-gaap" in facts else next(iter(facts), None)
        if not ns or ns not in facts:
            return f"ERROR: no us-gaap or ifrs-full facts for {ticker}"

        result: dict = {
            "ticker": ticker, "cik": cik, "name": company_name,
            "namespace": ns, "annual": {},
        }

        ns_facts = facts.get(ns, {})
        for our_key, sec_tags in _SEC_TAGS.items():
            for tag in sec_tags:
                if tag not in ns_facts:
                    continue
                units = ns_facts[tag].get("units", {})
                # prefer USD or shares explicitly; some facts have both
                # USD and USD/shares (per-share metrics) — USD is what we want
                unit_key = ("USD" if "USD" in units else
                            "shares" if "shares" in units else
                            next(iter(units), None))
                if not unit_key:
                    continue
                # Filter to annual (10-K) values
                annual = [r for r in units[unit_key]
                          if r.get("form") in ("10-K", "10-K/A")
                          and r.get("fp") == "FY"]
                annual.sort(key=lambda r: r.get("end", ""), reverse=True)
                # de-duplicate by fiscal year, keep most recent restatement
                seen: set = set()
                clean = []
                for r in annual:
                    fy = r.get("fy")
                    if fy in seen:
                        continue
                    seen.add(fy)
                    clean.append({"fy": fy, "end": r.get("end"),
                                   "val": r.get("val"), "unit": unit_key})
                    if len(clean) >= years:
                        break
                if clean:
                    result["annual"][our_key] = clean
                    break  # use first matching tag

        # derive EBITDA = Operating Income + D&A (where both exist for same FY)
        if "operating_income" in result["annual"] and "depreciation" in result["annual"]:
            oi_by_fy = {r["fy"]: r["val"] for r in result["annual"]["operating_income"]}
            da_by_fy = {r["fy"]: r["val"] for r in result["annual"]["depreciation"]}
            ebitda = []
            for fy in sorted(set(oi_by_fy) & set(da_by_fy), reverse=True):
                ebitda.append({"fy": fy, "val": oi_by_fy[fy] + da_by_fy[fy],
                                "unit": "USD",
                                "note": "derived: OperatingIncome + D&A"})
            if ebitda:
                result["annual"]["ebitda_derived"] = ebitda[:years]

        return json.dumps(result, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool()
def list_sec_filings(ticker: str, form_type: str = "10-K", limit: int = 5) -> str:
    """List recent SEC filings (10-K, 10-Q, etc.) for a US ticker, with
    URLs to the filing documents.
    """
    try:
        cik = _sec_ticker_to_cik(ticker)
        if not cik:
            return f"ERROR: ticker '{ticker}' not found in SEC EDGAR."

        url = f"https://data.sec.gov/submissions/CIK{cik}.json"
        data = _sec_get(url)
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accessions = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        primary_docs = recent.get("primaryDocument", [])

        out = []
        for i in range(len(forms)):
            if forms[i] != form_type:
                continue
            acc_clean = accessions[i].replace("-", "")
            doc_url = (f"https://www.sec.gov/Archives/edgar/data/"
                        f"{int(cik)}/{acc_clean}/{primary_docs[i]}")
            out.append({
                "form": forms[i],
                "filing_date": dates[i],
                "accession": accessions[i],
                "document_url": doc_url,
            })
            if len(out) >= limit:
                break

        return json.dumps({
            "ticker": ticker, "cik": cik, "form_type": form_type,
            "filings": out,
        }, indent=2, default=str)
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# =====================================================================
# screener.in — Indian retail/analyst standard
# =====================================================================
@mcp.tool()
def get_screener_summary(symbol: str, consolidated: bool = True) -> str:
    """Fetch the screener.in summary page for an Indian company.

    Returns key ratios, last 5y P&L, balance sheet, cash flow rows, and
    shareholding pattern — extracted from the page tables.

    Args:
      symbol: NSE symbol or company slug (e.g. 'RELIANCE', 'INFY', 'TCS')
      consolidated: True for consolidated financials (default), False for standalone
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
        sym = symbol.replace(".NS", "").replace(".BO", "").upper()
        suffix = "/consolidated/" if consolidated else "/"
        url = f"https://www.screener.in/company/{sym}{suffix}"
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (compatible; "
                                                  "DCFAgent/1.0)"}) as c:
            r = c.get(url)
            if r.status_code == 404 and consolidated:
                # not all companies have consolidated; try standalone
                url = f"https://www.screener.in/company/{sym}/"
                r = c.get(url)
            r.raise_for_status()

        soup = BeautifulSoup(r.text, "lxml")
        result: dict = {"symbol": sym, "url": url}

        # Header info
        header = soup.find("div", class_="company-info")
        if header:
            name_el = soup.find("h1")
            if name_el:
                result["name"] = name_el.get_text(strip=True)

        # Top ratios block (Market Cap, P/E, ROE, etc.)
        ratios: dict = {}
        for li in soup.select("ul#top-ratios li"):
            name_el = li.find("span", class_="name")
            value_el = li.find("span", class_="value") or li.find("span", class_="number")
            if name_el and value_el:
                ratios[name_el.get_text(strip=True)] = value_el.get_text(
                    " ", strip=True)
        if ratios:
            result["key_ratios"] = ratios

        # Tables: extract P&L, Balance Sheet, Cash Flow, Quarters
        def extract_table(section_id: str, label: str) -> list[dict] | None:
            section = soup.find("section", id=section_id)
            if not section:
                return None
            table = section.find("table")
            if not table:
                return None
            headers_cells = [th.get_text(strip=True) for th in table.find_all("th")]
            rows = []
            # Some tables don't have <tbody> — fall back to direct <tr> children
            tbody = table.find("tbody")
            tr_iter = tbody.find_all("tr") if tbody else table.find_all("tr")
            for tr in tr_iter:
                cells = [td.get_text(strip=True) for td in tr.find_all("td")]
                if len(cells) == len(headers_cells):
                    rows.append(dict(zip(headers_cells, cells)))
            return rows or None

        for sid, label in [
            ("profit-loss", "profit_loss"),
            ("balance-sheet", "balance_sheet"),
            ("cash-flow", "cash_flow"),
            ("quarters", "quarterly"),
            ("ratios", "ratios"),
        ]:
            data = extract_table(sid, label)
            if data:
                result[label] = data

        return json.dumps(result, indent=2, default=str)[:30000]  # cap size
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


# =====================================================================
# Damodaran live ERP fetch
# =====================================================================
@mcp.tool()
def get_damodaran_erp_live() -> str:
    """Fetch the latest country ERP table from Damodaran's NYU page.

    Returns the most recent ctryprem.html as parsed text. Damodaran
    updates this approximately monthly. Use this in preference to the
    static fallback `get_damodaran_erp` for production work.
    """
    try:
        import httpx
        from bs4 import BeautifulSoup
        url = "https://pages.stern.nyu.edu/~adamodar/New_Home_Page/datafile/ctryprem.html"
        with httpx.Client(timeout=20, follow_redirects=True,
                          headers={"User-Agent": "Mozilla/5.0 (DCFAgent/1.0)"}) as c:
            r = c.get(url)
            r.raise_for_status()
        soup = BeautifulSoup(r.text, "lxml")
        # Damodaran typically posts an HTML table with country | rating |
        # ERP | CRP. Extract tables, return as JSON.
        tables = soup.find_all("table")
        out = {"source": url, "fetched_at": "see HTTP date header",
                "tables": []}
        for ti, t in enumerate(tables):
            rows = []
            for tr in t.find_all("tr"):
                cells = [td.get_text(" ", strip=True)
                         for td in tr.find_all(["td", "th"])]
                if any(c for c in cells):
                    rows.append(cells)
            if rows and len(rows) > 5:   # skip tiny tables
                out["tables"].append({
                    "table_index": ti,
                    "row_count": len(rows),
                    "rows": rows[:120],   # cap to keep response size reasonable
                })
        if not out["tables"]:
            return ("ERROR: no usable tables found on Damodaran page. "
                     "Try fetching the URL manually with fetch_url_text.")
        return json.dumps(out, indent=2, default=str)[:30000]
    except Exception as e:
        return (f"ERROR fetching Damodaran ERP: {type(e).__name__}: {e}. "
                f"Fall back to get_damodaran_erp(country) for static value.")


if __name__ == "__main__":
    mcp.run(transport="stdio")
