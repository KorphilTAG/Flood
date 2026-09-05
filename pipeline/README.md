# Feature pipeline

Plan (Fable) → developer (Sonnet) → reviewer (Sonnet).

Invoke it from any of:

- Cursor or Claude Code: `/pipeline <feature>`
- Codex: `$pipeline <feature>`

Example: `/pipeline stub the four JSON contracts`

Artifacts land in `pipeline/features/<slug>/` as `spec.md`, `changes.md`, and `review.md`.
