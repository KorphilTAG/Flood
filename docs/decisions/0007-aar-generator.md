# 0007. Add an after-action-report generator on the LLM endpoint

Status: accepted, 2026-09-05.

## Context

The product's users include trainers and after-action reviewers who need an exportable, citation-backed decision log. The PRD delivers that as a raw export of session state. The team's assessment is that the after-action reporting on the July 2025 Kerr County flood was not thorough, and that a structured, evidence-linked AAR is both a genuine gap and an easy, demo-friendly addition. The pieces already exist: the session state holds every decision, every critique, and every citation, and the LLM critic already writes grounded prose.

## Decision

Add an AAR generator as a tool on the LLM endpoint. It runs at the end of a training session or a pre-deployment red-team, or on demand against the hindsight run of the real event.

Inputs, all from session state and the run store:

- The timeline of alerts and decision points with the trainee's plan at each.
- The impact JSON at each decision point, both the forecast the trainee saw (from `p`) and the hindsight truth for the same `t`, so the report can state what was foreseeable.
- The critic's objections and alternatives with their chunk and feature IDs.
- Hindcast skill for the session's `(p, t)` pairs, so the report is honest about the twin's own error.
- Search-area outputs where they were produced.

Output, a structured document in Markdown converted to PDF or DOCX on export:

1. Incident summary and scope of the review.
2. Timeline of hazard, warnings, and decisions.
3. For each decision point: situation as known at `p`, decision taken, projected consequence, actual or hindsight consequence, critique with citations.
4. What was foreseeable and when, drawn from the forecast-versus-hindsight comparison.
5. Lessons and recommendations, each tied to a citation or a feature.
6. Twin limitations and forecast skill for this session.
7. Appendix of every citation with source, page or paragraph, and chunk ID.

Rules:

- The output validator applies. Every factual claim cites an AAR chunk ID or a twin feature ID, and outputs that cite non-existent IDs are regenerated, not passed through.
- Generated reports are labelled as twin-grounded reconstructions, not official findings. This matters most when the generator is run against the real 2025 event.
- Generated AARs are stored in a separate, clearly labelled collection. They are never ingested into the retrieval corpus that grounds the critic, to avoid the corpus citing its own output.
- Structure the generated record in the same schema the AAR pipeline uses for source documents (hazard, phase, tactic, resources, outcome, lesson, citation), so a human reviewer can compare it directly with the historical record.

Priority: after Milestone 4 in the PRD and before the chatbot tab. Cost is low because it reuses the critic, the validator, and session state. It is a stronger demo close than a raw JSON export.

## Consequences

- The demo script gains a final step: the session ends, the AAR generates in under a minute, and the presenter opens it.
- Session state must retain enough per-decision-point detail to reconstruct the report after the fact; this is a small addition to contract 4.
- Running it against the real event produces a document that will be read as commentary on real people's decisions. The labelling rule above is not optional.

## Open questions

- Which AAR structure to follow: HSEEP-style exercise evaluation, ICS-style incident review, or the hybrid above. Start with the hybrid and adjust once a trainer has read one.
- Whether the report should include the map images for each decision point. Probably yes, rendered by the verifier's PNG helper.
