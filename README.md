# EquiTie — Senior Software Engineer Case Study

A conversational AI assistant that lets an EquiTie investor ask plain-language
questions about **their own portfolio** and receive grounded, cited answers backed
by deterministic Python — not model arithmetic.

---

## Repository layout

```
.
├── codebase/          # All application code (see below)
├── data/              # 10 synthetic CSVs that back the prototype
│   ├── allocations.csv
│   ├── capital_calls.csv
│   ├── deals.csv
│   ├── distributions.csv
│   ├── fees.csv
│   ├── fx_rates.csv
│   ├── investors.csv
│   ├── portfolio_companies.csv
│   ├── statement_lines.csv
│   └── valuations.csv
└── Dataset Guide.md   # Full data-schema and edge-case reference
```

### `codebase/`

```
codebase/
├── equitie/
│   ├── data.py        # Load + index CSVs; FX conversion; investor-scoped slices
│   ├── metrics.py     # Deterministic per-investor computations (source of truth)
│   ├── tools.py       # Anthropic tool schemas + dispatch into metrics
│   ├── profile.py     # Personalisation signals + system-prompt construction
│   └── assistant.py   # Claude tool-calling loop + deterministic offline fallback
├── app.py             # Streamlit chat UI  (investor selector acts as "login")
├── cli.py             # CLI chat loop
├── tests/
│   └── test_metrics.py   # 17 verification tests covering named edge cases
├── requirements.txt
├── run.sh             # One-command bootstrap (creates venv, installs deps, runs app)
├── ai-workflow.md     # How the prototype was built with AI tooling
└── ROADMAP.md         # 6-month plan to productionise as an iOS relationship-manager bot
```

---

## Quick start

```bash
cd codebase
cp .env.example .env          # optional: add ANTHROPIC_API_KEY for live LLM mode
./run.sh                      # launches the Streamlit chat app
./run.sh cli INV001           # CLI chat as investor INV001
./run.sh test                 # run the 17-test verification suite (no API key needed)
```

`run.sh` creates a `.venv` and installs dependencies on first run. Manual
equivalent:

```bash
python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt
./.venv/bin/streamlit run app.py
```

**No API key?** The assistant runs in **offline / deterministic mode**: the data
and metrics layer answers directly, returning structured tool output instead of a
polished LLM reply. Add `ANTHROPIC_API_KEY` to `.env` for the full conversational
experience.

---

## Core design

> **Deterministic code owns the numbers; the LLM owns the language.**

```
 user question
      │
      ▼
┌─────────────┐   picks a tool      ┌──────────────────────────────┐
│   Claude    │ ──────────────────► │  deterministic tools          │
│ (orchestr.) │                     │  (metrics.py over pandas)     │
│             │ ◄────────────────── │  returns { data, sources }    │
└─────────────┘   numbers + rows    └──────────────────────────────┘
      │
      ▼  grounded, personalised answer + "Source:" citation line
```

- **Data layer (`data.py`)** — loads the 10 CSVs into pandas and exposes
  investor-scoped slices. The `investor_id` is injected by the app and never
  chosen by the model, making cross-investor access structurally impossible.
- **Metrics layer (`metrics.py`)** — computes every figure (MOIC, current value,
  FX, fees, obligations, statement) and returns `{ data, sources }`.
- **Tool layer (`tools.py`)** — eight Anthropic-schema tools, each mapping 1:1 to
  a `metrics.py` function. Data is always FX-converted to the investor's
  reporting currency before it leaves this layer.
- **Assistant (`assistant.py`)** — runs the Claude tool-calling loop; falls back
  to raw tool output when no API key is present.
- **Front-ends (`app.py`, `cli.py`)** — thin wrappers; no business logic.

### The eight tools

| Tool                     | What it answers                                         |
| ------------------------ | ------------------------------------------------------- |
| `get_portfolio_overview` | All positions, total value, aggregate MOIC              |
| `get_position`           | Single deal: value, MOIC, cost basis, valuation history |
| `get_obligations`        | Upcoming / overdue capital calls and fees               |
| `get_realised_outcomes`  | Exits and write-offs with distributions and carry       |
| `get_fees`               | Fee breakdown by deal, with discount flags              |
| `get_valuation_history`  | Mark timeline for a company or deal                     |
| `get_account_statement`  | Transaction-level statement with running balance        |
| `get_investor_profile`   | KYC status, reporting currency, personalisation signals |

---

## Dataset

112 investors · 16 portfolio companies · 21 deals · 550 allocations · 55 valuations  
655 capital calls · 1,401 fee rows · 34 distributions · 1,390 statement lines · 4 FX rates

All data is **synthetic**. Report date is fixed at **2026-06-25** ("today" for
any upcoming / current figure). See [Dataset Guide.md](Dataset%20Guide.md) for
full schema documentation and edge-case notes.

---

## Dependencies

| Package                | Purpose                      |
| ---------------------- | ---------------------------- |
| `pandas >= 2.0`        | Data loading and computation |
| `anthropic >= 0.40`    | Claude API + tool-calling    |
| `streamlit >= 1.30`    | Chat UI                      |
| `python-dotenv >= 1.0` | `.env` configuration         |
| `pytest >= 7.0`        | Test suite                   |

Python 3.9+ required.

---

## Testing

```bash
./run.sh test
# or, inside an active venv:
pytest tests/ -v
```

17 tests cover the named edge cases in the Dataset Guide: multi-round
aggregation, fee discounts, multi-currency FX symmetry, pending/unfunded
allocations, zero-holding investors, exits (with carry), write-offs, down rounds,
partial secondaries, and statement integrity. All tests run offline with no API
key.

---

## Further reading

- [codebase/ai-workflow.md](codebase/ai-workflow.md) — how the prototype was
  built with AI tooling, what was rejected, and how correctness was verified.
- [codebase/ROADMAP.md](codebase/ROADMAP.md) — 6-month plan to evolve this into
  a production relationship-manager bot inside the EquiTie iOS app.
