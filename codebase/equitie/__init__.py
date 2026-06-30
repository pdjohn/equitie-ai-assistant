"""EquiTie Investor Assistant -- grounded, personalised portfolio Q&A.

Layers:
    data.py    -> load + index the CSV dataset (investor-scoped slices)
    metrics.py -> deterministic per-investor computations (the source of truth)
    tools.py   -> LLM-facing tool schemas + dispatch into metrics
    profile.py -> personalisation signals + system prompt
    assistant.py -> Claude tool-calling loop (with deterministic offline fallback)
"""

from .data import DataStore, REPORT_DATE

__all__ = ["DataStore", "REPORT_DATE"]
