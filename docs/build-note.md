# Dhaga Ops build note

## Code and model boundary

| Workflow step | Implementation | Reason |
|---|---|---|
| CSV/XLSX parsing and header aliases | Python / pandas | Deterministic file handling and row-level errors |
| Known color spelling normalization | Python dictionary | Exact mapping to the 24-color master palette |
| Unknown shade suggestion | Gemini fast model in live mode | Regional color terms need semantic interpretation; suggestion remains unconfirmed |
| Fabric, silhouette, care, and occasion normalization | Gemini fast model in live mode | Converts messy source-shaped fields into structured attributes |
| Occasion-led Hinglish copy | Gemini creative model in live mode | Language and audience adaptation require generation |
| Copy factuality review | Gemini fast model plus deterministic fabric/care term check | Evaluator step can reject claims that conflict with vendor source |
| Hinglish intent and identifier parsing | Regex first, Gemini fast model when enabled | Identifier matching remains exact; model handles varied phrasing |
| Carrier lookup, transit days, delay flag | Python over mock JSON records | Lookup and date arithmetic are deterministic |
| Policy retrieval | Local term-vector cosine similarity | Tiny policy set; no embedding service or vector database is needed for the demo |
| CX reply drafting | Gemini creative model in live mode | Produces concise customer-facing language grounded in known facts |
| Carrier/date audit | Gemini fast model plus deterministic comparison | Conflicting dates/carriers remain blocked for human review |
| Approval and exports | Python + SQLAlchemy | Staging actions and audit events are inspectable and repeatable |

The prompt chain is normalization → copy → audit for catalog rows. CX routing precedes exact carrier lookup, policy retrieval, reply drafting, and factual audit. These stages are separate so the system can stop on missing data, sync failures, or factual mismatches instead of sending an unsupported answer. Demo mode replaces all model calls with transparent local rules and template drafts.

## Model configuration

- Fast: `gemini-3.1-flash-lite` for extraction, routing, color suggestions, and evaluation at temperature 0.0–0.1.
- Creative: `gemini-3.1-pro-preview` for listing copy at 0.7 and CX replies at 0.4.
- The response schema is validated with Pydantic after each model boundary. Model IDs are configurable because availability and pricing change.

## Cost line for planning

This is a planning estimate for the standard paid tier, not a measured bill. It uses assumed token counts because no provider key or real model usage is configured yet. The estimate uses the current listed rates of $0.25 per million fast-model input tokens and $1.50 per million fast-model output tokens, plus $2 per million Pro input tokens and $12 per million Pro output tokens for prompts up to 200k tokens. The provider may count reasoning tokens as output. See [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing).

| Run | Assumed tokens per run | Estimated cost / run | Dhaga volume | Estimated weekly model cost |
|---|---|---:|---:|---:|
| One catalog SKU | Fast: 425 input + 90 output; Pro: 250 input + 150 output | $0.00254 | 400 SKUs / week | $1.02 |
| One WISMO ticket | Fast: 850 input + 180 output; Pro: 800 input + 150 output | $0.00388 | 5,220 tickets / week | $20.27 |
| **Combined** | Assumptions above | — | — | **$21.29 / week** |

Formula: `(fast input × $0.25 + fast output × $1.50 + Pro input × $2 + Pro output × $12) / 1,000,000`. The workload uses two fast-model calls and one Pro call per CX ticket. A catalog batch groups model calls across rows, so the per-SKU estimate amortizes the shared prompt overhead. Unknown-color suggestions, retries, model thinking tokens beyond the assumed outputs, taxes, Vercel, PostgreSQL, and FX conversion are excluded. Replace these assumptions with the usage metadata from real runs before presenting a committed cost target.

## MVP limits

The case brief asks for a small honest build. This repo makes no claim of production Freshdesk, Gupshup, Unicommerce, or courier integration. The PRD's sample RICE scores and baseline numbers are product context, not app telemetry. Real policy snippets, access control, data retention, migration history, provider usage logging, deployment URL, and acceptance measurements still need owner review before a client pilot.
