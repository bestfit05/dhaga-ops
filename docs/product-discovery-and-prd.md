# Dhaga Ops: product discovery, requirements, and gap audit

Date: 2 October 2026. This is a corrective discovery and requirements review of an existing implementation. It was written after the first build and must not be presented as a discovery note dated before the first commit. No client interviews, production data, or observed user studies were available for this review.

The supplied sources are **FDE Academy: The Dhaga & Co. Engagement** (client brief) and **FDE Academy: How to Read the Dhaga & Co. Brief** (reader's guide). They are provided separately and are not published in this repository. Citations use their numbered sections; the printed page numbers below exclude the cover.

| Source | Relevant section and printed page |
| --- | --- |
| Client brief | Client/operations: sections 02–03, pages 1–3; data: section 04, page 3; complaints/constraints: sections 05–06, pages 4–5; discovery: section 07, page 5; MVP/ground rules: sections 08–09, pages 5–7; presentation/deliverables: sections 10–11, pages 7–8; scope: section 15, page 10 |
| Reader's guide | Reading method: sections 02–03, pages 1–3; required discovery judgment and common mistakes: sections 04–05, pages 3–4 |

## 1. Discovery decision

**Problem, in the client's language:** Arpita's agents spend their day answering the same order-status questions, while customers wait nine hours for a first response; agents need an easy way to find the right order facts and prepare a reply they can trust.

**Owner and current workaround:** Arpita, Head of CX, owns the primary problem. Thirty-four agents use Freshdesk, a Gupshup WhatsApp line, and a shared document of canned replies. The secondary workflow belongs to Vivek, the listing lead: a six-person team types product attributes into an internal admin and writes copy by hand after the studio shoot. (Client brief, sections 03 and 05.)

**Evidence and scale:** The brief reports about 9,000 support tickets a week, 58% concerning order status, and nine-hour average first response. The addressable WISMO volume is therefore approximately `9,000 × 0.58 = 5,220 tickets/week`. This is derived arithmetic, not measured app traffic. Existing order data is described as clean; ticket tags are inconsistent. Listing work has a six-to-nine-day sample-to-live cycle, about 400 new SKUs a week, and around 200 descriptions written by four people each week. These are different workloads, not interchangeable denominators. (Client brief, sections 02–05.)

**Decision:** Prioritize an agent-reviewed order reply workflow. Retain the existing supplier-listing workflow as a bounded second task rather than expanding into retention, returns prediction, a storefront, or autonomous support. The two tasks share a clear product contract: bring source information, inspect what needs attention, review the proposed text, then save an internal handoff. They have different owners and must have separate success metrics.

**Cost of the primary problem:** The verified cost is waiting time and 5,220 repetitive tickets per week, not a verified rupee saving. If measured handling time falls by `d` minutes per WISMO ticket and the eligible fraction is `e`, the opportunity is `5,220 × e × d / 60` agent-hours/week. Illustratively, `e = 1` and `d = 2` imply 174 hours/week; both are unvalidated assumptions. Salary, current handling time, resolution quality, and backlog scheduling are missing. A faster draft by itself does not prove a faster first response.

**Success:** In a supervised pilot, agents should prepare and review a factually correct reply with less active handling time than today's process, without increasing corrections, repeat contacts, or bad handoffs. Measure the workflow with Freshdesk timestamps and a timed task sample; measure first-response time separately. For the listing workflow, measure supplier-sheet-to-approved-draft time and correction rates before claiming an improvement in sample-to-live time.

**Biggest assumption and falsifier:** Looking up facts and composing replies consume enough of WISMO handling time to materially affect the queue. Observe agents' current workflow and time each step. If the nine-hour delay is mainly queue staffing, unavailable carrier updates, or ownership gaps, and lookup/composition is a small share, this workbench will not solve the response-time problem. A cheaper initial test is a verified-order template plus a source facts panel in an agent's existing workflow; compare it with the AI version before adding more generation.

## 2. Ranked shortlist and why this order is defensible

Ranking uses strength of brief evidence, addressable repeat work, availability of trustworthy source data, ability to validate in a small pilot, policy risk, and operational effort. These are qualitative judgments. Numerical RICE scores would require reach periods, impact estimates, confidence, and engineering effort that the brief does not supply.

| Rank | Problem and accountable owner | Verified evidence | Why here; what could change the rank |
| --- | --- | --- | --- |
| 1 | Repetitive order-status handling and slow first response; Arpita | 9,000 tickets/week; 58% WISMO; nine-hour first response; 34 agents; clean order data | Bounded input-to-reviewed-reply task with clear failures and an existing measurement system. Drops in rank if waiting is caused mainly by staffing or unavailable carrier data. |
| 2 | Slow listing preparation; Vivek | Six-to-nine-day sample-to-live cycle; ~400 new SKUs/week; inconsistent colors, free-text fabric, vendor size charts; ~200 descriptions/week | Strong existing implementation and a reversible human-review workflow. Drops if the studio, sample arrival, or approval queue dominates lead time rather than attributes/copy. |
| 3 | Fit-related returns are hidden in free text; Neha | 31% returns overall; 44% of return reasons are "Other"; Neha's manual reading suggests fit is common | A valuable discovery/analysis opportunity, but labels, size-chart truth, return denominators, and interventions need validation. Text classification alone would not fix fit. |
| 4 | COD return-to-origin losses; Faizan | 61% COD share; 26% COD RTO; ~₹120 logistics cost each; 48,000 orders/week | Largest directly calculable logistics exposure, but cause and safe intervention are not supplied. Ranks higher if an actionable cause can be tested without harming COD customers. Do not respond by encouraging doorstep refusal. |
| 5 | Slow business analysis requests; Karthik | Two analysts; roughly two-week queue; reviews and search data largely unused | Broad potential but many undefined questions, permissions, and answer-quality risks. First identify a repeated, decision-linked request. |
| 6 | Weak retention and rising acquisition cost; Ritu and Sameer | 22% repeat purchase for six quarters; CAC up 40% year on year | Critical business outcomes, with no demonstrated cause or bounded intervention in the brief. An operations workbench must not claim it directly fixes either metric. |

The COD estimate, assuming the stated percentages apply to the same weekly order cohort, is `48,000 × 0.61 × 0.26 ≈ 7,613 COD RTOs/week`, with `7,612.8 × ₹120 ≈ ₹9.14 lakh/week` logistics exposure. This is an estimate from brief figures, not recoverable savings or a promise that the MVP reduces RTO. (Client brief, sections 02 and 05.)

The ranking is a decision to validate, not client consensus. The reader's guide explicitly requires at least four serious alternatives, a stated basis for ranking, a named owner, specific evidence, a cost, a build choice, and a way to know it worked. (Reader's guide, sections 04–05.)

