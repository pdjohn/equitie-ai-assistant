# EquiTie Mock Dataset — Data Schema & Edge Case Guide

This dataset backs the Senior Software Engineer case study. It models a simplified version of the EquiTie investor platform: investors make commitments to deals (SPVs), each deal invests in one round of one portfolio company, and the platform tracks allocations, capital contributions, management fees, valuations, distributions and an account statement.

**All data is synthetic. Every investor name, company name, and deal is fictional and invented for this exercise; any resemblance to a real person or company is coincidental.** Report date is **2026-06-25** (treat this as "today" for any "upcoming" / "current" figure).

---

## Entity relationship overview

```
portfolio_companies (1) ──< deals (1) ──< allocations >── (1) investors
                                 │                 │
                                 ├──< valuations   ├──< capital_calls
                                 │                 ├──< fees
                                 │                 └──< distributions
fx_rates  (currency reference)   └──────────────────────< statement_lines >── investors
```

Key relationships:

- One **company** can have **many deals** (one per funding round). This is the single most important modelling point — see edge cases.
- One **deal** has **many allocations** (one per investor in that SPV).
- An **allocation** is the grain at which capital contributions, fees and distributions hang.
- **valuations** is a time series of marks per deal; the latest mark drives current value and MOIC.
- **statement_lines** is a per-investor account statement derived from paid contributions, paid fees and distributions.

**Row counts:** 112 investors · 16 companies · 21 deals · 55 valuations · 550 allocations · 655 capital calls · 1,401 fee rows · 34 distributions · 1,390 statement lines · 4 FX rates.

**Fee model (important):** fees are **not** an investor-level class. Each **deal** carries a *standard* fee schedule that everyone in that deal pays by default — a management fee %, a performance fee % (carry), a structuring fee %, and a flat admin fee in USD — and these standards **vary by deal**. **Discounts are negotiated per allocation** (deal-by-deal): they only ever reduce a fee below the deal standard, and they skew toward loyal / repeat investors but not deterministically (some loyal LPs pay full freight; some newcomers get a break). Each allocation therefore stores its own *effective* rates alongside a `fee_discount` flag, which you compare to the deal's standard.

**Realistic shape (intentional):**

- Investors (112) ≫ deals (21); allocations (550) ≫ investors ≫ deals (≈ 4.9 allocations per investor, ≈ 26 per deal).
- **No anchors.** Investors participate in 1–12 deals (most in 1–4); none dominates. **Two** investors are onboarded but hold nothing yet; **one** has a pending/unfunded commitment.
- Each deal has **9–67 investors**, depending on round and size.
- **Ticket sizes:** floor ~10k, median ~44k, mean ~80k; most are ≤250k, with **0–2 large tickets of 500k–1m per deal** (each capped at ~55% of the round so no single LP dominates).
- **Deal sizes:** average ~2m, range ~0.6m–5m.
- For every deal, the sum of investor commitments equals the SPV's allocation in that round (`equitie_allocation_m`).

---

## Tables

### `portfolio_companies.csv` (16 rows)
| column | notes |
|---|---|
| company_id | PK, e.g. `CO001` |
| company_name | display name |
| sector | e.g. Robotics / Automation |
| hq_country | |
| status | `Active` / `Exited` / `Written Off` |
| website | dummy domain |

### `deals.csv` (21 rows)
One row per company-round SPV.
| column | notes |
|---|---|
| deal_id | PK, e.g. `DEAL001` |
| company_id | FK → portfolio_companies |
| company_name | denormalised for convenience |
| round | Seed / Series A / Series B |
| instrument | Equity / SAFE |
| spv_name | the legal vehicle investors hold |
| deal_currency | USD / GBP / EUR / AED — **the deal is denominated in this, not the investor's currency** |
| deal_date | |
| pre_money_valuation_m / post_money_valuation_m / round_size_m | in millions, deal currency |
| equitie_allocation_m | EquiTie's allocation in the round = sum of investor commitments |
| entry_share_price | share price EquiTie's SPV paid at entry |
| contributed_pct | **deal-level** % of commitments called/contributed so far (100 unless a partial call is in progress) |
| std_mgmt_fee_pct | **standard** management fee for this deal (varies: 1.5 / 2.0 / 2.5) |
| std_performance_fee_pct | **standard** performance fee / carry for this deal (15 / 20 / 25) |
| std_structuring_fee_pct | **standard** one-time structuring fee for this deal (3 / 4 / 5) |
| std_admin_fee_usd | **standard** flat admin fee, in USD (450) |
| status | mirrors company status for that round |

