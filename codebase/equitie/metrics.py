"""Deterministic portfolio metrics for a single investor.

Every number an investor sees is computed here in plain Python -- the LLM never
does arithmetic. Each public function returns a dict with two keys:

* ``data``    -- the computed result (JSON-serialisable)
* ``sources`` -- the source rows used, as ``"file.csv:ROW_ID"`` strings, so the
                 assistant can cite where each figure came from.

Conventions
-----------
* ``investor_id`` is always passed first and every query is filtered to that
  investor only -- cross-investor data cannot be reached from here.
* Amounts are reported in the investor's ``reporting_currency`` unless the field
  name says otherwise (``*_deal_ccy``). FX uses ``fx_rates.csv`` via USD.
* "Pending" (signed but unfunded) allocations are NOT counted as deployed
  capital: excluded from current value and MOIC, surfaced separately.
* Current value is 0 for Written Off deals and for fully-realised positions.
"""

from __future__ import annotations

from collections import defaultdict

import pandas as pd

from .data import REPORT_DATE, DataStore


# --------------------------------------------------------------------- helpers
def _round(x, n=2):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return None
    return round(float(x), n)


def _company_status_for_deal(store: DataStore, deal: dict) -> str:
    return store.company_by_id[deal["company_id"]]["status"]


def _realised_fraction(store: DataStore, allocation_id: str) -> float:
    d = store.distributions[store.distributions.allocation_id == allocation_id]
    return float(d["fraction_of_units"].sum()) if len(d) else 0.0


def _allocation_economics(store: DataStore, alloc: dict) -> dict:
    """Core per-allocation numbers in *deal currency* (pre-FX).

    Returns commitment, contributed, current value, distributions (gross/net),
    realised fraction, MOIC and the share price the investor actually paid.
    """
    deal = store.deal_by_id[alloc["deal_id"]]
    company = store.company_by_id[deal["company_id"]]
    latest = store.latest_valuation[alloc["deal_id"]]

    units = float(alloc["units"])
    realised = _realised_fraction(store, alloc["allocation_id"])
    live_units = units * (1.0 - realised)

    pending = alloc["allocation_status"] == "Pending"
    written_off = company["status"] == "Written Off"

    if pending or written_off:
        current_value = 0.0
    else:
        current_value = live_units * float(latest["share_price"])

    dist = store.distributions[store.distributions.allocation_id == alloc["allocation_id"]]
    dist_gross = float(dist["gross_amount"].sum()) if len(dist) else 0.0
    dist_net = float(dist["net_amount"].sum()) if len(dist) else 0.0
    carry_withheld = float(dist["performance_fee_amount"].sum()) if len(dist) else 0.0

    contributed = float(alloc["contributed_amount"])
    moic = (current_value + dist_net) / contributed if contributed > 0 else None

    return {
        "allocation_id": alloc["allocation_id"],
        "deal_id": deal["deal_id"],
        "company_id": company["company_id"],
        "company_name": deal["company_name"],
        "round": deal["round"],
        "sector": company["sector"],
        "deal_currency": alloc["deal_currency"],
        "deal_status": deal["status"],
        "company_status": company["status"],
        "allocation_status": alloc["allocation_status"],
        "is_pending": pending,
        "commitment": float(alloc["commitment_amount"]),
        "contributed": contributed,
        "outstanding_commitment": float(alloc["outstanding_commitment"]),
        "entry_share_price": float(deal["entry_share_price"]),
        "effective_share_price": float(alloc["effective_share_price"]),
        "price_discount_pct": float(alloc["price_discount_pct"]),
        "units": units,
        "realised_fraction": realised,
        "live_units": live_units,
        "latest_share_price": float(latest["share_price"]),
        "latest_valuation_date": str(latest["valuation_date"]),
        "latest_mark_source": latest["mark_source"],
        "current_value": current_value,
        "distributions_gross": dist_gross,
        "distributions_net": dist_net,
        "carry_withheld": carry_withheld,
        "moic": moic,
        "mgmt_fee_pct": float(alloc["mgmt_fee_pct"]),
        "performance_fee_pct": float(alloc["performance_fee_pct"]),
        "structuring_fee_pct": float(alloc["structuring_fee_pct"]),
        "admin_fee_usd": float(alloc["admin_fee_usd"]),
        "fee_discount": alloc["fee_discount"],
    }


