# xWiki

The main entrypoint is
`XWikiService`, designed for FastAPI backends, notebooks, task runners, and other
applications.

## Capabilities

- **Service API**: Use `XWikiService` for end-to-end orchestration (`ingest`, `compile`,
  `ask`, `lint`).
- **Workspace layout**: Standard runtime folders `inbox/`, `raw/`, `wiki/`, `.xwiki/`.
- **SQLite storage**: One database per workspace at `{workspace}/.xwiki/xwiki.sqlite`.
- **Retrieval**: Document search and wiki entity search with FTS5 and fallback.
- **QA**: Wiki-first, evidence-driven answers.
- **Linting**: Structural checks and optional LLM-based knowledge lint.

## Installation

Python 3.10 or newer is required. Create an isolated environment, then install
the package from the repository root:

```bash
python -m venv .venv
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
# macOS/Linux: source .venv/bin/activate
python -m pip install -e .
python -m xwiki --help
```

Runtime dependencies and version bounds are defined in `pyproject.toml`.
`constraints-tested.txt` records the exact dependency versions verified on Windows
with Python 3.14. Reuse that snapshot with
`python -m pip install -c constraints-tested.txt -e ".[test,build]"`.
It is a tested constraints snapshot, not a universal cross-platform lockfile.
CI tests Python 3.10 and 3.14 on both Windows and Linux using the declared bounds.
`python -m pip install -r requirements.txt` remains a compatible shortcut.
Only the chat client, schema validation and environment loader are required;
browser automation and HTTP server dependencies are installed by host applications
when needed. For tests use `python -m pip install -e ".[test]"`. For distribution
builds use `python -m pip install ".[build]"` followed by `python -m build`.
The installed `xwiki` shortcut calls the same entrypoint as `python -m xwiki`;
use the module form on managed Windows machines that block generated executables.
Builds include the `xwiki` package; private settings, runtime knowledge bases,
evaluation outputs and tests are excluded from the installed package.
Source archives additionally contain the tests, synthetic fixtures and evaluation
scripts. Verify both distributions with `python scripts/check_distributions.py dist`.

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

## AI maintenance

Use the service API or the JSON CLI to maintain knowledge without a frontend.
The default CLI command reports status; it does not ingest or compile anything.

```bash
python -m xwiki --workspace data/my_kb status
python -m xwiki --workspace data/my_kb ingest
python -m xwiki --workspace data/my_kb compile
python -m xwiki --workspace data/my_kb sources --status failed
python -m xwiki --workspace data/my_kb list --limit 20
python -m xwiki --workspace data/my_kb search "碳排放"
python -m xwiki --workspace data/my_kb search "碳排放" --kind documents
python -m xwiki --workspace data/my_kb read "碳排放"
python -m xwiki --workspace data/my_kb read-source DOCUMENT_ID 1 2
python -m xwiki --workspace data/my_kb update --input change.json --preview
python -m xwiki --workspace data/my_kb update --input change.json
python -m xwiki --workspace data/my_kb revisions "碳排放"
python -m xwiki --workspace data/my_kb lint
```

An update JSON file contains:

```json
{
  "name": "碳排放",
  "content": "来源支持的定义与条件 [DOCUMENT_ID p.1]",
  "base_version": "VERSION_RETURNED_BY_READ",
  "reason": "根据新增来源补充适用条件",
  "domain": "环境",
  "attributes": {"适用条件": "原文支持的条件"},
  "sources": ["DOCUMENT_ID"],
  "citations": [
    {"document_id": "DOCUMENT_ID", "page_no": 1, "quote": "逐字原文片段"}
  ]
}
```

Use `base_version: null` only to create a new entity. Existing entities require
the version returned by `read`; stale versions are rejected. `--preview` validates
the update and returns a diff without writing an entity or revision. Rollback
creates another revision and revalidates its citations:

```bash
python -m xwiki --workspace data/my_kb rollback "碳排放" REVISION_ID --base-version CURRENT_VERSION --reason "恢复经核验的旧版"
```

The Python equivalents are `read_entity`, `update_entity`, `entity_revisions`,
`rollback_entity`, and `list_documents`. `MaintenanceTools` exposes these same
operations for integrations. CLI results are JSON envelopes with `ok` and
`result` or `error`; failed ingest/compile batches return a nonzero exit code
and include individual failures in `stats.errors`.

SQLite remains the authoritative store in this version. Markdown files are
generated projections, not an independently editable source of truth. Use the
maintenance tools to keep database and files synchronized. External Markdown
edits are detected and preserved; subsequent writes fail until reconciled.
`read` includes `external_markdown` when a tracked file differs, and `lint`
reports the mismatch. New filenames include identity digests to avoid collisions;
unchanged legacy generated files retain their paths when first updated.

Ingestion archives a verified copy before indexing and only removes an unchanged
inbox input after success. Failed inputs remain retryable. Identical indexed
content is skipped; unsupported files remain in the inbox. Compilation skips
unchanged documents with the same compiler/model version; use `compile --force`
to explicitly rebuild. Each document's prepared entity changes and completion
state are saved together. Failures are recorded and other documents can continue.
Duplicate active runs are skipped, and abandoned run claims expire after one hour.