### `valuations.csv` (55 rows)
Time series of marks per deal. **Current value uses the latest `valuation_date` for that deal.** Companies move up *and* down here.
| column | notes |
|---|---|
| valuation_id | PK |
| deal_id | FK → deals |
| valuation_date | |
| share_price | marked share price on that date |
| company_valuation_m | implied company valuation at that mark, in millions, deal currency |
| mark_source | `Entry` / `Internal` / `Markup Round` / `Exit` / `Write Off` |
| multiple_vs_entry | share_price ÷ entry_share_price (>1 uplift, <1 markdown, 0 write-off) |

### `investors.csv` (112 rows)
| column | notes |
|---|---|
| investor_id | PK, e.g. `INV001` |
| investor_name | |
| investor_type | Individual / Entity |
| country | |
| reporting_currency | **the currency the investor wants to see** — often ≠ deal_currency |
| age | investor age (blank for entities) — *profile field for personalisation* |
| tech_savviness | `Low` / `Medium` / `High` — *profile field for personalisation* |
| kyc_status | Verified / Pending |
| onboarded_date | |
| email | |

Two further profile signals are **derivable**, not stored: how many deals an investor is in (count their allocations) and the sectors they invest in most (join allocations → deals → companies.sector). The assistant is expected to compute these.

### `allocations.csv` (550 rows)
The core fact table — one investor's position in one deal.
| column | notes |
|---|---|
| allocation_id | PK, e.g. `ALC0001` |
| deal_id | FK → deals |
| investor_id | FK → investors |
| deal_currency | |
| commitment_amount | total commitment, deal currency |
| price_discount_pct | **per-investor** discount off the entry share price (early-bird / side letter) |
| effective_share_price | entry_share_price × (1 − discount) — drives this investor's cost basis & unit count |
| units | commitment_amount ÷ effective_share_price |
| contributed_amount | capital contributed so far = commitment × deal `contributed_pct` (0 for Pending) |
| outstanding_commitment | commitment − contributed |
| mgmt_fee_pct | this investor's **effective** management fee on this deal (≤ deal standard) |
| performance_fee_pct | this investor's **effective** performance fee / carry on this deal (≤ deal standard) |
| structuring_fee_pct | this investor's **effective** structuring fee on this deal (≤ deal standard) |
| admin_fee_usd | this investor's **effective** flat admin fee, USD (0 if waived) |
| fee_discount | `Yes` if any effective fee is below the deal standard, else `No` |
| allocation_status | `Active` / `Pending` (pending = signed but unfunded) |
| allocation_date | |

### `capital_calls.csv` (655 rows)
Each row is a call against an allocation; a paid call becomes a capital contribution.
| column | notes |
|---|---|
| call_id | PK |
| allocation_id, investor_id, deal_id | FKs |
| call_number | 1 or 2 (tranches) |
| call_date / due_date | |
| amount / currency | deal currency |
| status | `Paid` / `Upcoming` |

### `fees.csv` (1,401 rows)
One row per fee charged to an allocation. Three fee types, each at the allocation's **effective** rate:
| column | notes |
|---|---|
| fee_id | PK |
| allocation_id, investor_id, deal_id | FKs |
| fee_type | `Management Fee` (annual), `Structuring Fee` (one-time at close), or `Admin Fee` (annual flat) |
| period | year — `2026` for management/admin; the deal's close year for structuring |
| fee_rate_pct | effective % for mgmt/structuring; blank for the flat admin fee |
| basis | `Commitment` (mgmt, structuring) or `Flat` (admin) |
| amount / currency | deal currency for mgmt & structuring; **USD** for the admin fee (even on non-USD deals) |
| due_date | |
| status | `Paid` / `Upcoming` / `Overdue` |

Notes: management & admin fees only accrue on **active** deals (exited/written-off deals stop accruing); structuring fees exist for all deals (charged historically at close). A fully-waived fee (effective 0) produces no row — don't assume every allocation has every fee.

### `distributions.csv` (34 rows)
| column | notes |
|---|---|
| distribution_id | PK |
| deal_id, allocation_id, investor_id | FKs |
| distribution_date | |
| distribution_type | `Exit Proceeds` / `Secondary Sale` |
| gross_amount | before performance fee |
| performance_fee_pct | the investor's carry rate |
| performance_fee_amount | carried interest withheld |
| net_amount | what the investor received |
| currency | deal currency |
| fraction_of_units | share of the position realised (1.0 = full exit) |

