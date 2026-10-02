# Dhaga Ops

Dhaga Ops helps listing operators and support agents turn supplier details and customer messages into reviewed work for their team. Choose a task, check the source facts, save a draft, and approve it when it is ready. Approval is an internal handoff; publishing and sending happen in your usual tools.

The linked Vercel project URL is [dhaga-ops.vercel.app](https://dhaga-ops.vercel.app), with Vercel Authentication and the app password. This README describes the redesigned code; final release verification is recorded separately once completed. Orders and policy examples are synthetic; no Dhaga production systems are connected.

## Start with one task

**Product listings:** Load the sample products or upload a supplier sheet. Search the review queue, filter products needing attention, and open one product at a time. Compare the supplier's original details, fix missing fields, review the listing text, then choose **Save draft** or **Approve for team**. Use **Saved approvals** to download completed work. Reuploading the identical sheet reopens its saved versions, including earlier edits and approvals.

**Customer messages:** Paste the customer's message or choose a sample, then select **Check order & prepare reply**. Review the order facts beside the editable reply. Choose **Save reply draft** to return later, or confirm your review and **Approve for team**. Missing identifiers show a request for information. Cancellation, disputed delivery, unmatched details, and unavailable tracking give a concrete follow-up step.

Save before leaving an editor. Reopen product drafts or customer messages from their saved-work section. Add **Your name (for approvals)** in the sidebar so the review record is understandable; it is a self-reported name, not individual sign-in.

## What you can do

- Upload a supplier CSV or modern Excel sheet, up to 5 MB and 500 rows, with common column names mapped automatically and unreadable rows reported separately.
- Normalize 141 listed color names to a 24-color palette. Unknown colors stay in review until a person chooses a standard color.
- Standardize common size names to XS, S, M, L, XL, and XXL.
- Draft Hinglish listing copy and flag material, care, or color claims that do not match supplier details.
- Triage English and Hinglish messages using an exact order number or a uniquely matching registered phone number. Conflicting or ambiguous identifiers need correction rather than an inferred order.
- Look up sample Delhivery, Shiprocket, and Ekart records. Show a carrier ETA only when supplied, flag an overdue ETA for follow-up, and keep missing dates visible. Transit age alone does not establish a delay.
- Review example rules. Cancellation eligibility goes to a teammate; the app does not advise doorstep refusal or invent refund dates.
- Save edits separately from approval, reopen the full saved-work list after refresh, and protect recorded approvals from stale saves and identical reuploads. A teammate's newer edit prompts you to reopen instead of silently overwriting it.
- Recheck final edited content at approval. Download drafts and approvals separately, with listing care, price, sizes, copy/highlights, source and review fields retained. CSV output preserves Unicode and treats formula-like text as text cells.
- Continue in example mode without an AI API key. Optional Gemini calls use structured Pydantic schemas and are checked before use.

## How AI is routed

The model gateway checks whether an AI call is useful before calling Gemini. Known colors, clear order requests, order lookups, date checks, policy search, and routine replies stay in Python. Gemini can suggest an unfamiliar color, interpret useful but messy supplier notes, write listing text, classify an unclear message, or help word a delayed, sensitive, or non-English customer reply. An extra AI check runs only on text Gemini wrote. Every result still needs a person's review.

This is an AI-assisted workbench, not a trained Dhaga model or an autonomous agent. It uses the Gemini API only for the selected tasks above; the rest of the workflow runs locally in the app.

## Run locally

Python 3.12 or newer is recommended.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit. Choose **Product listings** to load the example supplier batch, or choose **Customer messages** and select a sample scenario. Without a database URL, local drafts are stored in `var/dhaga_os.db` on this machine.

## Run the acceptance tests

```bash
.venv/bin/python -m unittest discover -s tests -v
```

The suite covers parsing/normalization, import recovery, missing and conflicting facts, routing, all sample carriers, ETA uncertainty, final approval checks, storage recovery, and CSV safety. The 50-row/90-second catalog and three-second local CX checks are implementation benchmarks, not targets supplied by the client brief or measured live AI latency.

On 2 October 2026, all **60 tests passed in 1.852 seconds**, including complete local UI workflows and concurrency regressions. Browser layouts were inspected at 1440px desktop and 390px phone widths, including responsive navigation and sidebar-help contrast. Independent code review found no blocking findings in the reviewed changes. The actual shared database was checked read-only: 130 listings, 8 support cases, and no duplicate approved normalized supplier codes; no stored records were rewritten and no schema migration ran. Final deployment confirmation is still pending. No cold user study, live Gemini quality benchmark, or production Dhaga integration has been tested. The corrective [discovery and PRD review](docs/product-discovery-and-prd.md) explains the evidence, ranked problems, assumptions, acceptance criteria, and proposed pilot measurements; it was written after implementation.

## Optional Gemini assistance

Gemini assistance is optional. The app makes no model calls in its default `demo` mode. To enable live calls locally, copy `.env.example` to `.env`, then set `MODEL_MODE=live` and add a Google Gemini API key as `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/api-keys). The distinct defaults are `gemini-3.5-flash-lite` for extraction, uncertain routing, and evaluation, and `gemini-3.8-flash` for listing/reply wording. Override them with `GEMINI_FAST_MODEL` and `GEMINI_CREATIVE_MODEL`. Compare quality and live latency before treating the split as validated.

In live mode, the gateway may send an unfamiliar color, a supplier's free-text product details, listing facts, or a customer message and sample order details to Gemini for the tasks listed above. It skips Gemini for routine local checks. These are bounded model requests in a Python workflow, not an autonomous agent or a model trained on Dhaga data. Deterministic checks and human approval remain in place.

Google currently lists free tiers for both configured models, with quotas and data-use conditions. Free-tier prompts and responses may improve Google's products; use synthetic examples for the demo. See [current pricing and data-use details](https://ai.google.dev/gemini-api/docs/pricing) and the explicitly illustrative [cost line](docs/build-note.md).

The gateway calls Google's Gemini API directly. `OPENROUTER_API_KEY` is not read by this code. Demo mode is the default, so the server still starts without a model key; if live mode is selected without a key, the UI explains that Gemini is unavailable. Do not put keys in source code or commit `.env`.

For Vercel, set `MODEL_MODE=live` and `GEMINI_API_KEY` in the project's encrypted Environment Variables, then redeploy. Keep the key out of GitHub and browser-side code.

## Database and deployment

Set `DATABASE_URL` to a managed PostgreSQL connection string for shared storage. The Vercel deployment requires PostgreSQL because local files do not provide durable shared storage. Configure `DHAGA_APP_PASSWORD` in the Vercel project settings; retain Vercel Authentication as a separate access gate.

The deployment configuration uses the repository's `Dockerfile.vercel`. Use the Vercel project already linked to this repository and keep both access gates enabled.

## When something needs attention

| What you see | What to do |
| --- | --- |
| Product details missing or copy fails its check | Compare the supplier source, fill the required fields, edit unsupported claims, save, and review again. |
| Unreadable supplier row | Download the row error report, correct the named row/header, and upload a corrected sheet. Other readable products remain available. |
| No unique order matches | Correct the order number or phone. Use an order number when a phone has multiple orders. |
| Tracking, cancellation, or policy needs a teammate | Use the internal follow-up note and verify the facts/policy in your usual tools. Nothing has been cancelled or assigned outside this app. |
| Saving unavailable or some drafts failed to save | Keep the editor open. Retry saving when offered or ask the app administrator to restore storage; approval requires successful storage. |
| AI unavailable | Local checks and example wording remain available. Review the fallback text and unresolved details. |

## Limits to keep in mind

- Carrier tracking uses sample JSON records, not live courier APIs.
- The four policy examples are not Dhaga-approved policy. Confirm their wording and rules with the CX owner before any pilot.
- Data in `data/` is synthetic. Replace it with authorized, client-approved test data before handling real customer information.
- “Approve” records an internal staging or agent handoff decision. It never publishes a listing or sends a customer response.
- The shared app password and self-reported reviewer name are demo controls, not verified per-person identity or role-based access.
- Live model latency and quality need measurement with the configured provider. Demo performance tests do not prove a production AI latency target.

## Project layout

```text
app.py                       Streamlit workspaces and operator screens
dhaga_os/catalog.py          Supplier parsing, normalization, copy and checks
dhaga_os/cx.py               Ticket routing, sample lookup, replies and fact checks
dhaga_os/policy_rag.py       Local policy ranking
dhaga_os/llm.py              Structured Gemini boundary
dhaga_os/db.py               SQLAlchemy tables, approval and recovery queries
dhaga_os/exports.py          Unicode CSV output and formula-like text handling
data/                        Synthetic products, orders and policies
docs/product-discovery-and-prd.md  Corrective discovery, PRD, gaps and pilot plan
docs/architecture.md         High-level design, data flow and database schema
docs/build-note.md           Model/code choices, patterns, cost and failure learning
tests/test_acceptance.py     Implementation acceptance and regression checks
Dockerfile.vercel            Vercel container entry point
```
