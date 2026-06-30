# Build Roadmap — EquiTie Relationship-Manager Bot (6 months)

From the read-only Q&A prototype to a **relationship-manager (RM) bot inside the
EquiTie iOS investor app** that does much of what a human RM does today —
proactively, safely, and with a full audit trail. Assumes ~6 months and
effectively unlimited budget; the constraint is *talent, trust and correctness*,
not money.

> **Guiding principle (carried from the prototype):** deterministic systems own
> money and numbers; the model owns language, routing and judgment under
> guardrails. The bot should feel like a great RM, but every figure, obligation
> and document action is computed/executed by audited code.

---

## 1. Scope and capabilities

**Bot does (with a human in the loop where it touches money, legal or comms):**

| Capability | Notes |
|---|---|
| **Grounded portfolio Q&A** | The prototype, hardened: positions, MOIC, fees, valuations, statements, multi-currency, multi-round. |
| **Proactive nudges** | Upcoming/overdue capital calls and fees, KYC expiry, new valuation marks, distribution notices — push notifications + in-app. |
| **Capital-call & fee workflows** | Explain, remind, and surface the pay flow; *initiating payment stays a deliberate user action*. |
| **Document & KYC requests** | Request/collect missing docs, re-KYC, track status; route to e-sign for subscription/side-letter docs. |
| **Onboarding** | Guided new-investor onboarding: profile, KYC/AML, bank details, first commitment. |
| **Reporting** | On-demand and scheduled statements/Capital-account reports; "explain my Q2 statement". |
| **Drafting investor comms** | Draft (never auto-send) RM replies, distribution notices, quarterly letters for human approval. |

**Stays with a human (assisted, not automated):** investment advice or
suitability opinions; bespoke fee/side-letter *negotiation*; anything legally
binding (signatures, fund commitments); escalations and relationship judgment;
final approval on any outbound investor communication. The bot drafts and
prepares; a person signs off.

---

## 2. Architecture and tech stack

```
 iOS app (SwiftUI)  ──►  API gateway / BFF (TypeScript)  ──►  Agent orchestrator
   chat + push                authN/Z, rate-limit              (LangGraph / Python)
        ▲                                                          │  tool calls
        │  streamed answers, citations, action cards              ▼
        └───────────────────────────────  Deterministic tool/services layer ──────┐
                                          (portfolio calc, fees, FX, obligations,   │
                                           docs, payments-init, comms-draft)        │
                                                   │                                │
   Postgres (ledger mirror) · Vector store (docs/policies) · Object store · Redis  │
                                                   │                                │
              Integrations: fund admin · CRM · KYC/AML · e-sign · comms · valuations
```

- **Client:** native **SwiftUI** chat with streaming, source-citation cards, and
  "action cards" (approve / pay / sign) that deep-link into existing app flows.
- **Backend / BFF:** **TypeScript (NestJS)** gateway owning auth, session →
  `investor_id` binding (scoping enforced server-side, as in the prototype),
  rate-limiting, and audit logging.
- **Orchestration:** **Python + LangGraph** (explicit, inspectable state machine
  over free-form agent loops — matters for auditability and guardrails).
- **Data layer:** **Postgres** as a read-replica/mirror of the portfolio ledger
  (the bot reads a governed copy, not prod fund-admin directly); **pgvector** or
  a managed vector DB for documents/policies/FAQs; **Redis** for sessions; object
  store for documents.
- **Models:** **Claude (Sonnet for routing/most turns, Opus for hard reasoning,
  Haiku for cheap classify/nudge jobs)** behind a thin provider interface; option
  for a fine-tuned small model on high-volume intents later.
