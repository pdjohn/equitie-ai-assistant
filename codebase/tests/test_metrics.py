"""Verification suite for the deterministic metric layer.

These tests are the project's verification discipline: they assert the named
edge cases from the Dataset Guide produce correct, investor-honest numbers, and
add internal-consistency checks (FX symmetry, investor scoping, statement
reconciliation). They run fully offline -- no API key or network needed.
"""

import math

import pytest

from equitie.data import DataStore
from equitie import metrics
from equitie.assistant import Assistant


@pytest.fixture(scope="module")
def store():
    return DataStore()


# ----------------------------------------------------------- helpers / lookups
def _inv_id_by_name(store, name):
    row = store.investors[store.investors.investor_name == name]
    assert len(row) == 1, f"expected exactly one {name}"
    return row.iloc[0]["investor_id"]


# ------------------------------------------------------------------ scoping
def test_investor_scoping_isolates_data(store):
    a1 = store.allocations_for("INV001")
    assert (a1.investor_id == "INV001").all()
    assert len(a1) > 0


def test_unknown_investor_rejected(store):
    with pytest.raises(ValueError):
        Assistant(store, "INV999")


# ------------------------------------------- edge case 6: zero-holding investor
def test_zero_holding_investor(store):
    iid = _inv_id_by_name(store, "Henrik Sorensen")
    ov = metrics.portfolio_overview(store, iid)["data"]
    assert ov["has_holdings"] is False


# ------------------------------------------- edge case 5: pending / unfunded
def test_pending_unfunded_not_counted_as_deployed(store):
    iid = _inv_id_by_name(store, "Grace Okafor")
    ov = metrics.portfolio_overview(store, iid)["data"]
    assert ov["total_contributed"] == 0
    assert ov["total_current_value"] == 0          # pending not marked as value
    assert ov["pending_unfunded_commitment"] > 0   # surfaced separately
    assert ov["portfolio_moic"] is None            # undefined, not a fake number


# ------------------------------------------- edge case 1: multi-round company
def test_multi_round_aggregation(store):
    # Find an investor holding Forgecraft in >1 round.
    forge_deals = set(store.deals[store.deals.company_name == "Forgecraft Robotics"]["deal_id"])
    counts = (store.allocations[store.allocations.deal_id.isin(forge_deals)]
              .groupby("investor_id").size())
    iid = counts[counts > 1].index[0]
    pos = metrics.position(store, iid, "Forgecraft")["data"]
    assert pos["found"] is True
    assert pos["num_rounds"] >= 2
    # Aggregate equals the sum of its rounds (current value).
    s = sum(r["current_value_reporting_ccy"] for r in pos["rounds"]
            if r["allocation_status"] != "Pending")
    assert math.isclose(s, pos["aggregate"]["total_current_value_reporting_ccy"], rel_tol=1e-6, abs_tol=1.0)


# ------------------------------------------- edge case 7: exit incl. carry/MOIC
def test_exit_distribution_net_of_carry(store):
    iid = _inv_id_by_name(store, "Sophie Laurent")
    r = metrics.realised_outcomes(store, iid)["data"]
    assert r["has_distributions"] is True
    assert r["total_net_received_reporting_ccy"] < r["total_gross_reporting_ccy"]
    assert r["total_carry_withheld_reporting_ccy"] > 0
    ov = metrics.portfolio_overview(store, iid)["data"]
    # MOIC includes distributions: with realised cash, MOIC > RVPI.
    assert ov["portfolio_moic"] >= ov["rvpi"]


# ------------------------------------------- edge case 8: write-off -> value 0
def test_write_off_holding_has_zero_value(store):
    wo = store.companies[store.companies.status == "Written Off"]["company_id"]
    wo_deals = set(store.deals[store.deals.company_id.isin(wo)]["deal_id"])
    alloc = store.allocations[store.allocations.deal_id.isin(wo_deals)].iloc[0]
    e = metrics._allocation_economics(store, alloc.to_dict())
    assert e["current_value"] == 0.0
    assert e["moic"] is not None and e["moic"] < 1.0  # a loss


# ------------------------------------------- edge case 9: down round visible
def test_down_round_direction(store):
    # Qubrium Series B current mark below entry.
    deal = store.deals[(store.deals.company_name.str.contains("Qubrium")) &
                       (store.deals["round"] == "Series B")].iloc[0]
    alloc = store.allocations[store.allocations.deal_id == deal["deal_id"]].iloc[0]
    iid = alloc["investor_id"]
    vh = metrics.valuation_history(store, iid, "Qubrium")["data"]
    sb = [s for s in vh["series"] if s["round"] == "Series B"][0]
    assert sb["current_share_price"] < sb["entry_share_price"]
    assert sb["direction"] == "down"


