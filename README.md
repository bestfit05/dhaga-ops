# Dhaga Ops

Dhaga Ops is a small operator app for preparing product listings and customer support replies. A person reviews every listing and reply. The app does not publish products, send customer messages, or change courier bookings.

The current Vercel deployment is [dhaga-ops.vercel.app](https://dhaga-ops.vercel.app). It is protected by Vercel Authentication and the app password. Sample orders, products, and policy text are synthetic examples; no Dhaga production systems are connected.

## What you can do

- Upload a supplier CSV or Excel sheet and map common column names.
- Normalize 141 listed color names to a 24-color palette. Unknown colors stay in review until a person chooses a standard color.
- Standardize common size names to XS, S, M, L, XL, and XXL.
- Draft Hinglish listing copy and flag material, care, or color claims that do not match supplier details.
- Triage English and Hinglish messages using an order number or registered phone number.
- Look up sample Delhivery, Shiprocket, and Ekart records, show a verified date and tracking link, and flag delayed or disputed deliveries for an agent.
- Review a small local policy library and approve an internal agent handoff.
- Save drafts to a database and reopen them after a page refresh. Download approved listings and handoffs as CSV.
- Continue in example mode without an AI API key. Optional Gemini calls use structured Pydantic schemas and are checked before use.

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

The suite covers color and size normalization, the 50-row processing target, malformed CSV rows, missing listing fields, unsupported fabric claims, Hinglish routing, phone lookup, all sample carriers, missing dates, date mismatches, and approval rules.

## Optional Gemini assistance

Gemini assistance is optional. The app makes no model calls in its default `demo` mode. To enable live calls locally, copy `.env.example` to `.env`, then set `MODEL_MODE=live` and add a Google Gemini API key as `GEMINI_API_KEY` from [Google AI Studio](https://aistudio.google.com/api-keys). The free-demo defaults use `gemini-3.1-flash-lite` for extraction, copy drafting, and checks; free-tier quotas and rate limits apply.

Live assistance is used for unfamiliar color suggestions, product-attribute normalization, listing copy and its audit, customer-message intent parsing, reply drafting, and the reply audit. These are bounded model requests in a Python workflow, not an autonomous agent or a model trained on Dhaga data. Deterministic checks and human approval remain in place.

The Gemini free tier may use submitted prompts and responses to improve Google products. Live prompts can include uploaded supplier fields or customer-message text and identifiers, so use only the synthetic examples for a free-tier demo. Paid Gemini API service has different data-use terms. See [Gemini pricing and data-use details](https://ai.google.dev/gemini-api/docs/pricing).

This project calls Google's Gemini API directly. `OPENROUTER_API_KEY` is not read by this code. Demo mode is the default, so the server still starts without a model key; if live mode is selected without a key, the UI explains that Gemini is unavailable. Do not put keys in source code or commit `.env`.

For Vercel, set `MODEL_MODE=live` and `GEMINI_API_KEY` in the project's encrypted Environment Variables, then redeploy. Keep the key out of GitHub and browser-side code.

## Database and deployment

Set `DATABASE_URL` to a managed PostgreSQL connection string for shared storage. The production deployment uses PostgreSQL because Vercel instances do not keep local files between runs. Configure `DHAGA_APP_PASSWORD` in the Vercel project settings; Vercel Authentication remains enabled as a separate access gate.

The current deployment uses the repository's `Dockerfile.vercel`. To deploy a later version, use the Vercel project already linked to this repository and keep both access gates enabled.

## Limits to keep in mind

- Carrier tracking uses sample JSON records, not live courier APIs.
- The four policy examples are not Dhaga-approved policy. Confirm their wording and rules with the CX owner before any pilot.
- Data in `data/` is synthetic. Replace it with authorized, client-approved test data before handling real customer information.
- “Approve” records an internal staging or agent handoff decision. It never publishes a listing or sends a customer response.
- The shared app password is a team demo gate, not per-person identity or role-based access.
- Live model latency and quality need measurement with the configured provider. Demo performance tests do not prove a production AI latency target.

## Project layout

```text
app.py                       Streamlit workspaces and operator screens
dhaga_os/catalog.py          Supplier parsing, normalization, copy and checks
dhaga_os/cx.py               Ticket routing, sample lookup, replies and fact checks
dhaga_os/policy_rag.py       Local policy ranking
dhaga_os/llm.py              Structured Gemini boundary
dhaga_os/db.py               SQLAlchemy tables, approval and recovery queries
data/                        Synthetic products, orders and policies
docs/architecture.md         High-level design, data flow and database schema
tests/test_acceptance.py     PRD acceptance and regression checks
Dockerfile.vercel            Vercel container entry point
```
