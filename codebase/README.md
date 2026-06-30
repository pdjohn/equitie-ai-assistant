# EquiTie Investor Assistant — Prototype

A conversational assistant that answers an EquiTie investor's questions about
**their own** portfolio, in plain language, with **correct numbers** and
**citations to the source rows**. Personalised to the individual investor.

Built for the Senior Software Engineer case study. Report date is fixed at
**2026-06-25** ("today" for anything upcoming/current).

---

## TL;DR — how to run

```bash
cd codebase
cp .env.example .env          # optional: paste an ANTHROPIC_API_KEY for the LLM
./run.sh                      # launches the Streamlit chat app
# or:
./run.sh cli INV001           # CLI chat as a given investor
./run.sh test                 # run the verification suite (17 tests, no key needed)
```

`run.sh` creates a virtualenv and installs deps on first run. Manual equivalent:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/streamlit run app.py
```

**No API key?** Everything still runs in **offline mode**: the deterministic
data/metrics layer answers, returning raw tool output instead of a polished LLM
reply. Add `ANTHROPIC_API_KEY` to `.env` to get the personalised conversational
experience.

---

## The core design idea

> **Deterministic code owns the numbers; the LLM owns the language.**

The brief rewards grounded answers, citations, and "where deterministic code
does the work instead of the model." So the model **never does arithmetic**. It
is a router and a writer:

```
 user question
      │
      ▼
┌─────────────┐   picks a tool      ┌──────────────────────────┐
│   Claude    │ ──────────────────► │  deterministic tools      │
│ (orchestr.) │                     │  (metrics.py over pandas) │
│             │ ◄────────────────── │  returns {data, sources}  │
└─────────────┘   numbers + rows    └──────────────────────────┘
      │
      ▼  grounded, personalised answer + "Source:" line
