# Memory Extractor

Convert one episode into structured memory candidates.

Return strict JSON with:
- `summary`
- `entities`
- `facts`
- `relations`

Rules:
- Keep provenance to the source episode.
- Separate stable facts from transient chatter.
- Mark uncertain items with lower confidence.
