"""The assistant orchestration loop.

Claude is the *router and writer*: it reads the question, calls one or more
deterministic tools, then writes a grounded, personalised answer. All numbers
come from the tools.

If no ANTHROPIC_API_KEY is configured, the assistant falls back to a
deterministic keyword router (`_offline_answer`) so the prototype still runs and
the data layer stays demonstrable without an LLM. The fallback is clearly
labelled and not personalised in prose -- it just surfaces the tool output.
"""

from __future__ import annotations

import json
import os

from .data import DataStore
from .profile import system_prompt
from . import tools

DEFAULT_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5")
MAX_TOOL_ROUNDS = 6


class Assistant:
    def __init__(self, store: DataStore, investor_id: str, model: str | None = None):
        if not store.investor_exists(investor_id):
            raise ValueError(f"Unknown investor_id: {investor_id}")
        self.store = store
        self.investor_id = investor_id
        self.model = model or DEFAULT_MODEL
        self.system = system_prompt(store, investor_id)
        self.history: list[dict] = []  # Anthropic message dicts
        self._client = self._make_client()

    # ------------------------------------------------------------------ setup
    def _make_client(self):
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            return None
        try:
            import anthropic
            return anthropic.Anthropic(api_key=api_key)
        except Exception:
            return None

    @property
    def online(self) -> bool:
        return self._client is not None

    # ------------------------------------------------------------------- main
    def ask(self, user_message: str) -> dict:
        """Return {'text': str, 'sources': [...], 'tool_calls': [...], 'mode': 'llm'|'offline'}."""
        if not self.online:
            return self._offline_answer(user_message)
        return self._llm_answer(user_message)

    # ---------------------------------------------------------------- llm path
    def _llm_answer(self, user_message: str) -> dict:
        import anthropic  # noqa: F401  (client already constructed)

        self.history.append({"role": "user", "content": user_message})
        collected_sources: list[str] = []
        tool_calls: list[dict] = []

        for _ in range(MAX_TOOL_ROUNDS):
            resp = self._client.messages.create(
                model=self.model,
                max_tokens=1500,
                system=self.system,
                tools=tools.TOOL_SCHEMAS,
                messages=self.history,
            )
            self.history.append({"role": "assistant", "content": resp.content})

            if resp.stop_reason != "tool_use":
                text = "".join(b.text for b in resp.content if b.type == "text")
                return {"text": text, "sources": _dedup(collected_sources),
                        "tool_calls": tool_calls, "mode": "llm"}

            tool_results = []
            for block in resp.content:
                if block.type != "tool_use":
                    continue
                result = tools.dispatch(self.store, self.investor_id, block.name, block.input)
                collected_sources.extend(result.get("sources", []))
                tool_calls.append({"tool": block.name, "input": block.input})
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result),
                })
            self.history.append({"role": "user", "content": tool_results})

        return {"text": "I wasn't able to complete that within the tool budget. Please rephrase.",
                "sources": _dedup(collected_sources), "tool_calls": tool_calls, "mode": "llm"}

    # ------------------------------------------------------------ offline path
    _ROUTES = [
        (("overview", "portfolio", "holdings", "total", "summary", "how am i", "doing"),
         "get_portfolio_overview"),
        (("owe", "upcoming", "overdue", "capital call", "obligation", "due", "pay next"),
         "get_obligations"),
        (("distribution", "exit", "received", "paid out", "realis", "carry on"),
         "get_realised_outcomes"),
        (("fee", "carry", "discount", "structuring", "admin fee", "management fee"),
         "get_fees"),
        (("valuation", "mark", "share price moved", "up or down", "down round"),
         "get_valuation_history"),
        (("statement", "cash flow", "account"),
         "get_account_statement"),
        (("position", "cost basis", "my stake", "how is", "holding in"),
         "get_position"),
    ]

    def _offline_answer(self, user_message: str) -> dict:
        q = user_message.lower()
        tool, arg = self._route_offline(q)
        ti = {"company_or_deal": arg} if arg else {}
        result = tools.dispatch(self.store, self.investor_id, tool, ti)
        text = _render_offline(tool, result["data"])
        banner = ("[offline mode -- no ANTHROPIC_API_KEY set; showing deterministic tool output, "
                  "not a personalised LLM answer]\n\n")
        return {"text": banner + text, "sources": _dedup(result.get("sources", [])),
                "tool_calls": [{"tool": tool, "input": ti}], "mode": "offline"}

    def _route_offline(self, q: str):
        # Try to extract a company name the investor actually holds.
        arg = None
        for a in self.store.allocations_for(self.investor_id).itertuples(index=False):
            name = self.store.deal_by_id[a.deal_id]["company_name"]
            if name.lower() in q or name.lower().split()[0] in q:
                arg = name
                break
        for keywords, tool in self._ROUTES:
            if any(k in q for k in keywords):
                if tool in ("get_position", "get_valuation_history") and not arg:
                    continue
                return tool, (arg if tool in ("get_position", "get_valuation_history", "get_fees") else None)
        # Default
        if arg:
            return "get_position", arg
        return "get_portfolio_overview", None


def _dedup(seq):
    seen, out = set(), []
    for s in seq:
        if s not in seen:
            seen.add(s); out.append(s)
    return out


def _render_offline(tool: str, data: dict) -> str:
    """Compact human-readable rendering of tool output for the no-LLM path."""
    return json.dumps(data, indent=2, default=str)