def _glossary(terms: list[str]) -> dict:
    g = {
        "MOIC": "Multiple on Invested Capital = (current value + cash distributions) / capital you've contributed. 2.0x means your stake is worth twice what you put in.",
        "carry": "Carried interest / performance fee = the share of profits the manager keeps, taken from distributions before you receive them.",
        "DPI": "Distributions to Paid-In = cash already returned to you / capital you've contributed.",
        "RVPI": "Residual Value to Paid-In = current (unrealised) value / capital you've contributed.",
        "cost basis": "What you paid for your stake -- your effective share price times the number of units.",
        "capital call": "A request to pay in part of your committed capital.",
    }
    return {t: g[t] for t in terms if t in g}


# ------------------------------------------------------------------ investor
def get_investor(store: DataStore, investor_id: str) -> dict:
    inv = store.investor_by_id[investor_id]
    allocs = store.allocations_for(investor_id)

    sectors = defaultdict(float)
    for a in allocs.itertuples(index=False):
        deal = store.deal_by_id[a.deal_id]
        comp = store.company_by_id[deal["company_id"]]
        sectors[comp["sector"]] += store.fx_to(
            float(a.commitment_amount), a.deal_currency, inv["reporting_currency"]
        )
    top_sectors = sorted(sectors.items(), key=lambda kv: -kv[1])

    age = inv.get("age")
    age_val = None if age is None or pd.isna(age) else int(age)

    return {
        "data": {
            "investor_id": investor_id,
            "name": inv["investor_name"],
            "investor_type": inv["investor_type"],
            "country": inv["country"],
            "reporting_currency": inv["reporting_currency"],
            "age": age_val,
            "tech_savviness": inv["tech_savviness"],
            "kyc_status": inv["kyc_status"],
            "onboarded_date": str(inv["onboarded_date"]),
            "num_deals": int(len(allocs)),
            "num_active_allocations": int((allocs.allocation_status == "Active").sum()),
            "top_sectors": [{"sector": s, "committed_reporting_ccy": _round(v)} for s, v in top_sectors],
        },
        "sources": [f"investors.csv:{investor_id}"],
    }


# ------------------------------------------------------------ portfolio view
def portfolio_overview(store: DataStore, investor_id: str) -> dict:
    inv = store.investor_by_id[investor_id]
    rc = inv["reporting_currency"]
    allocs = store.allocations_for(investor_id)

    if len(allocs) == 0:
        return {
            "data": {
                "reporting_currency": rc,
                "has_holdings": False,
                "message": "This investor is onboarded but holds no allocations yet.",
            },
            "sources": [f"investors.csv:{investor_id}"],
        }

    holdings, sources = [], [f"investors.csv:{investor_id}"]
    tot_commit = tot_contrib = tot_value = tot_dist_net = 0.0
    pending_commit = 0.0

    for a in allocs.itertuples(index=False):
        e = _allocation_economics(store, a._asdict())
        sources.append(f"allocations.csv:{e['allocation_id']}")

        commit_rc = store.fx_to(e["commitment"], e["deal_currency"], rc)
        contrib_rc = store.fx_to(e["contributed"], e["deal_currency"], rc)
        value_rc = store.fx_to(e["current_value"], e["deal_currency"], rc)
        dist_rc = store.fx_to(e["distributions_net"], e["deal_currency"], rc)

        if e["is_pending"]:
            pending_commit += commit_rc
        else:
            tot_commit += commit_rc
            tot_contrib += contrib_rc
            tot_value += value_rc
            tot_dist_net += dist_rc

        holdings.append({
            "company_name": e["company_name"],
            "round": e["round"],
            "deal_id": e["deal_id"],
            "status": e["company_status"],
            "allocation_status": e["allocation_status"],
            "commitment_reporting_ccy": _round(commit_rc),
            "contributed_reporting_ccy": _round(contrib_rc),
            "current_value_reporting_ccy": _round(value_rc),
            "distributions_net_reporting_ccy": _round(dist_rc),
            "moic": _round(e["moic"], 3),
        })

    moic = (tot_value + tot_dist_net) / tot_contrib if tot_contrib > 0 else None
    dpi = tot_dist_net / tot_contrib if tot_contrib > 0 else None
    rvpi = tot_value / tot_contrib if tot_contrib > 0 else None

    return {
        "data": {
            "reporting_currency": rc,
            "has_holdings": True,
            "num_holdings": len(holdings),
            "total_committed": _round(tot_commit),
            "total_contributed": _round(tot_contrib),
            "total_current_value": _round(tot_value),
            "total_distributions_net": _round(tot_dist_net),
            "pending_unfunded_commitment": _round(pending_commit),
            "portfolio_moic": _round(moic, 3),
            "dpi": _round(dpi, 3),
            "rvpi": _round(rvpi, 3),
            "holdings": holdings,
            "glossary": _glossary(["MOIC", "DPI", "RVPI"]),
        },
        "sources": sources,
    }


