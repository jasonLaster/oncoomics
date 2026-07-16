# Viewer v2 design pass 3: Diagnostic Inspector

## North star

The third pass makes the right rail earn its width. A routine run still opens with compact execution context, but a deliberate log selection turns that rail into a diagnostic surface with the parsed event, provenance, and untouched payload. The central ledger stays calm, compact, and spatially stable.

This pass combines the existing Sequencer Console direction with:

- the dark UI redesign loop's screenshot-reference-implementation-verification cycle;
- [Impeccable's AI slop catalog](https://impeccable.style/slop/) as a guard against card stacks, side stripes, decorative chrome, tiny unreadable type, and motion for its own sake;
- Emil Kowalski's design-engineering guidance for frequency-gated motion, spatially consistent drawers, interruptible transform/opacity transitions, and focus restoration;
- generated desktop and mobile edits anchored directly to the implemented pass-2 screens.

## Imagegen references

- [Desktop diagnostic inspector](../artifacts/screenshots/dark-audit/pass-3/references/desktop-diagnostic-inspector.png)
- [Mobile diagnostic inspector](../artifacts/screenshots/dark-audit/pass-3/references/mobile-diagnostic-inspector.png)

Mode: existing-screen edit. The references are directional inputs rather than pixel specifications; implementation preserves the actual event adapter model and browser behavior.

### Desktop prompt

```text
Edit the existing desktop operations dashboard into an implementable third design-pass reference. Preserve the Diana Compute Sequencer Console structure and dense dark scientific-instrument character. Show one deliberately selected structured event with a calm cobalt tint and subtle outline. Transform the right rail into an Event inspector containing title, severity/category/source, timestamp, message, structured metadata, provenance, raw payload, and Back to run. Keep rows readable and dense. No thick side stripe, gratuitous cards, gradients, glow, decorative charts, or pill overload.
```

### Mobile prompt

```text
Edit the existing mobile logs screen into an implementable third design-pass reference. Preserve the compact header, run context, search, filters, and infinite event stream. Show an explicit selected-event interaction and an Event inspector drawer opened from the right edge, leaving a spatial cue of the feed behind it. Include a reliable close action, readable message, parsed metadata, and raw payload. Do not auto-open details, reflow rows, use decorative motion, glow, gradients, giant text, or floating cards.
```

## Implemented decisions

| Before | After | Why |
| --- | --- | --- |
| The right rail always repeated run context | Direct event selection changes the same rail into a structured Event inspector | Context now follows the object the user is investigating. |
| Each event exposed an inline Raw event disclosure | Raw payload and parsed fields live in the inspector | Infinite-list rows never expand, so chronology and scroll anchoring remain stable. |
| Pass-2 routine rows were roughly 66-78px high | Desktop ledger rows are approximately 34px; mobile rows are 44px | Density comes from a single aligned summary line while touch remains operable. |
| Selection had no persistent visual state | The immutable `eventKey` drives a calm blue tint, subtle inset outline, and `data-selected` | Selection survives page prepends without confusing index drift and remains testable without relying on color. |
| A collapsed inspector had to be opened separately | The explicit Inspect action opens it without changing the stored rail preference | One intentional action reaches detail, and Back returns the prior layout. |
| Mobile detail could have expanded inline or used a bottom sheet | A right-edge modal sheet uses the established rail's spatial origin | Horizontal entry avoids competing with vertical feed scrolling and preserves the list geometry. |
| Closing detail could move the feed or lose keyboard context | Close restores the captured `scrollTop` and trigger focus with `preventScroll` | The user returns to the exact diagnostic position. |
| Pagination could mutate the feed behind an open mobile inspector | The observer pauses while an event is selected | The inspected event cannot shift under the user during modal review. |

## Motion and accessibility

- Desktop rail changes and event selection are instant; these are frequent operational actions.
- The existing mobile rail enters from its own edge in 220ms and exits in 160ms using transform only; reduced motion switches to a short opacity change.
- Event rows are semantic articles with a complete accessible label and an explicit button using `aria-controls` and `aria-expanded`.
- Mobile Event mode exposes `role="dialog"`, `aria-modal`, Escape dismissal, a scrim dismissal path, initial focus on Back to run, and focus restoration.
- Severity remains present as text in the inspector and in the event's accessible name; color is supplemental.

## Verification

Run from `tools/aws-job-viewer`:

```bash
npm test
npm run test:e2e
npm run lint
npx tsc --noEmit --incremental false
npx impeccable detect --json app
```

The deterministic suite covers event selection in both viewports, inspector structure, raw preservation, modal behavior, scroll restoration, and focus restoration. The opt-in production spec is documented in `viewer-v2.md` and must be run against `https://jobs.diana-tnbc.com` after release.

Final verified captures:

- [Desktop overview](../artifacts/screenshots/dark-audit/pass-3/desktop-overview.png)
- [Desktop compact ledger and Event inspector](../artifacts/screenshots/dark-audit/pass-3/desktop-logs.png)
- [Mobile overview](../artifacts/screenshots/dark-audit/pass-3/mobile-overview.png)
- [Mobile Event inspector](../artifacts/screenshots/dark-audit/pass-3/mobile-logs.png)

The capture run reported zero console errors, page errors, or framework overlays in either viewport.