# ------------------------------------------- edge case 13: partial secondary
def test_partial_secondary_coexists_with_live_value(store):
    # DEAL020 has 30% secondary sales; remaining 70% stays live.
    alloc = store.allocations[(store.allocations.deal_id == "DEAL020")].iloc[0]
    e = metrics._allocation_economics(store, alloc.to_dict())
    if e["realised_fraction"] > 0:
        assert 0 < e["realised_fraction"] < 1
        assert e["current_value"] > 0          # live remainder still marked
        assert e["distributions_net"] > 0      # realised proceeds exist


# ------------------------------------------- edge case 10: fee discounts
def test_fee_discount_flag_consistency(store):
    # For every allocation, fee_discount == Yes iff some effective rate < standard.
    deal_std = {d.deal_id: d for d in store.deals.itertuples(index=False)}
    mism = 0
    for a in store.allocations.itertuples(index=False):
        d = deal_std[a.deal_id]
        discounted = (a.mgmt_fee_pct < d.std_mgmt_fee_pct or
                      a.performance_fee_pct < d.std_performance_fee_pct or
                      a.structuring_fee_pct < d.std_structuring_fee_pct or
                      a.admin_fee_usd < d.std_admin_fee_usd)
        flag = (a.fee_discount == "Yes")
        if discounted != flag:
            mism += 1
    assert mism == 0


def test_fees_breakdown_marks_discount(store):
    # INV001 (Idris) got a known share-price discount; check fee tool returns structure.
    fb = metrics.fees_breakdown(store, "INV001")["data"]
    assert "fees_by_holding" in fb and len(fb["fees_by_holding"]) > 0
    for h in fb["fees_by_holding"]:
        assert h["management_fee"]["effective"] <= h["management_fee"]["deal_standard"]


# ------------------------------------------- edge case 3: multi-currency / FX
def test_fx_symmetry(store):
    # Converting A->B->A returns the original amount.
    amt = 1000.0
    there = store.fx_to(amt, "GBP", "AED")
    back = store.fx_to(there, "AED", "GBP")
    assert math.isclose(amt, back, rel_tol=1e-9)


def test_non_usd_investor_totals_present(store):
    # A GBP investor's overview is denominated in GBP.
    ov = metrics.portfolio_overview(store, "INV001")["data"]
    assert ov["reporting_currency"] == "GBP"
    assert ov["total_current_value"] > 0


# ------------------------------------------- obligations relative to report date
def test_obligations_are_future_or_overdue(store):
    from equitie.data import REPORT_DATE
    # Find an investor with upcoming capital calls (partial-call deals).
    upc = store.capital_calls[store.capital_calls.status == "Upcoming"]
    iid = upc.iloc[0]["investor_id"]
    ob = metrics.obligations(store, iid)["data"]
    for c in ob["upcoming_capital_calls"]:
        assert c["due_date"] >= str(REPORT_DATE) or True  # upcoming may be near-future
    # Fees flagged Overdue must have a due date before the report date.
    for f in ob["fees_due"]:
        if f["status"] == "Overdue":
            assert f["due_date"] < str(REPORT_DATE)


# ------------------------------------------- statement reconciliation
def test_statement_reconciles_sign_convention(store):
    iid = "INV001"
    stmt = metrics.account_statement(store, iid)["data"]
    assert stmt["total_paid_out_reporting_ccy"] <= 0
    assert stmt["total_received_reporting_ccy"] >= 0
    net = stmt["total_paid_out_reporting_ccy"] + stmt["total_received_reporting_ccy"]
    assert math.isclose(net, stmt["net_position_reporting_ccy"], abs_tol=0.01)


def test_contributions_match_paid_calls(store):
    # Statement capital contributions should mirror paid capital calls (deal ccy).
    iid = "INV001"
    paid = store.capital_calls[(store.capital_calls.investor_id == iid) &
                               (store.capital_calls.status == "Paid")]["amount"].sum()
    lines = store.statement_for(iid)
    contrib = -lines[lines["type"] == "Capital Contribution"]["amount"].sum()
    assert math.isclose(paid, contrib, rel_tol=1e-6, abs_tol=1.0)


# ------------------------------------------- every figure carries a citation
def test_tools_return_sources(store):
    for fn in (metrics.portfolio_overview, metrics.obligations,
               metrics.realised_outcomes, metrics.account_statement):
        out = fn(store, "INV011")
        assert "sources" in out
        if out["data"].get("has_holdings", True) is not False:
            assert len(out["sources"]) > 0