# --------------------------------------------------------------- single position
def position(store: DataStore, investor_id: str, query: str) -> dict:
    """Detail for a company (aggregating rounds) or a specific deal.

    ``query`` is matched case-insensitively against company name / deal id /
    company id. Multi-round holdings are aggregated and also broken out per round.
    """
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    allocs = store.allocations_for(investor_id)
    q = query.strip().lower()

    matched = []
    for a in allocs.itertuples(index=False):
        deal = store.deal_by_id[a.deal_id]
        comp = store.company_by_id[deal["company_id"]]
        hay = [deal["company_name"].lower(), deal["deal_id"].lower(),
               comp["company_id"].lower(), f"{deal['company_name']} {deal['round']}".lower()]
        if any(q in h or h in q for h in hay):
            matched.append(a._asdict())

    if not matched:
        return {
            "data": {"found": False,
                     "message": f"No holding matching '{query}' for this investor.",
                     "available_companies": sorted({store.deal_by_id[a.deal_id]['company_name']
                                                    for a in allocs.itertuples(index=False)})},
            "sources": [],
        }

    rounds, sources = [], []
    tot_contrib = tot_value = tot_dist = tot_commit = 0.0
    for a in matched:
        e = _allocation_economics(store, a)
        sources.append(f"allocations.csv:{e['allocation_id']}")
        sources.append(f"valuations.csv:{e['deal_id']}@{e['latest_valuation_date']}")
        commit_rc = store.fx_to(e["commitment"], e["deal_currency"], rc)
        contrib_rc = store.fx_to(e["contributed"], e["deal_currency"], rc)
        value_rc = store.fx_to(e["current_value"], e["deal_currency"], rc)
        dist_rc = store.fx_to(e["distributions_net"], e["deal_currency"], rc)
        if not e["is_pending"]:
            tot_commit += commit_rc
            tot_contrib += contrib_rc
            tot_value += value_rc
            tot_dist += dist_rc
        rounds.append({
            "company_name": e["company_name"],
            "round": e["round"],
            "deal_id": e["deal_id"],
            "deal_currency": e["deal_currency"],
            "allocation_status": e["allocation_status"],
            "company_status": e["company_status"],
            "commitment_deal_ccy": _round(e["commitment"]),
            "contributed_deal_ccy": _round(e["contributed"]),
            "outstanding_commitment_deal_ccy": _round(e["outstanding_commitment"]),
            "entry_share_price": e["entry_share_price"],
            "your_effective_share_price": e["effective_share_price"],
            "price_discount_pct": e["price_discount_pct"],
            "units": _round(e["units"], 4),
            "realised_fraction": e["realised_fraction"],
            "latest_share_price": e["latest_share_price"],
            "latest_mark_source": e["latest_mark_source"],
            "latest_valuation_date": e["latest_valuation_date"],
            "current_value_reporting_ccy": _round(value_rc),
            "distributions_net_reporting_ccy": _round(dist_rc),
            "moic": _round(e["moic"], 3),
        })

    agg_moic = (tot_value + tot_dist) / tot_contrib if tot_contrib > 0 else None
    return {
        "data": {
            "found": True,
            "company_name": rounds[0]["company_name"],
            "reporting_currency": rc,
            "num_rounds": len(rounds),
            "aggregate": {
                "total_committed_reporting_ccy": _round(tot_commit),
                "total_contributed_reporting_ccy": _round(tot_contrib),
                "total_current_value_reporting_ccy": _round(tot_value),
                "total_distributions_net_reporting_ccy": _round(tot_dist),
                "moic": _round(agg_moic, 3),
            },
            "rounds": rounds,
            "glossary": _glossary(["MOIC", "cost basis"]),
        },
        "sources": sources,
    }


