# Release verification

This record distinguishes each release's local regression tests, hosted operational checks, and remaining validation.

## Sample download, Future scopes and fresh-message update — hosted verification pending

The canonical supplier example moved to `static/dhaga_vendor_sample.csv`. Its bytes are unchanged: **2,969 bytes and 26 products**. Demo loading and the download now use the same file. **Download example sheet** links directly to the same-origin `/app/static/dhaga_vendor_sample.csv`, served with Streamlit static serving enabled; it is independent of in-memory download objects and database availability.

The **Future scopes** menu shows four proposed PRD-derived phases, with prerequisites and checks before proceeding. Customer messages includes the eight exact fresh synthetic examples, with a preview and an explicit load action. Eligible intent/reply prompts receive identifier-free patterns and handling labels. This is prompt adaptation, not weight training or a fine-tuned model; see the [dataset record](ai-example-dataset.md).

All **99 automated tests passed** in 3.735 seconds. These include the eight actual CX service routes, separate paraphrases, preserved billing gates and literal identifiers, delivery-dispute wording without confirmation-email/coupon/refund false matches in the added patterns, the `latest`/`late` sentiment correction, invalid input and unsupported-promise approval checks. UI checks cover read-only roadmap navigation, preserved unsubmitted text and explicit loading of fresh examples. Model-boundary checks use mocks and do not establish live Gemini accuracy.

A fresh local server returned the sample URL with HTTP 200 and `text/csv`, before opening an app session. Clicking the download link in the browser saved `dhaga_vendor_sample.csv` without leaving the product page; its 2,969 bytes match the shipped sample, and re-parsing produced 26 rows with no errors. Uploading the downloaded CSV through the app opened a 26-product batch, including five products needing attention. The four-phase roadmap opened from the menu in the browser. Independent review also exercised the installed Streamlit static route, confirmed deployment packaging includes the file and found no remaining actionable issue in the final changes.

Runtime commit, deployment and hosted download verification for this update are still pending. The completed release evidence below remains historical and does not establish deployment of this download change.

## Current MVP update — 3 October 2026

