# Feature pipeline

Plan (Fable) → developer (Sonnet).

Invoke it from any of:

- Cursor or Claude Code: `/pipeline <feature>`
- Codex: type `$` and pick **Feature Pipeline**, or `$pipeline <feature>`. `/skills` also lists it. Start a new Codex thread if it was already open before this skill existed.

Example: `/pipeline stub the four JSON contracts`

Artifacts land in `pipeline/features/<slug>/` as `spec.md` and `changes.md`.