- **Retrieval:** hybrid — **deterministic tools for all numbers** (the
  prototype's pattern) + **RAG** over documents, policies and prospectuses for
  qualitative questions, always cited.
- **Eval & observability:** an offline eval harness in CI (LLM-as-judge +
  golden numeric tests), plus runtime tracing (LangSmith / OpenTelemetry),
  per-answer grounding checks, and dashboards on tool-error and refusal rates.
- **Security:** SSO + per-request investor scoping, secrets in a vault,
  field-level encryption for PII, full immutable audit trail of every tool call
  and model decision, EU/UK data residency.

---

## 3. Data and integrations

| System | Role | Direction |
|---|---|---|
| **Portfolio ledger / fund admin** (e.g. internal + admin like Carta/Allvue) | positions, calls, distributions, NAV | read (mirror), reconcile nightly |
| **CRM** (e.g. Salesforce/HubSpot) | investor profile, RM ownership, interactions | read/write (log bot actions) |
| **KYC/AML** (e.g. Onfido/ComplyAdvantage) | identity, screening, re-KYC | read/write (trigger checks) |
| **E-signature** (e.g. DocuSign) | subscription docs, side letters | write (send), read (status) |
| **Comms** (email/push/secure messaging) | notices, reminders, draft replies | write (after human approval) |
| **Valuation / market data** | marks, FX | read (scheduled) |
| **Payments / banking** | capital-call settlement | initiate-only via user action; never autonomous |

Data flows through an **integration/ETL layer** that lands a governed,
versioned copy in Postgres with reconciliation jobs; the bot reads that copy so
it never depends on (or can corrupt) the system of record. Write actions go back
out through audited service calls with human approval gates.

---

## 4. AI approach and safety

- **Grounding:** numbers from deterministic tools; qualitative answers from RAG
  with citations; the model is forbidden to compute or invent figures (enforced
  by prompt **and** a post-hoc faithfulness check that every number in a reply
  traces to a tool result).
- **Tool use over free-text:** money/legal/comms actions are tool calls with
  schemas, validation and approval gates — the model proposes, code disposes.
- **Where deterministic code wins:** all financial math, FX, obligation
  detection, eligibility/compliance rules, and any state change. The model is
  used for intent, phrasing, summarisation, drafting and orchestration only.
- **Evaluation:** golden numeric tests (the prototype's suite, expanded) +
  LLM-as-judge on a labelled question bank scoring grounding, correctness,
  refusal of cross-investor/advice requests, and tone; gated in CI; canary +
  human review on new prompts/models.
- **Guardrails & compliance:** **no investment advice** (hard refusal +
  classifier), strict per-investor data isolation, PII minimisation, immutable
  audit trail, human-in-the-loop on every outbound comm and signature, and a
  regulator-friendly "show your sources" trail on every answer. Red-team for
  prompt injection (esp. via document content) before launch.

---

## 5. Team and hiring

| Role | Count | Lands | Focus |
|---|---|---|---|
| Tech lead / AI eng | 1 | M0 | architecture, guardrails, evals |
| Senior backend eng | 2 | M0–M1 | integrations, ledger mirror, services |
| Senior AI/ML eng | 1 | M1 | orchestration, RAG, eval harness |
| iOS engineer | 1 | M1 | SwiftUI chat + action cards |
| Data engineer | 1 | M2 | ETL, reconciliation, observability |
| Product designer (part-time) | 0.5 | M0 | conversation + action-card UX |
| Compliance / risk partner (embedded) | 0.5 | M0 | advice boundary, audit, data protection |
| QA / eval specialist | 1 | M3 | test banks, regression, red-team |

Peak ~7–8 FTE. Compliance and design are engaged from day one — the bot's
hardest problems are trust and correctness, not raw engineering.

---

## 6. Timeline (phased, value each phase)

- **Phase 0 — Foundations (M0–M1):** ledger mirror + reconciliation, auth &
  per-investor scoping, deterministic tool services (productionised prototype),
  eval harness in CI. *Ships:* hardened grounded Q&A behind a feature flag to
  internal users.
- **Phase 1 — In-app Q&A GA (M1–M2):** SwiftUI chat with streaming + citations,
  personalisation, observability. *Ships:* investor-facing portfolio Q&A in the
  iOS app for a pilot cohort.
- **Phase 2 — Proactivity (M2–M3):** nudges/reminders (calls, fees, KYC,
  valuations, distributions), notification preferences. *Ships:* the bot reaches
  out, not just responds.
- **Phase 3 — Workflows (M3–M5):** document/KYC requests, e-sign routing,
  capital-call explain-and-pay handoff, drafted comms with human approval.
  *Ships:* the bot does RM *work*, gated by humans.
- **Phase 4 — Onboarding + scale (M5–M6):** guided onboarding, reporting on
  demand, fine-tuned small model for high-volume intents, full red-team +
  compliance sign-off. *Ships:* GA to all investors.

---

## 7. Risks, build-vs-buy, and cost shape

**Top risks & mitigations**
- *Wrong numbers / hallucination* → deterministic compute + faithfulness checks +
  golden tests; never let the model do math. **(Highest priority.)**
- *Crossing into investment advice (regulatory)* → hard guardrail + classifier +
  compliance-owned eval set; human escalation.
- *Cross-investor data leakage* → server-side scoping, isolation tests, no PII in
  prompts beyond the logged-in investor.
- *Prompt injection via documents* → sandbox RAG content, treat doc text as
  untrusted, strip tool-trigger content.
- *Integration fragility / stale data* → governed mirror + reconciliation +
  staleness flags surfaced to the user.

**Build vs buy:** *Buy* — KYC/AML, e-sign, base LLMs, observability, push/email.
*Build* — the deterministic financial tool layer, orchestration/guardrails, the
eval harness, and the iOS experience (these are the differentiators and the
trust surface; they shouldn't be outsourced).

**Cost shape:** dominated by **people** (~7–8 senior FTE for 6 months). Infra,
model inference and third-party SaaS (KYC, e-sign, vector DB, observability) are
a comparatively small line — inference is cheap relative to the engineering and
compliance cost of being *correct*. Spend the budget on senior talent, evals,
and compliance, not on model tokens.
