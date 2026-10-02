# Architecture diagram verification

The [architecture page](../architecture.md) embeds static SVGs and links to editable `.mmd` sources. It renders without a Mermaid plugin. Open an SVG directly to zoom; the written architecture remains the explanation of each workflow.

## Reproduced failure

On 3 October 2026, the original three definitions were extracted from `docs/architecture.md` and rendered with the official `@mermaid-js/mermaid-cli` **12.0.0**, using installed Chrome rather than downloading a browser.

| Original diagram | Actual renderer result |
| --- | --- |
| System overview | Rendered successfully. A Markdown viewer still needs Mermaid support to display its original code fence. |
| Catalog sequence | Parse error at source line 11, after the message `Process only new rows; map colors and sizes` |
| Customer sequence | Parse error at source line 15, after the message `Exact order / unique phone lookup; validate identifier agreement` |

Mermaid treats unescaped semicolons as statement separators, including inside sequence-message text. Its documentation prescribes `#59;` when a message needs a literal semicolon. Replacing only the semicolons with commas made **both original sequence definitions render successfully**, isolating the cause. [Official sequence syntax](https://mermaid.js.org/syntax/sequenceDiagram.html#entity-codes-to-escape-characters).

The corrected sources use commas in messages, quoted flowchart labels, explicit line breaks and shorter wording. The system diagram uses a vertical layout; sequence labels wrap rather than forcing a very wide page. These changes preserve the workflow and include the current MVP team actor and Freshdesk demo boundary. Static SVG embeds remove dependence on the Markdown viewer's Mermaid version. [Flowchart syntax](https://mermaid.js.org/syntax/flowchart.html), [sequence configuration](https://mermaid.js.org/config/schema-docs/config-defs-sequence-diagram-config.html).

## Verified artifacts

All three final `.mmd` files parsed and rendered into SVG with CLI 12.0.0. PNG previews of those same definitions were also rendered and visually inspected: labels were legible, optional/alternative paths were distinct, and no text was clipped. The renderer configuration uses a neutral theme, wrapped sequence messages and SVG text labels for the flowchart.

- [System overview](system-overview.svg) — [source](system-overview.mmd)
- [Catalog workflow](catalog-flow.svg) — [source](catalog-flow.mmd)
- [Customer workflow](customer-flow.svg) — [source](customer-flow.mmd)

This verifies the documentation diagrams. It does not establish app accessibility conformance, human usability or production integration.

## Regeneration

From the repository root, use the [official Mermaid CLI](https://github.com/mermaid-js/mermaid-cli) pinned to the verified version:

```bash
npx --yes --registry=https://registry.npmjs.org --package=@mermaid-js/mermaid-cli@12.0.0 mmdc \
  -c docs/diagrams/render-config.json \
  -i docs/diagrams/system-overview.mmd \
  -o docs/diagrams/system-overview.svg -b white
```

Repeat with `catalog-flow` and `customer-flow`. The CLI requires a supported Chrome/Puppeteer browser. To use an existing browser, provide its executable path in a local Puppeteer JSON configuration using the CLI's `-p` option. Inspect rendered output after editing sources; a successful parse alone does not prove readable layout. Keep local browser paths and temporary previews out of the repository.