## 3. Evidence register and important source gaps

| Evidence type | What is supported | What is not supported |
| --- | --- | --- |
| Original client brief | Business figures and constraints; current systems; stakeholder complaints; human review; deployed usable MVP; two different models; validated model outputs; visible failures; cost arithmetic | A chosen problem, a supplied PRD, any approved policy text, a four-day delay rule, cancellation/refusal policy, return eligibility windows, or a promised reduction in time/cost |
| Reader's guide | Discovery method, ranking rationale, avoiding symptoms and retrofitted justification | A recommended feature set or predetermined winning problem |
| Repository and synthetic fixtures | Implementation, illustrative color aliases, sample orders, examples, local policy retrieval, approval and persistence code | Client authorization, production integration, real customer results, production latency, complete client color mappings, or a statistically representative ticket corpus |
| External primary sources | Design and technical guidance used to define requirements below | Evidence that Dhaga agents have been interviewed or that this app already meets an accessibility standard |

No standalone original PRD or pre-build discovery note was found among the tracked documentation and the two supplied PDFs. Existing references to "the PRD" or "RICE" should be treated as implementation-era assumptions until that source is supplied. The 24-color palette, 141 local aliases, a 500-row cap, a 50-row/90-second test, and a three-second demo triage test are implementation choices; the brief does not prescribe those numbers.

