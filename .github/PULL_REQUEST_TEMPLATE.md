<!-- Thanks for contributing to HEPHAESTUS! Please keep PRs focused and small where possible. -->

## Summary

<!-- What does this PR do, and why? Link any related issue: "Closes #123". -->

## Changes

<!-- Bullet the notable changes. -->
-

## How was this tested?

<!-- Commands you ran and what you observed. For UI changes, a screenshot helps. -->

## Checklist

- [ ] Backend gates pass: `cd backend && ruff check . && mypy --strict app tests && pytest -q`
- [ ] Frontend gates pass: `cd frontend && pnpm typecheck && pnpm test && pnpm build`
- [ ] No secrets (API keys, tokens) in code, tests, logs, or screenshots
- [ ] Docs/README updated if behavior or setup changed
- [ ] PR is focused on a single concern