### `statement_lines.csv` (1,390 rows)
Per-investor account statement. Negative = cash out by investor (contributions, fees), positive = cash in (distributions, net of performance fee).
| column | notes |
|---|---|
| line_id | PK |
| investor_id | FK |
| date | |
| type | Capital Contribution / Management Fee / Structuring Fee / Admin Fee / Exit Proceeds / Secondary Sale |
| deal_id | FK |
| amount | **signed**, in `currency` (deal currency, NOT reporting currency) |
| currency | |
| reference_id | points back to the call/fee/distribution row |

### `fx_rates.csv` (4 rows)
| column | notes |
|---|---|
| currency | USD / GBP / EUR / AED |
| to_usd | 1 unit of currency = this many USD, as of report date |
| as_of | 2026-06-25 |

To convert between two non-USD currencies, go via USD.

---

## Deliberate edge cases ("the traps")

1. **Same company, multiple rounds.** Forgecraft Robotics has **three** deals (Seed, Series A, Series B); Inferna AI, Pulsegrid Health and Qubrium each have two. "My position in Forgecraft" must aggregate across rounds, each with its own share price, mark and contribution status.

2. **Per-investor share-price discounts.** In the same deal investors hold different `effective_share_price` and therefore different unit counts and cost bases (e.g. Idris Olawale & Selina Voss got 10% off Forgecraft Seed; early SAFE investors got 15% off Inferna Seed). Cost basis is per-allocation, never per-deal.

3. **Multi-currency.** Deals are in USD/GBP/EUR/AED; investors report in their own currency. Every value/fee/cashflow must be FX-converted before it can be summed.

4. **Commitment vs contributed.** Forgecraft Series B (60% contributed) and Pulsegrid Health Series B (50%) have outstanding commitments and an **upcoming** second capital call. The contribution % is deal-level. "How much have I invested?" is ambiguous: commitment ≠ contributed.

5. **Pending / unfunded commitment.** Grace Okafor (KYC Pending) has a Helixar Bio allocation with 0% contributed — not deployed capital.

6. **Newly-onboarded, zero holdings.** Henrik Sorensen and Lara Greco hold no allocations — a "you have no investments yet" case.

7. **Exit.** Helianthe Energy returned 1.5× via Exit Proceeds; current holding value is 0 but realised distributions (net of performance fee) exist. MOIC must include distributions.

8. **Write-off.** Yappio is marked to 0 (its valuation series declines then writes off). Affected investors show a loss.

9. **Down round.** Qubrium Series B current mark (6.2) is **below** entry (10.0); the earlier Series A rose to 10.0 then was marked down to 6.2. Same company, both directions visible in `valuations.csv`.

10. **Deal-standard fees vs per-allocation discounts.** Every deal has a standard schedule (e.g. 2% mgmt / 20% performance / 4% structuring / 450 USD admin), but standards vary by deal and many investors negotiated a discount on *their* allocation — a lower management fee, reduced carry, cut structuring fee, or waived admin. To answer "what fees am I paying?" you must read the allocation's effective rates, not the deal standard. Discounts skew to loyal/repeat investors but not always.

11. **Performance fee on distributions.** Net = gross − performance fee, at the **allocation's** effective rate (which may be discounted below the deal standard). Some fees are Paid, some Upcoming, some **Overdue**; the admin fee is billed in USD even on non-USD deals.

12. **Similar names.** `Northpeak Analytics` and `Northpeak Health` are different companies in different sectors and currencies — a disambiguation test.

13. **Partial secondary.** Tallybook sold 30% of units in a secondary at 2.4×; the remaining 70% is still marked live. Realised proceeds and unrealised value coexist on one allocation.

---

## Useful derived metrics

- **Current value (per allocation)** = `units × latest share_price`, minus realised fraction, FX-converted. Zero if exited/written off.
- **MOIC** = (current value + distributions net of performance fee) ÷ capital contributed.
- **Effective fees** for an allocation come from the allocation row (mgmt/performance/structuring/admin); compare to the deal's `std_*` columns to see the discount.
- **DPI** = distributions ÷ contributed; **RVPI** = current value ÷ contributed.
- **Total portfolio value** = Σ current values across allocations, all converted to reporting currency.
- **Upcoming obligations** = capital_calls + fees (Management/Admin) with a future `due_date` and status Upcoming/Overdue.
- **Personalisation signals** = age, tech_savviness, number of deals (count allocations), and top sectors (allocations → deals → company sector).