Generated consensus requires validated document/page/verbatim-quote citations.
Manual pages may start without evidence, but lint flags them. Citation validation
checks source identity and quote location; it does not prove that every claim is
supported or detect all factual errors. Answers expose `citation_status` and
warnings for missing or unknown references; they are never automatically written
back into the Wiki. Source count counts distinct documents. Chinese retrieval
uses lexical matches and bigram fallback, not semantic equivalence.

Normal write failures restore earlier files and roll back database changes.
Abrupt process termination can leave a generated file out of sync; hash checks
detect this rather than silently overwriting it. Entity contexts exceeding
120,000 characters fail explicitly instead of silently dropping source evidence.

## Wiki articles and small-model maintenance

Wiki articles retain complete Markdown bodies and short summaries. Summaries
are discovery cards, not a separate knowledge store. Stable page IDs support
links and backlinks. Existing entity APIs, source citations, and revisions remain
compatible; database startup upgrades existing records in place.

```python
created = service.update_page(
    "雨水收集", "## 用途\n收集屋顶雨水。", summary="雨水收集的方法与维护",
    base_version=None, reason="建立文章",
)
page = service.read_page("雨水收集")  # Also accepts its stable page ID.
cards = service.page_cards(limit=20)
links = service.page_links(page["page"]["id"])
```

Related pages are supplied as stable IDs through `related=[...]`. Article
updates use the same version, citation, preview, and revision checks as entities.
Unchanged writes preserve the existing version without creating redundant
revisions. The legacy compiler remains available; use `maintain` for the new
article-oriented, model-decided workflow.

```bash
python -m xwiki --workspace data/my_kb maintain --limit 2 --preview
python -m xwiki --workspace data/my_kb maintain --limit 2
python -m xwiki --workspace data/my_kb tasks
python -m xwiki --workspace data/my_kb read-page "雨水收集"
python -m xwiki --workspace data/my_kb write-page --input article.json --preview
```

`article.json` uses `title`, `body`, `summary`, `base_version`, `reason`, and
optional `sources`, `citations`, `domain`, and `related` fields. Preview checks
an article edit without writing it. Maintenance preview calls the model and
records discovery tasks, but does not archive inputs or save articles; its
returned plan is a proposal, not a saved edit.

The maintenance model sees a bounded card index, selects at most five existing
articles, then proposes up to three writes with at most one new article per
task. It decides whether to retain an incoming source and whether an article
needs creating or updating. Writes require retained evidence. Source hashes,
version checks, citations, and filesystem integrity are handled by code rather
than generated by the model. A model may retain a useful source without creating
an article. Sources it chooses not to retain stay in the inbox under cooling;
they are not physically deleted.

Automatic maintenance conservatively preserves existing factual sentences and
their precise citations. Headings, whitespace, Markdown emphasis and citation
formatting may change; rewriting or removing old factual text is rejected before
archiving the incoming source. Conflicting new evidence must be added alongside
the old statement for review. This text guard does not establish semantic truth:
safe paraphrases may also be blocked, and very short statements are not covered.
Deliberate corrections remain possible through version-checked manual page edits.
New pages are rejected when at least 80% of their extracted factual sentences
already occur in an existing page. This detects near-copy duplicates across
different titles, not arbitrary semantic duplicates. Discovery searches source
content as well as its filename.
Invalid model-selected page IDs get one bounded correction attempt, then fail
without saving articles. The live smoke report records provider method calls
for creation, immediate cooling, and incremental updates (not HTTP retry counts).

```bash
python scripts/evaluate_maintenance.py
python scripts/smoke_maintenance.py --env-file .env.test.local --update
```

The former scores deterministic write guards against gold maintenance plans and
writes `data/evaluation/maintenance-safety.json`; the latter checks a real model's
new-page and incremental-update behavior with synthetic sources. Their scores
must not be interpreted as broad model maintenance accuracy.

Tasks persist in SQLite. Stable/no-change checks increase the next interval
from hours up to seven days; changed inputs reset source cooling. Article edits
reschedule review, and newly created articles initially wait one hour. Failed
transient failures retry after five minutes, then ten minutes. Three consecutive
failures suspend the task in `review`. Invalid plans, lost facts, invalid evidence,
duplicate pages and missing inputs enter `review` immediately, preserving the
generated plan when available. Running tasks use exclusive claims with a one-hour
abandoned-claim timeout. `--force` bypasses cooling but never an active claim.
It also never resumes a `review` task. Inspect `tasks`, correct the source or edit
the article, then use `retry-task TASK_ID --fingerprint CURRENT_FINGERPRINT` for
an explicit retry; retry regenerates and validates the plan rather than approving
an unsafe proposal. Changed source fingerprints resume discovery automatically.
Search and reading remain available during cooling. No background daemon or
automatic deletion is enabled; invoke `maintain` when appropriate.

The input source limit is 16,000 characters and the selected maintenance context
limit is 32,000 characters. Oversized inputs fail explicitly and remain available
for splitting. Discovery currently considers up to 50 cards and 10 lexical
matches. This is intended for small Wikis, not exhaustive library-wide planning.