Current code/documentation changes remove the app password, login, sign-out and reviewer-name input. The sidebar is for navigation. New approval actions use **MVP team**, without verified personal identity or rewriting historical approvals. Overview numbers open matching product/customer queues with exact pending totals. High/low risk partition pending tickets; return/refund, ready-to-review and missing-detail subsets can overlap. After approval, **1-click reply to CX** opens the public [Freshdesk main page](https://www.freshworks.com/freshdesk/) as a demonstration; no ticket integration or customer send is performed.

Streamlit's disconnected-session retention is configured for 86,400 seconds on the running server. A restart, replacement server or new browser session can lose unsaved content. Saved database records remain recoverable. This is not automatic saving.

| Item | Current evidence |
| --- | --- |
| Runtime code commit | `089a5ba4b177a818668f2d47632fc953b26e1732`, pushed to GitHub `origin/main` |
| Local regression suite | All **84 tests passed in 3.210s**; independent backend run passed the same 84 tests in 3.201s |
| Independent review | Return-queue negation/address-change false positives were reproduced, corrected and validated; no remaining blocking findings reported |
| Vercel deployment | `dpl_DNUehkFCKoE13fMaEQwvW19ZKjYC`, **READY** with API-verified source commit above, [deployment URL](https://dhaga-hz5q9hha5-tushar-64b9.vercel.app), and production alias [dhaga-ops.vercel.app](https://dhaga-ops.vercel.app) |
| Public access and health | Vercel `ssoProtection` removed and verified `null`; anonymous requests without cookies/auth returned app HTTP 200 and health HTTP 200/body `ok`, without redirects |
| Hosted browser | Fresh tab and a later production reload opened Overview directly with nine clickable overview metrics, without login, reviewer entry, sidebar help or sign-out |
| Hosted phone layout | Actual production Overview and Menu inspected at 390px width, screenshot saved, and viewport restored afterward |
| Hosted queues | High-risk count 12 opened 12 matching tickets; low-risk count 0 showed clear empty-state guidance; return/refund count 1 opened exactly one matching row; approved-customer-replies count 3 opened exactly three approved replies |
| Hosted approved reply | Existing approved order 84920 reply opened read-only with saved-success state, reply text and **1-click reply to CX** link; clicking it opened `https://www.freshworks.com/freshdesk/` in a new tab with the official Freshdesk customer-service page title; the tab was closed and a screenshot saved |
| Hosted product queue | Clicking **156 Products awaiting review** opened Product listings with 156 left, 156 saved waiting, **Product 1 of 156**, and the selected product's detail form loaded; no edit, save, import or generation was performed |
| Local browser | Desktop and 390px phone layouts checked; actual approved-reply Freshdesk button opened the official homepage |

The current read-only shared-work snapshot has **156 pending products** and **15 support cases: 12 pending and 3 approved**. These are current queue counts, not the historical release's 130-listing/12-case snapshot below. The shared data changed between releases and may reflect user activity; this update's hosted verification performed **no shared-record writes and no AI calls**. An AI warning already stored on a saved product was not a new provider check. This release does not establish new live-model quality or availability results. All planned operational checks for this update are complete.

The earlier 70-test/READY result below must not be treated as current-release evidence. All three documentation diagrams passed actual Mermaid CLI 12.0.0 rendering, and their PNG previews were visually inspected. Both original sequence failures were reproduced and isolated to unescaped semicolons. Corrected SVGs and editable definitions are recorded in [the diagram verification record](diagrams/README.md). Documentation work did not write to the shared database.

## Earlier verified release — 2 October 2026

| Item | Verified result |
| --- | --- |
| Verified code commit | `a2c5dd987b4fec312d2d89d28ca1df715aa5f5da` |
| Git delivery | Pushed to GitHub `origin/main` |
| Production URL | [dhaga-ops.vercel.app](https://dhaga-ops.vercel.app) |
| Verified Vercel deployment | `dpl_DbuvU8d6o8cVNQRQNtqcnW4cTKdR`, status `READY`, matching the code commit and aliased to the production URL at verification |
| Access | Authenticated hosted access and app sign-in checked; existing access gates retained |
| Local regression suite for this release | All 70 tests passed in 1.793s, including UI workflows, approval/content checks, recovery, CSV handling, concurrency and provider configuration regressions |
| Independent code review | No blocking findings reported in the reviewed changes |

Saved-work checks were conducted across the initial and follow-up releases. Fresh authenticated sign-in, health (`ok`), phone navigation, and a persisted synthetic CX draft were checked again on the final revision above. Documentation changes alone do not alter the referenced application revision.

This release used LOW thinking for Gemini 3.8 Flash, a 40-second request timeout, and one attempt. Provider diagnostics exposed a safe error category; formula-like text was protected in direct CSV exports and dataframe downloads. Its [deployment URL](https://dhaga-if9xrmvzk-tushar-64b9.vercel.app) and the production alias referenced this release at that verification; the alias now serves the newer update above.

### Hosted operational checks

- The application health check succeeded and the authenticated sign-in screen loaded.
- The saved product workflow retrieved the complete 130-draft list rather than stopping at a default list cap.
- Opening a chosen saved product reopened that exact product.
- Saved approved customer replies were available in the hosted app.
- Desktop layout at 1440px and phone layout at 390px were inspected; responsive navigation and sidebar-help contrast were corrected.
- Four synthetic CX smokes created four drafts to exercise the hosted workflow. They did not approve a reply, send a customer message, or change existing records.
- The final Hinglish order-status smoke retained the correct supplied 3 October 2026 ETA. Eight days since shipping did not incorrectly trigger an overdue state when that ETA was still in the future.

The shared database was inspected read-only before the smokes: 130 listings, 8 support cases, and no duplicate approved normalized supplier codes. The final read-only check confirmed **130 listings, 12 support cases, and zero duplicate approved normalized supplier codes**. Four persisted synthetic smoke drafts account for the 8-to-12 case change. The existing 130 products were untouched; no existing records were rewritten and no schema migration ran. These smoke records are not customer activity or product adoption evidence. Final hosted screenshots record the 1440px home and the checked customer result.

### Live AI result and limits

One hosted short ambiguous message produced a schema-valid result from the fast classification model, changing the local `OTHER` outcome to `RETURN_REQUEST`. This establishes an actual successful call, not classification accuracy or a labeled quality benchmark.

An earlier creative attempt showed a took-too-long message under a 20-second request configuration; later attempts showed mapped temporary AI-service unavailability. The final LOW-thinking/40-second release also displayed the mapped message "AI service is temporarily unavailable" and used local fallback. The runtime stream contained no safe Gemini failure events. The evidence is the UI's mapped temporary-unavailability category; no exact HTTP code, transport subtype or deeper runtime/JSON cause was captured. LOW thinking and the longer bounded timeout did not establish successful creative generation in this smoke.

The hosted application, fact-checked fallback, and storage checks succeeded. Creative generation remains unavailable in the observed smokes; end-to-end live AI quality, latency and cost remain unvalidated. A reachable deployment or a passing schema/regression test does not establish those results.

No cold human user study, production Dhaga/Freshdesk/Gupshup/courier integration, or accessibility conformance audit was performed. All orders/policy examples were synthetic and approval was an internal handoff. Reviewer names in this historical release were self-reported; the later MVP update uses automatic **MVP team** attribution. Neither establishes verified personal identity. Local timing checks are implementation benchmarks rather than measured production AI targets.

The [discovery and PRD review](product-discovery-and-prd.md) records the evidence, unresolved assumptions, pilot criteria and required client decisions. Record a successful representative creative-model run and subsequent provider/quality measurements before claiming end-to-end live AI operation.
