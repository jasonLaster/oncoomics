# Viewer v2 design pass 2: Sequencer Console

## North star

The second visual pass treats the viewer as a calm scientific instrument: a clinical-genomics run sheet crossed with a precision batch scheduler. The pipeline data supplies the visual identity through stage connectivity, chromosome channels, and event rhythm. Decorative DNA imagery, glow, and generic dashboard ornament are intentionally absent.

The pass draws on:

- [Impeccable's AI slop catalog](https://impeccable.style/slop/) for repeated-kicker, nested-card, tiny-type, side-accent, palette, and motion anti-patterns;
- Emil Kowalski's [`emil-design-eng`](https://github.com/emilkowalski/skills/tree/main/skills/emil-design-eng) skill for interaction timing and invisible correctness;
- Emil Kowalski's [`find-animation-opportunities`](https://github.com/emilkowalski/skills/tree/main/skills/find-animation-opportunities) skill for a frequency, purpose, speed, and function gate on motion;
- generated desktop and mobile references anchored to the implemented pass-1 screens.

## Imagegen references

- [Desktop Sequencer Console](../artifacts/screenshots/dark-audit/pass-2/references/desktop-sequencer-console.png)
- [Mobile event ledger](../artifacts/screenshots/dark-audit/pass-2/references/mobile-event-ledger.png)

The references are design inputs, not pixel specifications. They invent some icons and values, so the implementation borrows hierarchy, rhythm, color semantics, and density while preserving the viewer's real data model and accessible controls.

### Desktop prompt

```text
Use case: ui-mockup
Asset type: desktop dark-theme redesign reference for the Diana AWS genomics job viewer
Primary request: Redesign the current operational screen as a distinctive Sequencer Console, a calm clinical-genomics run sheet crossed with a precision batch scheduler.
Composition: preserve the three-region structure; use one continuous summary band, a connected six-stage workflow, a compact chromosome matrix, and a low-noise inspector.
Color: graphite and warm white; blue only for selected/running/progress; mint only for complete/live; amber warning; red failed; neutral queued.
Constraints: realistic data density; sans summaries and mono data; no marketing hero, DNA illustration, glow, gradient text, side-tab accents, nested cards, repeated kickers, or impossible UI flourishes.
```

### Mobile prompt

```text
Use case: ui-mockup
Asset type: mobile dark-theme redesign reference for the Diana AWS genomics log viewer
Primary request: Redesign the mobile logs screen as a compact clinical-genomics event ledger.
Composition: compact run context, attached tabs and command surface, readable structured events, quiet routine rows, semantic anomalies, and a thin anomaly map beside the feed.
Color: graphite and warm white; blue running/selected; mint complete/live; amber warning; red error; gray routine.
Constraints: 44px controls, 11-12px message text, no redundant INFO treatment, no dead space above logs, no compressed desktop microtype, glow, glass, card stack, or decorative imagery.
```

## Implemented decisions

| Before | After | Why |
| --- | --- | --- |
| Geist Sans and Mono across nearly every surface | IBM Plex Sans Condensed for the operational interface and IBM Plex Mono only for data | The narrower instrument face creates a domain-specific voice and preserves horizontal density without making body text tiny. |
| Running progress and successful completion both used mint | Cobalt blue means selected, running, and incomplete progress; mineral mint means complete or live | State can be read without interpreting context-specific reuse of one accent. |
| Narrative card followed by four separate metric cards | One continuous run deck with a summary band and four baseline-aligned facts | The deck reads as one object and removes unnecessary containment. |
| Six workflow tiles in a 3-by-2 grid | Six connected stages in one horizontal spine, adapting to a vertical spine on mobile | The workflow now communicates order and dependency instead of resembling a feature grid. |
| Chromosomes in long two-column rows | Compact four-channel desktop matrix and one readable mobile channel | The genomics domain becomes the visual system rather than decoration. |
| Repeated uppercase kicker above most section headings | Kicker labels remain only where they establish major workspace context | Fewer editorial labels produce a stronger and less generated hierarchy. |
| Logs used tiny four-column rows with a repeated INFO pill | Event ledger uses a time gutter, a small semantic mark, one strong summary, and readable payload | Density comes from information compression, not miniature type. |
| Severity used thick inset side accents and gradients | Calm row tint, title treatment, and a data-driven anomaly dot | Exceptions remain visible without the common rounded-card side-tab pattern. |
| The main panel could retain a prior vertical scroll offset when switching tabs | Tab and job changes reset the outer panel; the bounded feed owns log scrolling | Run context and controls remain attached to the stream and screenshots no longer begin in dead space. |
| Ambiguous rail chevrons | Panel-left and panel-right glyphs with the existing accessible names | Collapse affordances now describe the surface they control. |

## Motion gate

| Candidate | Purpose | Frequency | Decision |
| --- | --- | --- | --- |
| Mobile rail drawer | Spatial consistency | Occasional | Enter from its edge in 220ms with `cubic-bezier(0.32, 0.72, 0, 1)`; exit in 160ms with strong ease-out. |
| Toolbar and rail button press | Feedback | Tens per day | Subtle `scale(0.97)` for 130ms, restricted to compact chrome controls. |
| Skeleton shimmer | Loading feedback | Occasional | Retained normally; becomes static under reduced motion. |
| Tab switch | Core navigation | High | Rejected. Content changes instantly. |
| Infinite-scroll rows | Functional data | High | Rejected. Prepending must preserve scroll position without animation. |
| Progress values and chromosome bars | Functional data | High | Rejected. Motion would make changing evidence harder to read. |
| Job-list hover scaling | Repeated navigation | High | Rejected. Hover is a color-only affordance and is pointer-gated. |

All movement is disabled or reduced to opacity under `prefers-reduced-motion`. Desktop rail width changes remain instant to avoid layout animation and preserve perceived speed.

## Verification

Run from `tools/aws-job-viewer`:

```bash
npm test
npm run test:e2e
npm run lint
npx tsc --noEmit
npx impeccable detect --json app
```

The final browser captures live under `artifacts/screenshots/dark-audit/pass-2/` beside the generated references.
