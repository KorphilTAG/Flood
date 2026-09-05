# Manually verified source documents

This directory holds instructions and an example only. It is not a source
discovery tool, and no document listed here has been located, downloaded, or
declared authoritative by the code.

Before a production corpus build, a designated human curator must:

1. Locate and save a text-extractable PDF from its authoritative publisher.
2. Verify that the saved file, publisher, title, and canonical URL are the
   intended source. Scanned PDFs need a human-prepared text/OCR follow-up and
   re-verification before admission; the pipeline does not run OCR.
3. Calculate the saved file's SHA-256 and record it with the curator name,
   ISO-8601 verification time, and a meaningful verification note.
4. Mark the entry's `status` as `verified`, then run `python -m aar validate`
   before building. The production validator requires all nine categories in
   `manifest.example.json`.
5. Add only human-reviewed, page-bounded annotations. Do not place inferred
   tactics, outcomes, lessons, or generated summaries in this manifest.

Keep real PDFs and verified manifests under ignored `data/aar/`; do not commit
them here. Product-generated AARs must remain in a separate collection and are
prohibited from this retrieval corpus, so future retrieval cannot cite its own
output.

`manifest.example.json` is deliberately non-production: its URLs, paths,
checksums, and `pending` statuses are placeholders. Replace every placeholder
after manual verification rather than attempting to validate or build it.