# ---------------------------------------------------------------- obligations
def obligations(store: DataStore, investor_id: str) -> dict:
    """Upcoming / overdue capital calls and fees relative to the report date."""
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    calls = store.calls_for(investor_id)
    fees = store.fees_for(investor_id)

    upcoming_calls, sources = [], []
    call_total_rc = 0.0
    for c in calls.itertuples(index=False):
        if c.status == "Upcoming":
            amt_rc = store.fx_to(float(c.amount), c.currency, rc)
            call_total_rc += amt_rc
            sources.append(f"capital_calls.csv:{c.call_id}")
            deal = store.deal_by_id[c.deal_id]
            upcoming_calls.append({
                "call_id": c.call_id,
                "company_name": deal["company_name"],
                "round": deal["round"],
                "call_number": int(c.call_number),
                "due_date": str(c.due_date),
                "amount_deal_ccy": _round(float(c.amount)),
                "currency": c.currency,
                "amount_reporting_ccy": _round(amt_rc),
            })

    fee_items = []
    fee_total_rc = 0.0
    for f in fees.itertuples(index=False):
        if f.status in ("Upcoming", "Overdue") and f.fee_type in ("Management Fee", "Admin Fee"):
            cur = f.currency
            amt_rc = store.fx_to(float(f.amount), cur, rc)
            fee_total_rc += amt_rc
            sources.append(f"fees.csv:{f.fee_id}")
            deal = store.deal_by_id[f.deal_id]
            fee_items.append({
                "fee_id": f.fee_id,
                "company_name": deal["company_name"],
                "round": deal["round"],
                "fee_type": f.fee_type,
                "period": f.period,
                "status": f.status,
                "due_date": str(f.due_date),
                "amount_original": _round(float(f.amount)),
                "currency": cur,
                "amount_reporting_ccy": _round(amt_rc),
            })

    # Signed-but-unfunded (Pending) commitments: not yet a scheduled call, but
    # still money the investor has agreed to put in -- surface so "what do I owe?"
    # is complete (e.g. Grace Okafor's Helixar Bio commitment).
    allocs = store.allocations_for(investor_id)
    pending = []
    pending_total_rc = 0.0
    for a in allocs.itertuples(index=False):
        if a.allocation_status == "Pending" and float(a.outstanding_commitment) > 0:
            amt_rc = store.fx_to(float(a.outstanding_commitment), a.deal_currency, rc)
            pending_total_rc += amt_rc
            sources.append(f"allocations.csv:{a.allocation_id}")
            deal = store.deal_by_id[a.deal_id]
            pending.append({
                "allocation_id": a.allocation_id,
                "company_name": deal["company_name"],
                "round": deal["round"],
                "outstanding_commitment_deal_ccy": _round(float(a.outstanding_commitment)),
                "currency": a.deal_currency,
                "amount_reporting_ccy": _round(amt_rc),
                "note": "Signed but unfunded; no capital call has been scheduled yet.",
            })

    overdue = [x for x in fee_items if x["status"] == "Overdue"]
    return {
        "data": {
            "reporting_currency": rc,
            "report_date": str(REPORT_DATE),
            "upcoming_capital_calls": sorted(upcoming_calls, key=lambda x: x["due_date"]),
            "total_upcoming_calls_reporting_ccy": _round(call_total_rc),
            "fees_due": sorted(fee_items, key=lambda x: x["due_date"]),
            "total_fees_due_reporting_ccy": _round(fee_total_rc),
            "num_overdue": len(overdue),
            "pending_unfunded_commitments": pending,
            "total_pending_unfunded_reporting_ccy": _round(pending_total_rc),
            "total_obligations_reporting_ccy": _round(call_total_rc + fee_total_rc),
            "glossary": _glossary(["capital call"]),
        },
        "sources": sources,
    }


