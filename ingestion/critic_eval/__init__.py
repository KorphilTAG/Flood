"""Offline RAGAS citation-quality evaluation harness for the historical critic.

Runs a fixed, checked-in sample of representative trainee plans
(`fixtures/sample_plans.json`) through the real `critic.service.run_critique`
(real retrieval, real OpenAI generation) and scores the resulting citations
with RAGAS's faithfulness and context-precision metrics -- a check for
whether a cited chunk is actually the *right* evidence for the claim next to
it, distinct from `critic.validator`'s existence-only check (see
`pipeline/features/citation-quality-eval/spec.md`).

Only this package's own plumbing (loading samples, calling the critic,
reshaping a `CritiqueResponse` into RAGAS's input shape, formatting a report)
is offline-testable. Producing an actual score requires a real
`OPENAI_API_KEY`, real network access, and a real built AAR corpus -- see
`ingestion/README.md`.
"""
