# xWiki

xWiki has been refactored into an importable service package. The main entrypoint is
`XWikiService`, designed for FastAPI backends, notebooks, task runners, and other
applications.

This repository no longer relies on the legacy CLI scripts such as `ingestor.py`
or `searcher.py`; all primary flows are exposed through the service API.

## Capabilities

- **Service API**: Use `XWikiService` for end-to-end orchestration (`ingest`, `compile`,
  `ask`, `lint`).
- **Workspace layout**: Standard runtime folders `inbox/`, `raw/`, `wiki/`, `.xwiki/`.
- **SQLite storage**: One database per workspace at `{workspace}/.xwiki/xwiki.sqlite`.
- **Retrieval**: Document search and wiki entity search with FTS5 and fallback.
- **QA**: Wiki-first, evidence-driven answers.
- **Linting**: Structural checks and optional LLM-based knowledge lint.

## Installation

```bash
pip install -r requirements.txt
```

Set these environment variables in `.env` (or pass config values explicitly):

- `OPENAI_API_KEY`
- `OPENAI_MODEL` (default: `gpt-4.1`)
- `OPENAI_BASE_URL` (optional, for custom API gateway)

## Project Layout

```text
xwiki/
  __init__.py
  service.py
  config.py
  converter.py
  indexer.py
  searcher.py
  agent/
    compiler.py
    query.py
    linter.py
    tools.py
scripts/
  smoke_service.py
tests/
```

## Quick Start

```python
import asyncio
from xwiki import XWikiConfig, XWikiService


async def main() -> None:
  service = XWikiService(XWikiConfig(workspace="data/my_kb"))
  await service.ingest_inbox()
  await service.compile_knowledge()
  result = await service.ask("What are the key points of this KB?")
  print(result["answer"])


asyncio.run(main())
```

### Common Commands

```bash
# Run a smoke check
python scripts/smoke_service.py

# Print current service status
python - <<'PY'
from xwiki import XWikiConfig, XWikiService

print(XWikiService(XWikiConfig(workspace="data/my_kb")).status())
PY
```

## Import Markdown Documents

Drop your Markdown files into `{workspace}/inbox/`, then run:

1. `await service.ingest_inbox()` to move files to `raw/` and index them.
2. `await service.compile_knowledge()` to generate wiki pages and entities.

If you keep source files in `output_md/`, copy them into the workspace inbox and
run the smoke script:

```bash
python scripts/smoke_service.py
```

> Note: `output_md/` is ignored by git, but it can still be used as a runtime input
> directory.

## Tests

```bash
pytest
```

Tests use temporary workspace fixtures, so they do not depend on your local production
workspace data.