```

* **Input** → the logged-in `investor_id` (stands in for auth) + the question.
* **Data & retrieval** → `data.py` loads the 10 CSVs into pandas and exposes
  **investor-scoped** slices. `metrics.py` computes every figure (MOIC, current
  value, FX, fees, obligations, statement) and returns `{data, sources}`.
* **Model reasoning** → Claude calls the right tool(s) via tool-calling, then
  writes the answer. The `investor_id` is **injected by the app, never chosen by
  the model**, so cross-investor access is structurally impossible.
* **Output** → a personalised reply that cites the dataset rows it used.

### Why this separation
- **Reliability:** numbers are unit-tested Python, not model guesses.
- **Security:** the only data the model can reach is one investor's, by
  construction (`metrics.py` filters on `investor_id` at the single choke point
  in `data.py`).
- **Explainability:** every tool emits `sources` (e.g. `allocations.csv:ALC0001`,
  `valuations.csv:VAL003`) which the model surfaces as citations.

---

## Architecture / repo layout

```
codebase/
├── equitie/
│   ├── data.py        # load + index CSVs; FX; investor-scoped slices; REPORT_DATE
│   ├── metrics.py     # deterministic per-investor computations  ← source of truth
│   ├── tools.py       # Anthropic tool schemas + dispatch into metrics
│   ├── profile.py     # personalisation signals + system prompt (scoping + grounding)
│   └── assistant.py   # Claude tool-calling loop  (+ deterministic offline fallback)
├── app.py             # Streamlit chat UI (investor selector = "login")
├── cli.py             # CLI chat loop
├── tests/test_metrics.py  # 17 verification tests over the named edge cases
├── requirements.txt · .env.example · run.sh
```

### The eight tools the model can call
`get_portfolio_overview` · `get_position` · `get_obligations` ·
`get_realised_outcomes` · `get_fees` · `get_valuation_history` ·
`get_account_statement` · `get_investor_profile`

Each maps 1:1 to a function in `metrics.py` and returns data **already
FX-converted to the investor's reporting currency**, plus its source rows.

---

## Which AI models / APIs and why

| Layer | Choice | Why |
|---|---|---|
| Orchestration + phrasing | **Anthropic Claude** (`claude-sonnet-5` default; `claude-opus-4-8` configurable) | Strong, reliable tool-calling and good instruction-following for the "don't do math, cite sources, adapt tone" constraints. Sonnet is the cost/latency sweet spot for routing + short answers; Opus is a drop-in for harder reasoning. |
| Numbers | **No model — plain Python/pandas** | Determinism and testability. FX, MOIC, fee discounts and multi-round aggregation are exact, not approximated. |

Model is set via `ANTHROPIC_MODEL`. Swapping providers means re-implementing
only `assistant.py` (the tool schemas are standard JSON-Schema).

---

## Personalisation

Tone, depth and framing adapt to the investor; **the numbers stay identical for
everyone**. Signals used (`profile.py`):

- **Stored:** `age`, `tech_savviness`, reporting currency, KYC.
- **Derived:** number of deals (count of allocations) and top sectors
  (allocations → deals → company sector).

Three styles: **Sophisticated** (High tech-savviness + ≥4 deals → concise,
data-dense, no jargon defined), **Less technical** (Low savviness or age ≥ 65 →
plain language, jargon explained, shorter), **Balanced** (default). The
assistant also reflects portfolio shape (e.g. top sector / concentration) where
useful. It is instructed to stay professional and never patronising.

---

## Assumptions made

- **"Logged-in" investor** = the selected `investor_id`. No real auth is built
  (the brief says not to); the selector/flag substitutes for a session identity.
- **Pending / unfunded allocations** (e.g. Grace Okafor's Helixar Bio) are **not
  counted as deployed capital**: excluded from current value and from MOIC
  (denominator would be 0 → MOIC reported as "undefined"), and surfaced
  separately as a *pending commitment*. This is the investor-honest reading of
  "not deployed capital."
- **Current value** = `live_units × latest share price`, where
  `live_units = units × (1 − realised fraction)`; **0** for Written-Off
  companies and for fully-realised positions. Latest = max `valuation_date`.
- **MOIC** = `(current value + distributions net of carry) ÷ contributed`.
  Denominator is **contributed** (cash actually paid in), not committed.
- **Obligations** = capital calls with status `Upcoming`, plus Management/Admin
  fees with status `Upcoming`/`Overdue`. Structuring fees are historical (at
  close) and excluded from "what's coming up". Admin fees are billed in USD even
  on non-USD deals (converted to reporting currency for display).
- **Cost basis** is per-allocation (per round), never per-deal, because
  share-price discounts differ by investor and round.
- FX uses `fx_rates.csv` as of the report date; cross-rates go via USD.

---

## How answers are verified

- **17 deterministic tests** (`./run.sh test`) assert the named edge cases:
  multi-round aggregation, per-investor share/fee discounts, multi-currency
  (FX symmetry), pending/unfunded, zero-holding, exit (carry + MOIC),
  write-off (value 0, loss), down round, partial secondary, fee-discount flag
  consistency, obligations vs report date, and statement reconciliation
  (statement contributions == paid capital calls; sign convention).
- **Internal consistency:** aggregate position value equals the sum of its
  rounds; A→B→A FX round-trips to the original.
- **Grounding at runtime:** every numeric answer ends with a `Source:` line of
  dataset rows, so a reviewer can trace any figure back to a CSV row.

Run them: `./run.sh test` → `17 passed`.

---

## Known limitations / failure modes

- **Entity resolution is keyword/substring** (e.g. "Forgecraft", "Qubrium
  Series B"). It correctly distinguishes the deliberate near-duplicate
  *Northpeak Analytics* vs *Northpeak Health*, but an obscure paraphrase may
  miss; the tool then returns the investor's available company list rather than
  guessing.
- **Offline mode is not conversational** — it returns structured tool output
  (clearly labelled), so the data layer is demonstrable without a key, but tone
  personalisation needs the LLM.
- **No multi-investor / portfolio-manager view** — single-investor by design.
- **Read-only snapshot** — no write-backs, no live valuation feed; everything is
  the static report-date dataset.
- **LLM phrasing risk** — the model could still mis-summarise correct numbers.
  Mitigations: numbers come pre-computed in the tool payload, the system prompt
  forbids invented figures, and citations let a reader verify. A production
  build would add an output check that every figure in the reply appears in a
  tool result (see `ai-workflow.md` → next 8 hours).

See also `ai-workflow.md` (AI tooling + verification) and `ROADMAP.md`
(six-month plan for the full relationship-manager bot).
