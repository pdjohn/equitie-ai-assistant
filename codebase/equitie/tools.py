"""LLM-facing tools: schemas (Anthropic format) + a single dispatch function.

The model never touches the dataset directly. It calls one of these tools with
``investor_id`` bound by the application (not chosen by the model), and the tool
runs the matching deterministic function in ``metrics.py``.
"""

from __future__ import annotations

from . import metrics
from .data import DataStore

# Anthropic tool schemas. Kept deliberately small and unambiguous so the model
# routes reliably. ``investor_id`` is injected by the app, never by the model.
TOOL_SCHEMAS = [
    {
        "name": "get_portfolio_overview",
        "description": (
            "Whole-portfolio summary for the logged-in investor: every holding, "
            "total committed vs contributed, current value, net distributions, and "
            "portfolio MOIC/DPI/RVPI -- all in the investor's reporting currency. "
            "Use for 'how is my portfolio doing', 'what do I hold', 'my total value'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_position",
        "description": (
            "Detail on one company or deal the investor holds: cost basis, the share "
            "price they paid, current value and MOIC, broken out per round when they "
            "hold the same company across multiple rounds. Use for 'my Forgecraft "
            "position', 'how is <company> doing'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"company_or_deal": {"type": "string",
                           "description": "Company name, deal id, or 'Company Round'."}},
            "required": ["company_or_deal"],
        },
    },
    {
        "name": "get_obligations",
        "description": (
            "Upcoming capital calls and upcoming/overdue management & admin fees "
            "(future or unpaid as of the 2026-06-25 report date), in reporting currency. "
            "Use for 'what do I owe', 'upcoming fees', 'capital calls', 'anything overdue'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_realised_outcomes",
        "description": (
            "Distributions, exits and secondary sales: gross, carry withheld, and net "
            "received. Use for 'what have I been paid', 'my exits', 'distributions', 'returns realised'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_fees",
        "description": (
            "Fee schedule the investor pays: their effective management/performance/"
            "structuring/admin rates vs the deal standard, flagging discounts. Optionally "
            "scoped to one company/deal. Use for 'what fees do I pay', 'my fees on <company>'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"company_or_deal": {"type": "string",
                           "description": "Optional company/deal to scope to."}},
        },
    },
    {
        "name": "get_valuation_history",
        "description": (
            "How a company's mark has moved over time (share price + company valuation, "
            "up and down) and the effect on the investor's MOIC. Use for 'how has <company> "
            "valuation changed', 'is <company> up or down'."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"company_or_deal": {"type": "string",
                           "description": "Company name or deal id."}},
            "required": ["company_or_deal"],
        },
    },
    {
        "name": "get_account_statement",
        "description": (
            "Plain-language account statement summary: capital contributions, fees and "
            "distributions grouped by type, with cash paid in vs received. Use for "
            "'my account statement', 'summarise my cash flows'."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "get_investor_profile",
        "description": (
            "The investor's own profile and derived signals: reporting currency, KYC, "
            "number of deals, and top sectors by commitment. Mostly for context."
        ),
        "input_schema": {"type": "object", "properties": {}},
    },
]


def dispatch(store: DataStore, investor_id: str, tool_name: str, tool_input: dict) -> dict:
    """Run a tool. ``investor_id`` is authoritative and supplied by the app."""
    ti = tool_input or {}
    if tool_name == "get_portfolio_overview":
        return metrics.portfolio_overview(store, investor_id)
    if tool_name == "get_position":
        return metrics.position(store, investor_id, ti.get("company_or_deal", ""))
    if tool_name == "get_obligations":
        return metrics.obligations(store, investor_id)
    if tool_name == "get_realised_outcomes":
        return metrics.realised_outcomes(store, investor_id)
    if tool_name == "get_fees":
        return metrics.fees_breakdown(store, investor_id, ti.get("company_or_deal"))
    if tool_name == "get_valuation_history":
        return metrics.valuation_history(store, investor_id, ti.get("company_or_deal", ""))
    if tool_name == "get_account_statement":
        return metrics.account_statement(store, investor_id)
    if tool_name == "get_investor_profile":
        return metrics.get_investor(store, investor_id)
    return {"data": {"error": f"Unknown tool '{tool_name}'."}, "sources": []}
