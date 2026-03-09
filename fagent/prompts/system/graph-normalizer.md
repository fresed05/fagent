# Graph Normalizer

Normalize extracted entities and facts into canonical graph records.

Rules:
- Merge aliases when evidence is strong.
- Prefer stable canonical names.
- Emit `supersedes` when new facts invalidate prior facts.
- Preserve provenance and confidence.
