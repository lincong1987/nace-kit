# nace-kit

**Multi-key client, presets, CLI and MCP server for the [nace.ai Drex API](https://console.nace.ai) — classify text or JSON with calibrated probabilities, from Python or any MCP-speaking agent.**

English | [简体中文](docs/readme/README.zh-CN.md)

[![PyPI](https://img.shields.io/pypi/v/nace-kit)](https://pypi.org/project/nace-kit/)
[![Python](https://img.shields.io/pypi/pyversions/nace-kit)](https://pypi.org/project/nace-kit/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/lincong1987/nace-kit/actions/workflows/ci.yml/badge.svg)](https://github.com/lincong1987/nace-kit/actions/workflows/ci.yml)

> [!IMPORTANT]
> **Community project — not affiliated with or endorsed by Nace AI.** Install only from PyPI ([`nace-kit`](https://pypi.org/project/nace-kit/)) or GitHub ([`lincong1987/nace-kit`](https://github.com/lincong1987/nace-kit)); similar names are not this project. For the official Python SDK and MCP server see [`nace-sdk`](https://pypi.org/project/nace-sdk/) and [`nace-mcp`](https://pypi.org/project/nace-mcp/).

## Contents

- [Why this exists](#why-this-exists)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Comparison with the official SDK](#comparison-with-the-official-sdk)
- [Question types](#question-types)
- [Document pipeline](#document-pipeline)
- [MCP for agents](#mcp-for-agents)
- [CLI](#cli)
- [FAQ](#faq)
- [Contributing](#contributing)
- [License](#license)

## Why this exists

Drex answers typed questions about any text or JSON with calibrated probabilities — great for routing tickets, triaging issues, grading replies. The official `nace-sdk` wraps the whole API; nace-kit wraps the **operations** around it:

- **Key pool** — several API keys work as one. A dead key (401) or an exhausted quota (429) fails over to the next key mid-request.
- **Response cache** — Drex answers are deterministic, so identical requests are served from an LRU cache instead of billed again.
- **Usage metering** — calls and tokens, per key, always visible in `client.usage`.
- **Presets & typed answers** — `urgency()`, `sentiment()`, `severity()`, `priority()` out of the box; pydantic questions and responses throughout.
- **Document pipeline** — parse / extract / ground over the official SDK with the same key pool (`[docs]` extra).

## Quick start

Requires Python 3.11+ (Windows / macOS / Linux) and one or more API keys from the [console](https://console.nace.ai).

```bash
pip install nace-kit        # or: uv add nace-kit / uvx nace-kit for one-off use
export NACE_API_KEYS="nace_sk_...,nace_sk_..."   # pool of keys; NACE_API_KEY for one
```

```python
from nace_kit import NaceClient, presets

client = NaceClient()  # defaults to drex-latest

# binary question -> probability of yes
r = client.classify("Help! My payouts have been failing for 3 days.", presets.urgency())
r.answers["is_urgent"].noul             # 0.7161

# state can be any JSON; questions batch into ONE request
r = client.classify(
    {"ticket": "#42", "subject": "payout failure", "days_stuck": 3},
    [presets.urgency(), presets.severity(), presets.priority()],
)

client.models()   # available models; also a cheap key health check
client.usage      # {'nace_sk_wn…': {'calls': 12, 'input_tokens': 300, ...}}
```

Async works the same: `from nace_kit import AsyncNaceClient`.

## How it works

| Failure | Behaviour |
|---|---|
| 401 / 403 (bad or dead key) | rotate to the next key immediately |
| 429 (quota), several keys configured | rotate to the next key immediately |
| 429, single key configured | retry the same key with backoff (honours `Retry-After`) |
| 408 / 5xx / network / timeout | retry the same key — exponential backoff + jitter, `Retry-After` aware, 30 s total budget — then rotate |
| 4xx (payload rejected) | raise immediately, no retries (`NaceBadRequest`) |

Keys are validated at construction (`nace_sk_` + 43 chars); retries (`max_retries`, `backoff_*`, `retry_budget`), cache size and timeouts are constructor parameters.

## Comparison with the official SDK

| | official `nace-sdk` | `nace-kit` |
|---|---|---|
| Classification API (all three question types, any-JSON `state`, models listing, typed objects) | ✅ | ✅ |
| **Multi-key pool with failover** | ❌ single key | ✅ |
| **LRU response cache** | ❌ | ✅ |
| **Per-key usage metering** | ❌ | ✅ |
| Backoff retries, `Retry-After`, budget | ✅ | ✅ (combined with rotation) |
| Question presets | ❌ | ✅ |
| Document pipeline (upload/parse/extract/jobs) | ✅ | ✅ via the official SDK (`[docs]` extra) |
| `nace login` credential file | ✅ | ❌ env vars |
| CLI + MCP server in one package | ❌ separate `nace-mcp` | ✅ |

## Question types

| Type | `criteria` | Answer |
|---|---|---|
| `noul` | optional `{"true": "…", "false": "…"}` outcome descriptions | `{"noul": 0..1}` — probability of yes |
| `choice` | `{label: description}` — one label wins | `{"choice": "billing", "probabilities": {...}, "confidence": …}` |
| `score` | `["low", "medium", "high"]` — ordered levels | `{"score": 1.31, "legend": […], "probabilities": {...}, "confidence": …}` |

```python
from nace_kit import presets as p

p.noul("Refund?", true="wants money back")
p.choice("What is this?", {"billing": "payments", "technical": None})
p.score("How angry?", ["calm", "annoyed", "angry", "furious"])
```

Pick your own threshold on the probabilities rather than treating them as a verdict.

## Document pipeline

The document operations wrap the official `nace-sdk` (MIT) — their API surface, our key pool on top:

```bash
pip install "nace-kit[docs]"
```

```python
from nace_kit import DocsClient

docs = DocsClient()   # same NACE_API_KEYS pool; rotates on 401/429
job = docs.parse("https://example.com/report.pdf",
                 output={"formats": ["markdown"]}, wait=120)
job.result["document"]["markdown"]
```

`parse` / `split` / `classify_document` / `extract` / `ground` create jobs and (with `wait`) poll them to completion; `docs.job(id)`, `docs.wait(id)`, `docs.jobs()` manage them afterwards. Every create is idempotency-keyed, so a key rotation mid-call never bills a second job. `AsyncDocsClient` mirrors everything.

## MCP for agents

One registration, every project. ZCode (`~/.zcode/cli/config.json` → `mcp.servers`):

```json
"nace": {
  "type": "stdio",
  "command": "uvx",
  "args": ["nace-kit-mcp"],
  "env": { "NACE_API_KEYS": "nace_sk_...,nace_sk_..." }
}
```

Claude Desktop / Cursor: same shape under `mcpServers`.

Tools: `classify` (full batch interface), `ask` (single question over noul / score / choice), `list_models`, and — with the `[docs]` extra installed — `parse_document`, `extract_data`, `get_document_job`.

Prefer a skill? `nace-kit --install-skill` copies an [Agent Skill](https://agentskills.io) (`SKILL.md`) to `~/.agents/skills/` (or `--claude` for `~/.claude/skills/`), so agents get usage guidance — question phrasing, batching, thresholds — even without the MCP registration.

## CLI

```bash
nace-kit "Camera 3 is showing a black screen." --no-cache
nace-kit "..." --ask "How angry is the user?" --kind score --levels calm annoyed angry furious
nace-kit "..." --ask "What is this about?" --kind choice --options billing:"payment issues" technical:"bugs"
nace-kit --models
```

## FAQ

**Is the cache safe?**
Drex answers are deterministic for identical input (same model, state, questions), so caching is exact. Pass `cache_size=0` to disable.

**Which model does it call?**
`drex-latest` by default, which nace.ai moves forward on announced dates; pin with `NaceClient(model="drex-v2.0")` if you need reproducibility.

**Where do keys go?**
`NACE_API_KEYS` (comma-separated pool) or `NACE_API_KEY`. For agents, put them in the MCP server's `env` block. Never in code.

## Contributing

Issues and PRs are welcome at [lincong1987/nace-kit](https://github.com/lincong1987/nace-kit).

```bash
uv sync            # httpx, mcp, pytest
uv run pytest -q   # unit tests — no network or keys needed
```

## License

[MIT](LICENSE) © nace-kit contributors.