Four policy examples in `data/policies.json` are demonstration rules, not Dhaga-approved policy. The brief says delivery typically takes four to seven days, longer into the northeast; it does not say that every shipment older than four days is late. A verified ETA in the past is useful evidence of an overdue delivery, while transit age without an ETA is uncertainty. The brief also gives no authority to refuse a COD parcel, cancel it after dispatch, promise compensation, or state a refund deadline. The only supplied refund sequence is collection, inspection, then refund. (Client brief, sections 03, 05, and 06.)

## 4. Product requirements

### Audience and scope

The application is an internal operator workbench. Its main users are CX agents and listing operators who can work with messages and spreadsheets but should not need to understand models, routing, schemas, databases, or deployment. Dhaga's shoppers influence language, reliability, and safety requirements; this MVP does not replace the consumer Android shopping app.

| User | Job to complete | Information needed to act safely | Product responsibility |
| --- | --- | --- | --- |
| CX agent, accountable to Arpita | Prepare a useful order reply or request the missing information | The exact matched order, source status/location, ETA if present, unavailable facts, applicable example/client policy, and next owner | One obvious input; readable facts beside the reply; recoverable errors; explicit internal handoff |
| Listing operator, accountable to Vivek | Prepare product details and text from supplier evidence | Original supplier fields, normalized values, unresolved fields, content conflicts, and which rows are approved | A searchable review queue; clear required fields; source-backed choices; saved edits; separate draft and approval |
| Team lead | Review saved work and find outstanding exceptions | Counts by meaningful state, oldest unresolved work, handoff reason, and approved exports | Clear status language and recovery; no false claim that an external task has been completed |
| Dev or app administrator | Keep the small workflow running | Storage health, model configuration, failure logs, startup instructions, and dependencies | Technical detail belongs in documentation/admin troubleshooting, with plain operational status for users |

### Intended journeys

**First visit:** Open the MVP directly without an app password or login, see what it does in one sentence, choose "Customer messages" or "Product listings", and use a clearly marked example. The sidebar is for navigation. Overview counts open the corresponding queue. Sample data and live integration status remain visible. Approval saves work for teammates under automatic actor **MVP team**, without personal authentication. It does not send or publish.

