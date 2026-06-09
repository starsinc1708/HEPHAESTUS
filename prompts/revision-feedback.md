# HEPHAESTUS — Revision Feedback (re-implementation)

The validation funnel returned **needs_revision** for item `{{item_id}}`.
This is **attempt {{attempt}} of {{max_revisions}}**. Fix the blocking items below
WITHOUT discarding your previous changes — you are on the same branch, diff accumulates.

## Original proposal
{{proposal}}

## Acceptance
{{acceptance}}

## Blocking items (MUST fix all)
{{blocking}}

## Lens findings (verdict != approve)
{{lens_findings}}

## Rules
- Do not go out of scope (stay inside the item's touched files).
- Add or fix tests so they fail WITHOUT the production change.
- Keep prior correct changes; only address the blocking items.
- Commit when done (the driver will verify + re-validate).