Configure an OpenAI-compatible chat provider using `OPENAI_API_KEY`,
`OPENAI_BASE_URL`, and `OPENAI_MODEL`, or aliases `llmAPI_KEY`, `API_BASE_URL`,
and `MODEL_NAME`. Private test settings can be loaded explicitly:

```bash
python -m xwiki --env-file .env.test.local --workspace data/test_kb maintain
python scripts/smoke_maintenance.py --env-file .env.test.local
python scripts/smoke_maintenance.py --env-file .env.test.local --update
```

The smoke check sends synthetic rainwater-system material to the configured
provider and uses a temporary Wiki. It is opt-in and is not part of unit tests.
The `--update` check also adds a second source and verifies that the existing
article gains the new information while retaining its earlier maintenance facts.
`XWIKI_LLM_MAX_OUTPUT_TOKENS` defaults to 4096; compatible endpoints without
JSON Schema support fall back to text JSON with local schema validation. Set
`XWIKI_STRUCTURED_MODE=json` to use locally validated JSON directly with providers
whose constrained decoding is slow. Configure
a model within your desired parameter budget; the application cannot infer
parameter count from an arbitrary provider alias. Retrieval remains lexical;
no embedding provider is contacted by this workflow.

## Tests

Automatic maintenance validates all quoted source text before archiving inputs,
then reviews proposed body lines, headings and summaries against those quotes.
The reviewer also receives up to 300 characters around each quote from the actual
source page, so a clipped quote cannot by itself remove nearby negation or
conditions. Context is bounded and may omit distant document-wide assumptions.
Exact source sentences need no additional review call. Paraphrases and combined
claims use a bounded model review (up to 24 non-verbatim units and 24,000 context
characters), checking subjects, numbers, units, negation, conditions and exceptions.
Explicit inline references must refer to the plan's evidence. Unsupported claims,
missing decisions or invalid supporting IDs suspend the task before article writes.
Reports are retained in task `review_json` alongside the proposed `plan_json`.
This review is fallible model judgement, not proof of semantic correctness; manual
page edits and the legacy compiler do not use this automatic maintenance gate.

```bash
python scripts/evaluate_evidence.py --env-file .env.test.local
```

This opt-in synthetic gold evaluation scores supported paraphrases and false
claims with incorrect numbers, units, prohibitions, exceptions and thresholds.
Provider/schema failures count as failures rather than successful rejections.
The result is written to `data/evaluation/evidence-support.json`.

`python scripts/evaluate_continuous.py` runs 25 sequential rounds with a scripted
planner, including incremental additions, blocked destructive updates, forced
review attempts, changed inputs, transient failure recovery, and repeated stable
reviews. Results at `data/evaluation/continuous-maintenance.json` include call
counts, retained facts and revision growth. This measures scheduling and write
integrity; it does not score a real model's comprehension or editing quality.

Gold-answer retrieval and question-answer evaluation uses a synthetic Chinese
corpus with frequency, restrictions, numeric facts, paraphrases and missing
evidence cases. It is independent of the unit-test pass count:

```bash
python scripts/evaluate_wiki.py
python scripts/evaluate_wiki.py --live --env-file .env.test.local
```

Reports are written to `data/evaluation/latest.json`. Offline mode measures
document Hit@3 and reciprocal rank. Live mode also measures answer keyword-group
accuracy and citation locator validity. Unknown-answer cases contribute to
answer accuracy but not retrieval or citation denominators. This small corpus
does not measure semantic entailment or general maintenance quality. Supply
`--dataset` and `--output` to compare repeated runs on another gold dataset with
the same JSON schema; keep corpus and question set unchanged across comparisons.

Answer citations with explicit verified document/page pairs (for example
`[document_id 1]`) are normalized to `[document_id p.1]`. Responses report
`citation_repairs` when normalization occurs. Missing citations are not invented;
unknown document IDs and unsupplied pages remain invalid, including shorthand
citations mixed with valid references. Locator validation does not prove that
the cited passage supports every generated claim.

```bash
pytest
```

Tests use temporary workspace fixtures, so they do not depend on your local production
workspace data.
# 自动质量检查

公开示例见 [虚构社区花园](examples/garden/README.md)。运行 `python scripts/demo_wiki.py` 可离线复现来源摄取、文章增量维护、引用校验、检索、冷却和回滚，并保存 JSON 报告。模拟维护器的结果不代表真实模型成绩。

每次推送和 PR 都运行 CI：Windows/Linux 的 Python 3.10、3.14 测试，最低 80% 语句覆盖率，以及 Ruff、完整包的基础类型检查、构建内容审计和独立 wheel 安装检查。CI 不需要模型密钥，使用离线及模拟模型测试；真实模型评估仍单独运行。

本地复现：

```bash
python -m pip install ".[test,quality,build]"
python -m ruff check xwiki scripts tests
python -m mypy
python -m pytest -q --cov=xwiki --cov-report=term-missing --cov-report=xml
python -m build
python scripts/check_distributions.py dist
```