# ----------------------------------------------------------- realised outcomes
def realised_outcomes(store: DataStore, investor_id: str) -> dict:
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    dist = store.distributions_for(investor_id)
    if len(dist) == 0:
        return {"data": {"reporting_currency": rc, "has_distributions": False,
                         "message": "No distributions or exits recorded for this investor yet."},
                "sources": []}

    items, sources = [], []
    tot_gross = tot_net = tot_carry = 0.0
    for d in dist.itertuples(index=False):
        deal = store.deal_by_id[d.deal_id]
        gross_rc = store.fx_to(float(d.gross_amount), d.currency, rc)
        net_rc = store.fx_to(float(d.net_amount), d.currency, rc)
        carry_rc = store.fx_to(float(d.performance_fee_amount), d.currency, rc)
        tot_gross += gross_rc; tot_net += net_rc; tot_carry += carry_rc
        sources.append(f"distributions.csv:{d.distribution_id}")
        items.append({
            "distribution_id": d.distribution_id,
            "company_name": deal["company_name"],
            "round": deal["round"],
            "date": str(d.distribution_date),
            "type": d.distribution_type,
            "fraction_of_units": float(d.fraction_of_units),
            "gross_reporting_ccy": _round(gross_rc),
            "performance_fee_pct": float(d.performance_fee_pct),
            "carry_withheld_reporting_ccy": _round(carry_rc),
            "net_received_reporting_ccy": _round(net_rc),
            "currency_original": d.currency,
        })
    return {
        "data": {
            "reporting_currency": rc,
            "has_distributions": True,
            "distributions": sorted(items, key=lambda x: x["date"]),
            "total_gross_reporting_ccy": _round(tot_gross),
            "total_carry_withheld_reporting_ccy": _round(tot_carry),
            "total_net_received_reporting_ccy": _round(tot_net),
            "glossary": _glossary(["carry"]),
        },
        "sources": sources,
    }


# ------------------------------------------------------------------- fees view
def fees_breakdown(store: DataStore, investor_id: str, query: str | None = None) -> dict:
    """Effective fees vs the deal standard, per holding.

    If ``query`` is given, restrict to the matching company/deal.
    """
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    allocs = store.allocations_for(investor_id)
    q = (query or "").strip().lower()

    rows, sources = [], []
    for a in allocs.itertuples(index=False):
        deal = store.deal_by_id[a.deal_id]
        comp = store.company_by_id[deal["company_id"]]
        if q:
            hay = [deal["company_name"].lower(), deal["deal_id"].lower(),
                   f"{deal['company_name']} {deal['round']}".lower()]
            if not any(q in h or h in q for h in hay):
                continue
        sources.append(f"allocations.csv:{a.allocation_id}")
        sources.append(f"deals.csv:{deal['deal_id']}")

        def cmp(eff, std):
            eff, std = float(eff), float(std)
            return {"effective": eff, "deal_standard": std,
                    "discounted": eff < std, "saving_pct_points": _round(std - eff, 3)}

        rows.append({
            "company_name": deal["company_name"],
            "round": deal["round"],
            "deal_id": deal["deal_id"],
            "fee_discount_flag": a.fee_discount,
            "management_fee": cmp(a.mgmt_fee_pct, deal["std_mgmt_fee_pct"]),
            "performance_fee_carry": cmp(a.performance_fee_pct, deal["std_performance_fee_pct"]),
            "structuring_fee": cmp(a.structuring_fee_pct, deal["std_structuring_fee_pct"]),
            "admin_fee_usd": {"effective": float(a.admin_fee_usd),
                              "deal_standard": float(deal["std_admin_fee_usd"]),
                              "waived": float(a.admin_fee_usd) == 0.0},
            "fees_accruing": comp["status"] == "Active",
            "note": ("Management & admin fees stop accruing on exited / written-off deals."
                     if comp["status"] != "Active" else None),
        })

    if not rows:
        return {"data": {"found": False, "message": f"No matching deal for '{query}'."}, "sources": []}
    return {
        "data": {"reporting_currency": rc, "fees_by_holding": rows,
                 "glossary": _glossary(["carry"])},
        "sources": sources,
    }


