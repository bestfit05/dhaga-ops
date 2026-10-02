# Dhaga Ops build note

## Code and model boundary

| Workflow step | Implementation | Reason |
|---|---|---|
| CSV/XLSX parsing and header aliases | Python / pandas | Deterministic file handling and row-level errors |
| Known color spelling normalization | Python dictionary | Exact mapping to the 24-color master palette |
| Unknown shade suggestion | Gemini fast model in live mode | Regional color terms need semantic interpretation; suggestion remains unconfirmed |
| Missing attributes in useful free text | Gemini fast model when fields are missing | Skip calls when source values are already clear |
| Occasion-led Hinglish copy | Gemini creative model in live mode | Language and audience adaptation require generation |
| Copy factuality review | Gemini fast model plus deterministic fabric/care term check | Evaluator step can reject claims that conflict with vendor source |
| Message intent and identifiers | Rules/regex; Gemini for unclear intent | Literal identifiers remain authoritative |
| Carrier lookup and ETA checks | Python over mock JSON records | Exact/unique identifier matching; active shipment is overdue only after a supplied ETA passes |
| Policy retrieval | Local term-vector cosine similarity | Four example rules need no embedding service |
| CX reply drafting | Local routine template; optional Gemini for supported sensitive/multilingual replies | Cancellation/dispute requires a teammate; unknown policies are not invented |
| Reply fact check | Deterministic comparison always; Gemini only for Gemini-written text | Check known identifiers, dates, courier, link, status/location and unsupported promises |
| Approval and exports | Python + SQLAlchemy | Recheck final edits in the transaction, protect approvals, record content hashes, export safe Unicode CSV |

The gateway checks task need before calling Gemini. Catalog generation uses only source-shaped fields; routine CX lookup/replies remain local. Demo mode uses templates and makes no model calls. Human source review remains required.

## Patterns and operator workflow

**Routing** keeps clear work local and sends unsupported requests to a teammate. Without it, routine work incurs calls and cancellation can get unsafe generic wording. **Prompt chaining** passes standardized facts into copy and evaluation; otherwise writer and reviewer lack a consistent source. Evaluation is one check, not an autonomous repair loop.

The UI provides a searchable product queue and reply/facts panels. Full saved-work lists and complete listing exports retain previous work. Drafts save separately from approval. Exact reuploads recover saved work; revision tokens/conditional writes and row/SKU locks prevent stale or conflicting writes. Approval rechecks final text and records the self-reported reviewer.

## Model configuration

- Distinct defaults: `gemini-3.5-flash-lite` for extraction/routing/evaluation; `gemini-3.8-flash` for wording. Reserve richer language work for Flash; validate the split with measured quality/latency.
- Temperatures: extraction/classification 0.0; color suggestion/evaluation 0.1; CX wording 0.4; listing copy 0.7. All boundaries use JSON Schema and Pydantic; missing audit results do not count as a pass.
- Both have published free tiers on 2 October 2026; quotas/data-use terms apply. [Official models](https://ai.google.dev/gemini-api/docs/models), [pricing.](https://ai.google.dev/gemini-api/docs/pricing)

## Cost line for planning

**Rules-only model cost: $0.** Hosting/storage/review are separate. Live usage, cost, latency, and quality remain unmeasured.

Illustrative paid scenario: assume the total tokens below, no retries, and output including billed thinking. Standard prices per million tokens: Lite $0.30 input/$2.50 output; Flash $0.75/$3.75 through 31 December 2026, higher in 2027. [Google pricing, checked 2 October 2026.](https://ai.google.dev/gemini-api/docs/pricing)

| Run | Assumed total tokens per run | Illustrative cost/run | Assumed weekly runs | Illustrative weekly cost |
|---|---|---:|---:|---:|
| One AI-assisted description | Lite: 425 in + 90 out; Flash: 250 in + 150 out | $0.0011025 | 200 descriptions | $0.22 |
| One AI-assisted WISMO ticket | Lite: 850 in + 180 out; Flash: 800 in + 150 out | $0.0018675 | 5,220 tickets | $9.75 |
| **Illustrative combined** | Every listed run uses AI | — | — | **$9.97** |

Formula: `(Lite in × 0.30 + Lite out × 2.50 + Flash in × 0.75 + Flash out × 3.75) / 1,000,000`. Addressable WISMO is `9,000 × 58% = 5,220/week`. The brief separately reports 200 descriptions and 400 new SKUs; generating all 400 would give ~$10.19/week combined. Actual eligibility/calls, batch overhead, unknown-color calls, retries, taxes, hosting, and FX differ. Replace assumptions with provider usage before committing a target.

## Failure learning and validation limits

The demo labeled every shipment older than four days delayed and suggested COD doorstep refusal. The brief gives normal four-to-seven-day delivery and no refusal rule. Corrected behavior uses overdue ETA, missing-date uncertainty, and manual cancellation. Valid JSON did not catch the policy error.

The gateway returned `None` for local work while a caller read it as a model result; that fallback contract is fixed. Final approval rechecks edited content. All 60 local tests passed in 1.852s, including UI/concurrency regressions. Desktop/phone layouts were inspected. Local timing checks are implementation benchmarks; deployment confirmation remains pending.

## MVP limits

No production integration, cold user study, or accessibility audit was tested. Policies/data are synthetic; reviewer identity is self-reported. The [discovery/PRD review](product-discovery-and-prd.md) was written after implementation. Approved policy, real-data controls, metering, and owner-led pilots remain prerequisites.
