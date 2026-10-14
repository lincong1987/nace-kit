---
name: nace-kit
description: Classify text or JSON with the nace.ai Drex API — calibrated yes/no
  scores (noul), label routing (choice), ordered ratings (score); presets for
  urgency/sentiment/severity/priority; parse and extract from documents. Use
  when scoring, routing, triaging or grading text, or when a document needs
  parsing or field extraction.
---

# nace-kit — Drex classification for agents

Prefer the MCP tools (`classify`, `ask`, `list_models`, and with the docs extra
`parse_document`, `extract_data`) when they are available in this session.
Otherwise use the CLI or Python below.

## Setup (once)

- Needs `NACE_API_KEYS` (comma-separated key pool) or `NACE_API_KEY` in the environment.
- No install needed: `uvx nace-kit ...`. Persistent: `pip install nace-kit`.
- Document operations additionally need `pip install "nace-kit[docs]"`.

## Classifying via CLI

```bash
uvx nace-kit "Help! My payouts have been failing for 3 days."            # urgency preset (noul 0..1)
uvx nace-kit "TEXT" --ask "How angry is the user?" --kind score --levels calm annoyed angry furious
uvx nace-kit "TEXT" --ask "What is this about?" --kind choice --options billing:"payment issues" technical:"bugs"
uvx nace-kit --models                                                     # key health check
```

Output JSON: `answers.<name>.noul` / `.choice` / `.score`, each with
`probabilities` and (except noul) `confidence`.

## Choosing the question type

- Yes/no decision → `noul` (fastest, ~100 ms). Ask one concrete question —
  "Does this convey urgency?", never "analyze this text".
- Routing among labels → `choice`; `criteria` maps each label to a short description.
- Ordered intensity → `score`; `criteria` lists levels from low to high.

## Batching (Python — one upstream call for many questions)

```python
from nace_kit import NaceClient, presets

client = NaceClient()
r = client.classify(state, [presets.urgency(), presets.priority()])
r.answers["priority"].choice           # typed answers, IDE-completable
```

Custom questions:

```python
from nace_kit.types import Choice, Score
Choice(instructions="Topic?", criteria={"billing": "payments", "technical": None})
Score(instructions="Severity?", criteria=["minor", "moderate", "major", "critical"])
```

`state` may be any JSON object, not just text — pass structured records directly.

## Reading results

Probabilities are calibrated, not verdicts: pick a threshold (e.g. `noul > 0.8`
means urgent) instead of trusting a single answer blindly.

## Documents (needs the `[docs]` extra)

```python
from nace_kit import DocsClient

docs = DocsClient()
job = docs.parse("https://example.com/report.pdf", output={"formats": ["markdown"]}, wait=120)
job.result["document"]["markdown"]
```

Also `docs.extract(url, schema={...})` for structured fields; job state via
`docs.job(id)` / `docs.wait(id)`.

## Cost care

Identical requests are served from an LRU cache. Pass `--no-cache` (CLI) or
`cache_size=0` (Python) when you need a genuinely fresh call.
