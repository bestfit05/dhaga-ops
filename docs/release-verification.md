# Release verification

Verified on 2 October 2026. This record distinguishes local regression tests, hosted operational checks, and remaining validation.

## Code and deployment

| Item | Verified result |
| --- | --- |
| Current deployed code commit | `a2c5dd987b4fec312d2d89d28ca1df715aa5f5da` |
| Git delivery | Pushed to GitHub `origin/main` |
| Production URL | [dhaga-ops.vercel.app](https://dhaga-ops.vercel.app) |
| Current Vercel deployment | `dpl_DbuvU8d6o8cVNQRQNtqcnW4cTKdR`, status `READY`, matching the code commit and aliased to the production URL |
| Access | Authenticated hosted access and app sign-in checked; existing access gates retained |
| Latest local regression suite | All 70 tests passed in 1.793s, including UI workflows, approval/content checks, recovery, CSV handling, concurrency and provider configuration regressions |
| Independent code review | No blocking findings reported in the reviewed changes |

Saved-work checks were conducted across the initial and follow-up releases. Fresh authenticated sign-in, health (`ok`), phone navigation, and a persisted synthetic CX draft were checked again on the final revision above. Documentation changes alone do not alter the referenced application revision.

The final code uses LOW thinking for Gemini 3.8 Flash, a 40-second request timeout, and one attempt. Provider diagnostics expose a safe error category; formula-like text is protected in direct CSV exports and dataframe downloads. The final [deployment URL](https://dhaga-if9xrmvzk-tushar-64b9.vercel.app) and the production alias both reference the verified release.

## Hosted operational checks

- The application health check succeeded and the authenticated sign-in screen loaded.
- The saved product workflow retrieved the complete 130-draft list rather than stopping at a default list cap.
- Opening a chosen saved product reopened that exact product.
- Saved approved customer replies were available in the hosted app.
- Desktop layout at 1440px and phone layout at 390px were inspected; responsive navigation and sidebar-help contrast were corrected.
- Four synthetic CX smokes created four drafts to exercise the hosted workflow. They did not approve a reply, send a customer message, or change existing records.
- The final Hinglish order-status smoke retained the correct supplied 3 October 2026 ETA. Eight days since shipping did not incorrectly trigger an overdue state when that ETA was still in the future.

The shared database was inspected read-only before the smokes: 130 listings, 8 support cases, and no duplicate approved normalized supplier codes. The final read-only check confirmed **130 listings, 12 support cases, and zero duplicate approved normalized supplier codes**. Four persisted synthetic smoke drafts account for the 8-to-12 case change. The existing 130 products were untouched; no existing records were rewritten and no schema migration ran. These smoke records are not customer activity or product adoption evidence. Final hosted screenshots record the 1440px home and the checked customer result.

## Live AI result and limits

One hosted short ambiguous message produced a schema-valid result from the fast classification model, changing the local `OTHER` outcome to `RETURN_REQUEST`. This establishes an actual successful call, not classification accuracy or a labeled quality benchmark.

An earlier creative attempt showed a took-too-long message under a 20-second request configuration; later attempts showed mapped temporary AI-service unavailability. The final LOW-thinking/40-second release also displayed the mapped message "AI service is temporarily unavailable" and used local fallback. The runtime stream contained no safe Gemini failure events. The evidence is the UI's mapped temporary-unavailability category; no exact HTTP code, transport subtype or deeper runtime/JSON cause was captured. LOW thinking and the longer bounded timeout did not establish successful creative generation in this smoke.

The hosted application, fact-checked fallback, and storage checks succeeded. Creative generation remains unavailable in the observed smokes; end-to-end live AI quality, latency and cost remain unvalidated. A reachable deployment or a passing schema/regression test does not establish those results.

No cold human user study, production Dhaga/Freshdesk/Gupshup/courier integration, or accessibility conformance audit was performed. All orders/policy examples remain synthetic, approval remains an internal handoff, and reviewer names remain self-reported. Local timing checks are implementation benchmarks rather than measured production AI targets.

The [discovery and PRD review](product-discovery-and-prd.md) records the evidence, unresolved assumptions, pilot criteria and required client decisions. Record a successful representative creative-model run and subsequent provider/quality measurements before claiming end-to-end live AI operation.
