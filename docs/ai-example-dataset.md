# Fresh customer-message examples

The eight synthetic messages supplied in this chat are maintained in `data/cx_examples.json`. They use the existing sample order records. Each example has an intent label and an expected handling outcome; none supplies a new carrier fact, delivery promise, refund entitlement or approved customer reply.

| Scenario | Message | Expected handling |
| --- | --- | --- |
| Routine tracking | Hi, could you share the latest tracking update for order 84922? | Look up that order and prepare a fact-checked draft. |
| Hinglish tracking | Order 84920 ka latest update bata do. Mujhe delivery ka wait hai. | Use that order's facts; attempt careful wording only when the existing AI gate permits it. |
| Return | Order 84930 ka size loose hai. Isko return karne ka process batao. | Identify a return request; require eligibility review before any commitment. |
| Cancellation | I accidentally placed order 84921. Can your team check whether cancellation is possible? | Require a teammate to check cancellation; do not claim the order was cancelled. |
| Unknown order | Can you locate order 68417? I cannot find its tracking details. | Report no matching sample order. |
| Missing identifier | My package hasn’t arrived. Could someone check its location? | Ask for an order number or the phone linked to the order. |
| Conflicting orders | My receipt shows order 84922, but please check order 84920 instead. | Ask the operator to confirm which order to check. |
| Disputed delivery | Order 84924 is marked delivered, but nobody at home received it. | Require delivery-proof investigation; do not treat a delivered scan as proof the customer received it. |

## How these examples improve the app

The app supplies labeled message patterns and handling instructions in eligible Gemini requests. Numeric identifiers are removed from those prompt examples. The current customer input and verified order lookup remain authoritative. The examples do not enable extra model calls, change configured models, remove fact checks, or bypass human approval.

The local routing rules also cover the missing-package wording and explicit negative receipt phrases uncovered by this set. Added receipt patterns distinguish the parcel from confirmation emails, coupons and refunds. The sentiment check treats `latest` separately from `late`, avoiding unnecessary AI wording for a routine tracking update. Automated checks run the eight scenarios through the actual CX service, with separate paraphrases for regression coverage. Provider-boundary tests use mocked responses, so passing them establishes application behavior rather than Gemini's accuracy on unseen customer messages. Input-format and unsupported-promise checks remain separate from model generation.

## Training status and limits

This is example-based prompt adaptation, not a fine-tuned Gemini model. Google's current Developer API and AI Studio do not offer a model that supports fine-tuning; the official guidance points to its enterprise platform for that capability. [Google Gemini fine-tuning documentation](https://ai.google.dev/gemini-api/docs/model-tuning).

No training job was submitted, model weights were changed, or new training infrastructure was configured. The messages are synthetic examples, not a representative or client-approved training corpus. Production accuracy, wording quality, latency and costs still need a separately labeled, independently reviewed evaluation set and successful live-provider measurements.

To extend this set, add a synthetic example with a reviewed intent and handling label, then add a separate paraphrase test. Keep real customer information out of the public sample files. Any future fine-tuning project needs an approved deidentified corpus, a held-out evaluation set, a supported model/platform and an agreed budget before a training job is run.