# -------------------------------------------------------------- valuations view
def valuation_history(store: DataStore, investor_id: str, query: str) -> dict:
    """Mark history for a company the investor holds + the effect on their MOIC."""
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    allocs = store.allocations_for(investor_id)
    q = query.strip().lower()

    held_deals = {}
    for a in allocs.itertuples(index=False):
        deal = store.deal_by_id[a.deal_id]
        hay = [deal["company_name"].lower(), deal["deal_id"].lower(),
               f"{deal['company_name']} {deal['round']}".lower()]
        if any(q in h or h in q for h in hay):
            held_deals[a.deal_id] = a._asdict()

    if not held_deals:
        return {"data": {"found": False, "message": f"No holding matching '{query}' for this investor."},
                "sources": []}

    series, sources = [], []
    for deal_id, alloc in held_deals.items():
        deal = store.deal_by_id[deal_id]
        vrows = store.valuations[store.valuations.deal_id == deal_id].sort_values("valuation_date")
        marks = []
        for v in vrows.itertuples(index=False):
            sources.append(f"valuations.csv:{v.valuation_id}")
            marks.append({
                "date": str(v.valuation_date),
                "share_price": float(v.share_price),
                "company_valuation_m": float(v.company_valuation_m),
                "mark_source": v.mark_source,
                "multiple_vs_entry": float(v.multiple_vs_entry),
            })
        e = _allocation_economics(store, alloc)
        sources.append(f"allocations.csv:{alloc['allocation_id']}")
        series.append({
            "company_name": deal["company_name"],
            "round": deal["round"],
            "deal_id": deal_id,
            "deal_currency": deal["deal_currency"],
            "entry_share_price": float(deal["entry_share_price"]),
            "your_effective_share_price": e["effective_share_price"],
            "current_share_price": e["latest_share_price"],
            "direction": ("up" if e["latest_share_price"] > e["entry_share_price"]
                          else "down" if e["latest_share_price"] < e["entry_share_price"]
                          else "flat"),
            "marks": marks,
            "your_current_moic": _round(e["moic"], 3),
        })
    return {"data": {"found": True, "reporting_currency": rc, "series": series,
                     "glossary": _glossary(["MOIC"])},
            "sources": sources}


# --------------------------------------------------------------- account statement
def account_statement(store: DataStore, investor_id: str) -> dict:
    rc = store.investor_by_id[investor_id]["reporting_currency"]
    lines = store.statement_for(investor_id)
    if len(lines) == 0:
        return {"data": {"reporting_currency": rc, "has_activity": False,
                         "message": "No account statement activity for this investor yet."},
                "sources": []}

    by_type = defaultdict(lambda: {"count": 0, "total_reporting_ccy": 0.0})
    cash_out = cash_in = 0.0
    sources = []
    for ln in lines.itertuples(index=False):
        amt_rc = store.fx_to(float(ln.amount), ln.currency, rc)
        by_type[ln.type]["count"] += 1
        by_type[ln.type]["total_reporting_ccy"] += amt_rc
        if amt_rc < 0:
            cash_out += amt_rc
        else:
            cash_in += amt_rc
        sources.append(f"statement_lines.csv:{ln.line_id}")

    summary = {k: {"count": v["count"], "total_reporting_ccy": _round(v["total_reporting_ccy"])}
               for k, v in sorted(by_type.items())}
    return {
        "data": {
            "reporting_currency": rc,
            "has_activity": True,
            "num_lines": int(len(lines)),
            "by_type": summary,
            "total_paid_out_reporting_ccy": _round(cash_out),
            "total_received_reporting_ccy": _round(cash_in),
            "net_position_reporting_ccy": _round(cash_in + cash_out),
            "note": "Negative = cash you paid in (contributions, fees). Positive = cash you received (distributions).",
        },
        # Cap citations to keep payloads small; statements can have many lines.
        "sources": sources[:40],
    }