**Customer message:** Open a pending/risk/return queue or paste the customer's wording → optionally supply the order number or phone → check the order → inspect source facts and uncertainties → edit the proposed reply → confirm source review → save a draft or approve an internal handoff → find it again after refresh. A missing identifier produces an editable request for information. Unknown orders, broken tracking, disputed delivery, ambiguous matching, and unsupported requests produce an actionable manual-review state. The approved result's **1-click reply to CX** link opens the [Freshdesk main page](https://www.freshworks.com/freshdesk/) for demonstration only; it does not send or select a connected ticket.

**Product listing:** Load a supplier CSV/XLSX or example → see readable rows and a separate error report → select a product from a queue → compare source with standardized values → resolve missing/uncertain details → inspect and edit the listing text → save edits or approve → continue to the next product → export approved work separately from drafts.

### Release acceptance criteria

These are requirements for the improved workbench. The audit column describes the starting implementation inspected on 2 October 2026; it is not a claim that every criterion has passed in the final deployment. Release validation must record actual test outcomes.

| ID | Acceptance criterion | Starting audit and verification needed |
| --- | --- | --- |
| AC-01 | A first-time nontechnical user can select a task, load an example, recognize the next action, and explain the saved result without coaching. | Overview and examples exist, but onboarding relies heavily on many alerts and long forms. Validate through realistic tasks and a clean browser session. |
| AC-02 | Catalog import accepts real-shaped header aliases and mixed valid/invalid rows; valid rows survive; errors identify the row and correction; empty or oversized input fails visibly. | Parser and row report exist; alias, malformed-row, missing-field, and batch-size checks need representative fixtures. |
| AC-03 | A supplier code, name, source-supported material, and confirmed standard color are required before catalog approval. Unknown shade suggestions are never silently accepted. | Service/UI guards exist. Confirm that direct approval calls also reject invalid data and edits rerun factual checks. |
| AC-04 | A user reviews one chosen product at a time; search/filter/selection work at a 50-row batch size; opening a saved draft selects that actual draft. | Starting UI expands a form for every row and its saved-draft selector does not reliably focus the selected record. This makes batch review slow and confusing. |
| AC-05 | Copy and support replies cannot acquire an unsupported fabric/care claim, courier, order number, location, delivery date, delivery promise, or policy promise through editing or generation. | Deterministic checks cover some terms/dates; schema validation is not semantic validation. Add regression cases for plausible but wrong facts and unsupported policy wording. |
| AC-06 | Order lookup uses literal identifiers. If an order number and phone conflict, or a phone matches multiple orders, do not silently select an unrelated/latest order. | Starting lookup falls through from a failed order ID to phone and picks a latest active phone match. Exact match, conflicts, ambiguity, and override recovery need explicit tests. |
| AC-07 | English, Romanized Hinglish, and representative Hindi-script messages have clear outcomes; a cancellation mentioned in negation is not automatically treated as cancellation. Unsupported intent requires a person. | Hinglish/negation tests exist. A larger labeled language set and human review are still needed; no universal vernacular accuracy claim. |
| AC-08 | Delay uses verified ETA/status evidence. A future ETA or missing ETA is not automatically labeled overdue because transit exceeds four days. | Starting rule and policy use a universal four-day threshold; this conflicts with normal delivery ranges in the brief and must be corrected. |
| AC-09 | Cancellation/return requests expose missing eligibility information and prepare a manual handoff. No invented refusal, refund timing, compensation, or external assignment claim is presented as policy. | Starting COD reply encourages doorstep refusal; example rules lack owner/version approval. Replace unsafe inference and keep policy uncertainty visible. |
| AC-10 | Edited customer replies can be saved without being approved; a refreshed page reopens the saved edit; meaningful changes require re-review before approval. | Initial support draft persists, but the starting reply editor mainly saves on approval. Verify save/resume across navigation and a new session. |
| AC-11 | Every meaningful action distinguishes "open in browser", "saved draft", "needs review", and "approved for internal handoff"; success appears only after storage succeeds. | Storage and statuses exist. Verify provider/database failures, partial catalog writes, repeated clicks, approval guards, and export state. |
| AC-12 | Saved lists and exports are readable to operators, omit internal JSON/debug fields, and preserve Hindi/Unicode. Draft exports and approved exports have clear labels. | CSV export exists; dense dataframes and raw state labels need an operator-oriented projection. Verify CSV opening and safe treatment of spreadsheet formula-like source cells. |
| AC-13 | At 390px mobile width and 200% zoom, essential actions, labels, and replies remain usable; color is not the only status cue; keyboard focus and form labels remain accessible. | Streamlit defaults are a starting point, not proof. Browser/keyboard checks are required; a WCAG audit has not been performed. |
| AC-14 | Model absence/failure produces a visible local fallback or manual check. A local lookup or successful schema parse does not certify correctness; no provider error or secret appears to users. | Rules-first gateway, optional demo mode, and validated Pydantic boundaries exist. Verify invalid outputs, omission, timeout, quota errors, and unsafe text. |
| AC-15 | A stranger can run locally from the README, and an authorized cold browser can complete happy/failure paths on the deployed URL with durable saving. | Instructions and deployment exist. Time a fresh setup; verify production storage, gate access, refresh recovery, and the deployment revision. |

The 3 October MVP scope additionally requires direct app access without login; a navigation-only sidebar; automatic **MVP team** approval attribution; clickable overview counts that match their filtered queues; and an explicitly labeled Freshdesk demonstration handoff. Pending tickets exclude approved replies. High/low-risk counts partition all pending work; return/refund, ready-to-review and missing-detail counts are overlapping subsets. Risk labels guide attention and do not establish fraud probability or correctness. Disconnected sessions are retained for up to 24 hours on the same running server; users still need to save, because restart/new-browser recovery is only guaranteed for successfully saved database records. Test and deployment evidence for this update is recorded separately from the starting audit and earlier release.

### Plain-language and accessibility requirements

Use task labels such as "Check order", "Save draft", "Needs more details", and "Approved for the team". Explain unusual terms at the point of use. Keep source facts, choices, and the current result visible, with one main action for the current step. Avoid requiring users to remember supplier facts while scrolling between long forms. This applies the author's guidance on system status, user-language matching, error prevention, and recognition. [Nielsen Norman Group, usability heuristics.](https://www.nngroup.com/articles/ten-usability-heuristics/)

Show a concise error summary and a correction beside the relevant field; preserve entered text when saving fails. Success must identify what was saved and how to reopen it. Programmatic labels, keyboard focus, and announced feedback need verification in the rendered app. [W3C WAI, form notifications.](https://www.w3.org/WAI/tutorials/forms/notifications/)

Use readable contrast and responsive layouts. Target controls should meet WCAG 2.2's 24×24 CSS-pixel minimum or its spacing/exceptions; main actions should be comfortably larger. Reflow ordinary task content at narrow widths; a table may scroll, but the whole task should not depend on two-dimensional scrolling. These are design and test targets, not a conformance claim. [W3C, target size](https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html), [W3C, reflow.](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)

### Technical and AI boundary

File parsing, dictionaries, size normalization, identifier matching, lookup, date arithmetic, policy ranking, storage, and approval checks belong in deterministic code. Use a model for useful messy-language interpretation and copy wording. Model-generated text and operator edits always receive source checks plus human review.

Routing is necessary because a verified order status does not need generative lookup and a cancellation/dispute needs a different safe path. Chaining is useful for attributes → copy → review because copy should see standardized source facts. An evaluator can surface inconsistencies, but is not a guarantee, and a single audit without a repair loop should be described as evaluation rather than a full evaluator-optimizer cycle.

The original brief requires **at least two different models**. At the audit's start, both configurable roles defaulted to `gemini-3.1-flash-lite`; two role names using one model do not satisfy that rule. The revised code uses distinct defaults: `gemini-3.5-flash-lite` for extraction/routing/evaluation and `gemini-3.8-flash` for wording, with configurable overrides. A measured cost/latency/quality comparison remains necessary; distinct defaults do not demonstrate live calls or superior outcomes. Extraction/classification temperature 0.0, color suggestion/evaluation 0.1, support wording 0.4, and catalog copy 0.7 are documented implementation settings, not evidence that outputs are correct.

Google's structured-output guidance distinguishes a syntactically valid schema from semantically correct values. Retain local field/fact checks, reject unmatched row IDs and unsafe outputs, and show a recoverable fallback when validation fails. [Google Gemini API, structured outputs.](https://ai.google.dev/gemini-api/docs/structured-output)

## 5. Prioritized gap matrix

| Priority | Gap discovered | Consequence | Observed code response and remaining validation |
| --- | --- | --- | --- |
| P0 | Fabricated COD refusal and universal four-day delay policy | Wrong advice may increase RTO; false delays confuse agents | Corrected to overdue supplied ETA, missing-date uncertainty, and manual cancellation/eligibility check; local regression checks passed. CX owner must still approve actual policies. |
| P0 | Partial factual checks and ambiguous/conflicting lookup | A plausible reply may refer to the wrong order or make an unsupported claim | Explicit IDs no longer fall through to another phone match; nonunique phone results block. Final checks cover known fact/link/status/location and promise expressions. Bounded coverage still needs representative language/policy review. |
| P0 | Approval/edit persistence semantics unclear | Users can lose work or mistake a staging approval for external action | Separate CX draft save, exact/full saved-record recovery, stable reupload IDs, final-content recheck and idempotency implemented. Revision tokens, conditional writes and row/SKU locks guard stale/concurrent writes; UI/concurrency regressions passed. Hosted full-list and exact-product recovery verified; final revision `a2c5dd9` is READY. |
| P1 | No original discovery decision or traceable PRD | Hard to defend scope, business value, or acceptance | This corrective document supplies evidence, ranking, assumptions, criteria, and measurement; client owners must validate. The original pre-code discovery timing cannot be recreated. |
| P1 | Long all-row forms and noisy status layout | Nontechnical users cannot easily find the next product or action | Search/filter queue, one selected product, source comparison, task steps, readable states and reply/facts panels implemented. Cold user observation is still missing. |
| P1 | Two configured roles default to one model; cost line is stale | Assignment ground rule and cost justification remain incomplete | Distinct current model defaults configured; build note replaces the stale cost with explicitly assumed tokens and dated published prices. Live usage/quality/latency remains unmeasured. |
| P1 | No observed usability evidence | A clean-looking UI may still require narration | Uncoached target-user study remains open. Automated/browser journeys can establish behavior, not that a nontechnical person understands it without explanation. |
| P1 | No end-to-end live performance/cost evidence | Demo timing can be mistaken for production promise | Live model/total latency, tokens, failures, review time and usage cost remain open. Local implementation timing benchmarks are labeled separately. |
| P2 | No person-level identity and small local example policy set | No individual accountability or production policy authority | Latest MVP removes app password/login and uses automatic actor **MVP team**, without rewriting historical attribution. Revision/conflict checks remain. Individual roles, approved versioned rules, real-data retention and production migration strategy remain pilot work. |
| P2 | No Freshdesk/Gupshup/courier integration or owner task assignment | Handoff saved in this app does not change the operational queue | Internal follow-up wording/export is explicit. Latest post-approval Freshdesk link is a public-page demonstration, not a send action or connected ticket. A permissioned read adapter and agreed handoff contract remain needed. |

P0 behavior is required for a credible release of the demo. The code responses above were inspected, local regression tests passed, and hosted operational checks succeeded; successful live AI remains separate and unverified. P1 items make the work defensible and understandable. P2 items are explicit pilot dependencies, not features silently claimed as implemented. CSV formula-like text handling and complete listing export fields are implemented and covered by local checks.

## 6. Measurement, cost, and release evidence

| Metric | Baseline available | Measurement and proposed decision rule |
| --- | --- | --- |
| WISMO first response | Brief: nine hours average, definition/period unspecified | Freshdesk created-to-first-agent-response timestamp, business/calendar-hour definition agreed; compare matched queues/cohorts. Do not equate draft generation with response. |
| Active handling time | Missing | Timed current-workflow tasks versus workbench tasks including lookup, editing, verification, saving, and transfer. Proposed pilot gate: median improvement ≥30%, with no quality regression; Arpita must approve the target. |
| Factual/policy defect rate | Missing | Independently review a labeled set stratified by carrier, missing ETA, delay, cancellation, return, conflict, dispute, and language. Any wrong order or unsupported promise is a release blocker. |
| Reply acceptance and edit burden | Missing | Accepted-without-edit fraction and reasons, material edit rate, time spent verifying, human escalation disposition. A high acceptance rate alone is not correctness. |
| Repeat contact/CSAT | Existing platform may hold it; not supplied | Use matched resolved-ticket outcomes after an approved pilot. Confirm availability and attribution before setting targets. |
| Catalog draft preparation | Missing; sample-to-live is six to nine days | Track supplier-input-ready → reviewed-draft, corrections per product, exception reasons, approval completion. Preserve total sample-to-live as a separate downstream metric. |
| Usability | No user observation | Initial proposed sample: five nontechnical operators, including CX and listing roles. Report participant/task results directly; ≥4/5 complete core tasks without coaching is a proposed iteration gate, not statistical proof. |
| Reliability and performance | Local acceptance tests only | Report local/demo and live model timings separately. Measure p50/p95 total time, storage failure, model failure/fallback, and durable refresh recovery under the actual deployment. |
| Cost per reviewed action | No current metered provider bill | Record model ID, calls, input/output tokens, retries, batch rows, fallback, and review time; use current published prices and separate Vercel/database costs. |

Run usability sessions around actual tasks, neutral instructions, consent, observation, and follow-up questions rather than a guided feature tour. Include users with relevant access needs. [GOV.UK Service Manual, moderated usability testing.](https://www.gov.uk/service-manual/user-research/using-moderated-usability-testing) Ask about confidence and satisfaction after task completion as well as observing success. [GOV.UK Service Manual, measuring satisfaction.](https://www.gov.uk/service-manual/measuring-success/measuring-user-satisfaction)

**Cost arithmetic:** `model cost/run = Σ[(input tokens × input price + output tokens × output price) / 1,000,000]`, adding retries and any separately billed categories. `weekly model cost = eligible CX runs × mean CX cost + catalog batches × mean batch cost`. Use 5,220 WISMO tickets/week only as addressable volume, and separate eligible fraction, adoption, calls per task, and 200-description/400-SKU workloads. Rules-only demo model cost is zero; hosting, storage, and human work remain costs. Published free tiers have quotas and may use submitted data to improve products; confirm current terms and authorized data before a real-data pilot. [Google Gemini pricing and data-use terms.](https://ai.google.dev/gemini-api/docs/pricing)

The earlier build note's $21.29/week figure assumed an older three-call paid configuration. The revised [build note](build-note.md) replaces it with dated current prices and explicitly illustrative token/workload assumptions, separates 200 descriptions from 400 new SKUs, and keeps rules-only demo model cost distinct. None is a measured live bill. A free model price is also not an unlimited throughput guarantee.

### Minimum release evidence to record

1. Commit/revision, deployment URL, access path, date, execution mode, and storage type.
2. Catalog happy path, one blocked/unknown-color path, a malformed row, saved exact-draft recovery, and approved-only export.
3. CX routine order, overdue ETA, future/missing ETA, missing ID, unmatched/conflicting identifiers, cancellation, broken tracking, and disputed delivery.
4. An edited fact/promise that cannot be approved; a saved unapproved reply that survives refresh; visible model and storage failure behavior.
5. Desktop/narrow-width/zoom and keyboard checks, plus a clean browser cold-open check.
6. Actual automated check results and limitations. Do not turn this checklist into claims before those checks occur.

### Verification recorded during this review

On 2 October 2026, the local suite passed **70 tests in 1.793 seconds**, including full UI workflows, edited-content/terminal-order cases, concurrency, provider-configuration, recovery and export checks. Independent code review reported no blocking findings in the reviewed changes. Browser layout was inspected at 1440px desktop and 390px phone widths; responsive navigation and sidebar-help contrast were corrected.

The shared database snapshot was checked read-only: 130 listings, 8 support cases, and no duplicate approved normalized supplier codes. No existing records were rewritten and no schema migration ran. Reopened revision tokens, conditional writes, PostgreSQL row/normalized-SKU locks, SQLite writer serialization, full saved-work retrieval, and complete export fields are part of the inspected implementation.

For the earlier 2 October release, GitHub `origin/main` contained deployed revision `a2c5dd987b4fec312d2d89d28ca1df715aa5f5da`; its matching Vercel deployment was READY and health returned `ok`. Hosted sign-in, phone navigation, full 130-draft retrieval, exact chosen-product recovery and saved approved replies were checked. The read-only database check confirmed 130 listings, 12 cases and zero duplicate approved normalized supplier codes. Four synthetic CX smokes account for the 8-to-12 case change, with no approval or sending; existing products were untouched. These historical checks do not verify the later no-login/navigation/queue update; see the separate current-release record.

Fast classification succeeded once on a short ambiguous message, changing local `OTHER` to `RETURN_REQUEST`; that outcome was not independently labeled for accuracy. An earlier creative attempt showed a took-too-long message under the 20-second request configuration; later attempts showed mapped temporary AI-service unavailability. The final LOW-thinking/40-second single-attempt release still displayed temporary unavailability and used fact-checked local fallback. Its 3 October ETA stayed correct and eight transit days did not falsely mark a future ETA overdue. The runtime stream contained no safe Gemini failure events, so no exact HTTP code, transport subtype or deeper runtime/JSON cause was captured. No cold human user study, successful creative-quality/latency benchmark, or production Dhaga integration was tested. The [release verification record](release-verification.md) gives exact revisions and scope.

## 7. Client validation still required

| Question or evidence request | Owner | Decision it unlocks |
| --- | --- | --- |
| Observe a representative agent shift; time lookup, composition, carrier waiting, and queue waiting; obtain deidentified ticket samples and labels | Arpita | Whether WISMO automation addresses the nine-hour delay and what assistance is safe |
| Supply approved cancellation, returns, compensation, delay, and missing-tracking rules with versions and escalation owners | Arpita and Faizan | Replace illustrative policy; prevent wrong promises and RTO harm |
| Define authoritative order/phone matching, multiple-order selection, source timestamps, courier freshness, ETA semantics, and stale-data behavior | Dev and operations | A trustworthy real order adapter and error recovery contract |
| Observe the sample-to-live pipeline; identify which stage causes delay; supply approved attributes, the actual color dictionary, vendor size charts, and representative sheets | Vivek | Whether listing preparation is the bottleneck; field requirements and dictionary authority |
| Confirm response-time calculation, measurement period, return-rate denominators, salaries/handling time, and workload cohorts | Karthik and function heads | Defensible targets and a benefit/cost line |
| Name who reviews, owns exceptions, and checks failures on Monday after the build team leaves | Dev, Arpita, and Vivek | Sustainable operation by the existing team without an ML engineer |
| Approve identity/roles, retention/deletion, supplier/customer data access, model-provider terms, and credentials for a bounded real-data pilot | Dev and data owner | Moving beyond synthetic examples |

The brief's ₹310 crore run-rate GMV, ₹840 AOV, and ~48,000 weekly orders should retain their original context. Naively multiplying weekly orders × AOV × 52 gives ~₹210 crore; different periods or definitions may explain it, but those definitions are not supplied. Do not reconcile by inventing extra revenue or quietly replace the brief's verified figures.

For a later Freshdesk integration, the official API exposes ticket retrieval, conversations, notes, and replies as distinct operations. Start with permissioned read-only retrieval and an explicit internal-review handoff. API availability is not evidence that this app is integrated or that sending is authorized. [Freshdesk API reference.](https://developers.freshdesk.com/api/)

## 8. Submission constraints that remain separate from product improvements

The original brief requires a dated pre-code one-page discovery note, a usable deployed frontend, a root README supporting a five-minute cold start, at least two deliberately chosen workflow patterns, two different models, structured validated output, stated temperatures, visible failures, a two-page maximum build note including cost and an unexpected failure, and a twenty-minute presentation with all five members speaking. The live demo must include a failure case. (Client brief, sections 07–11 and 15.)

This corrective review restores missing reasoning and gives the team a testable product contract. It cannot reconstruct pre-code agreement, client interviews, measured production results, a full accessibility audit, or the live team presentation. Keep those limits explicit while making the implemented workbench clearer, safer, and easier to operate.

## 9. Proposed future development phases

The application's **Future scopes** menu translates the requirements above into a proposed sequence. These phases are not dated commitments, original-brief milestones or claims that a future feature is ready. Each phase exposes its goal, work, dependencies and checks before proceeding.

| Phase | Goal and work | Dependencies and release checks |
| --- | --- | --- |
| 1 — Prove the basics with the team | Observe the actual work; confirm policies, product definitions and exception ownership; validate realistic language, recovery and accessibility. | Arpita, Vivek and Faizan approve source rules and representative examples. The proposed 4-of-5 uncoached usability check needs agreement; any reviewed wrong-order reply or unsupported promise blocks release. See sections 4–7. |
| 2 — Connect trusted sources | Add real order/courier updates, approved versioned policies, read-only Freshdesk retrieval, individual reviewer access and agreed data handling. | Dev, operations and the data owner approve access, matching/freshness semantics, provider terms, retention and handoff ownership. Verify failures and permissions before external actions. See sections 5 and 7. |
| 3 — Run a measured, supervised pilot | Compare templates and AI-assisted work against the current workflow; measure handling, response, listing preparation, corrections, latency, failures and cost. | Owners agree baseline definitions and operating responsibility. Arpita must approve the proposed ≥30% median active-handling improvement with no quality regression; report actual results rather than infer whole-cycle or first-response savings. See sections 1, 6 and 7. |
| 4 — Choose the next problem from evidence | Revisit fit-related returns (Neha), COD return-to-origin (Faizan), decision-linked analysis (Karthik), then retention/acquisition cost (Ritu and Sameer). | Rerank with permitted data, reliable labels, a named owner, a baseline and a bounded measurable trial. Do not claim business improvement before evidence. See sections 2, 3 and 7. |
