"""Data access layer for the EquiTie Investor Assistant.

Loads the synthetic CSV dataset into pandas DataFrames, builds the indices the
metric functions rely on, and exposes a small set of grounded lookups.

Design notes
------------
* The report date is fixed at 2026-06-25 (see ``REPORT_DATE``). Anything
  "upcoming" / "current" is judged against this date, never ``datetime.now()``.
* All FX conversion goes through USD using ``fx_rates.csv``.
* Nothing in this module is investor-specific; scoping to a single investor is
  the caller's responsibility (enforced in ``metrics.py``).
"""

from __future__ import annotations

import os
from datetime import date
from functools import cached_property

import pandas as pd

# Treat this as "today" for all upcoming / current figures (per the brief).
REPORT_DATE = date(2026, 6, 25)

# Default location: ../data relative to this package.
_DEFAULT_DATA_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "..", "data")
)


def _to_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce").dt.date


class DataStore:
    """Loads and indexes the dataset. One instance is shared across the app."""

    def __init__(self, data_dir: str | None = None):
        self.data_dir = data_dir or os.environ.get("EQUITIE_DATA_DIR", _DEFAULT_DATA_DIR)
        if not os.path.isdir(self.data_dir):
            raise FileNotFoundError(
                f"Data directory not found: {self.data_dir}. "
                "Set EQUITIE_DATA_DIR or pass data_dir."
            )
        self._load()

    # ------------------------------------------------------------------ load
    def _csv(self, name: str) -> pd.DataFrame:
        return pd.read_csv(os.path.join(self.data_dir, name))

    def _load(self) -> None:
        self.investors = self._csv("investors.csv")
        self.companies = self._csv("portfolio_companies.csv")
        self.deals = self._csv("deals.csv")
        self.valuations = self._csv("valuations.csv")
        self.allocations = self._csv("allocations.csv")
        self.capital_calls = self._csv("capital_calls.csv")
        self.fees = self._csv("fees.csv")
        self.distributions = self._csv("distributions.csv")
        self.statement_lines = self._csv("statement_lines.csv")
        self.fx_rates = self._csv("fx_rates.csv")

        # Normalise date columns we compare against REPORT_DATE.
        for df, cols in [
            (self.valuations, ["valuation_date"]),
            (self.capital_calls, ["call_date", "due_date"]),
            (self.fees, ["due_date"]),
            (self.distributions, ["distribution_date"]),
            (self.statement_lines, ["date"]),
            (self.deals, ["deal_date"]),
        ]:
            for c in cols:
                df[c] = _to_date(df[c])

        self.fx = dict(zip(self.fx_rates["currency"], self.fx_rates["to_usd"]))

    # ----------------------------------------------------------------- index
    @cached_property
    def investor_by_id(self) -> dict:
        return {r.investor_id: r._asdict() for r in self.investors.itertuples(index=False)}

    @cached_property
    def deal_by_id(self) -> dict:
        return {r.deal_id: r._asdict() for r in self.deals.itertuples(index=False)}

    @cached_property
    def company_by_id(self) -> dict:
        return {r.company_id: r._asdict() for r in self.companies.itertuples(index=False)}

    @cached_property
    def latest_valuation(self) -> dict:
        """Most recent valuation row per deal (drives current value / MOIC)."""
        idx = self.valuations.sort_values("valuation_date").groupby("deal_id").tail(1)
        return {r.deal_id: r._asdict() for r in idx.itertuples(index=False)}

    # --------------------------------------------------------------- helpers
    def fx_to(self, amount: float, from_ccy: str, to_ccy: str) -> float:
        """Convert ``amount`` from one currency to another via USD."""
        if amount is None or pd.isna(amount):
            return 0.0
        if from_ccy == to_ccy:
            return float(amount)
        usd = float(amount) * float(self.fx[from_ccy])
        return usd / float(self.fx[to_ccy])

    def investor_exists(self, investor_id: str) -> bool:
        return investor_id in self.investor_by_id

    def list_investors(self) -> pd.DataFrame:
        return self.investors[["investor_id", "investor_name", "reporting_currency"]]

    # Investor-scoped row slices -- the single choke point for data access.
    def allocations_for(self, investor_id: str) -> pd.DataFrame:
        return self.allocations[self.allocations.investor_id == investor_id].copy()

    def fees_for(self, investor_id: str) -> pd.DataFrame:
        return self.fees[self.fees.investor_id == investor_id].copy()

    def calls_for(self, investor_id: str) -> pd.DataFrame:
        return self.capital_calls[self.capital_calls.investor_id == investor_id].copy()

    def distributions_for(self, investor_id: str) -> pd.DataFrame:
        return self.distributions[self.distributions.investor_id == investor_id].copy()

    def statement_for(self, investor_id: str) -> pd.DataFrame:
        return self.statement_lines[self.statement_lines.investor_id == investor_id].copy()
