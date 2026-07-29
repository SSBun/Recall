# Recall Guide

[README](../README.md) · [简体中文指南](./GUIDE.zh-CN.md)

This guide covers installation, authentication, configuration, indexing, retrieval, the dashboard, the HTTP API, data management, troubleshooting, and development.

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Your first knowledge base](#your-first-knowledge-base)
- [Provider authentication](#provider-authentication)
- [Configuration](#configuration)
- [Indexing](#indexing)
- [Search and Ask](#search-and-ask)
- [Document management](#document-management)
- [Web dashboard](#web-dashboard)
- [Per-store daemon](#per-store-daemon)
- [HTTP API](#http-api)
- [Data, privacy, and backups](#data-privacy-and-backups)
- [Pi extension and agent integrations](#pi-extension-and-agent-integrations)
- [Troubleshooting](#troubleshooting)
- [Development](#development)

## Requirements

| Dependency | Supported version | Purpose |
|---|---:|---|
| Python | 3.11–3.13 | Recall CLI, Chroma, and embeddings |
| Node.js | 22.19+ | Built-in Pi SDK model bridge |
| uv | Current stable | Recommended environment and command runner |
| Model credentials | Provider dependent | Automatic tagging and `ask` |

Recall does not require the Pi CLI and does not read Pi's global configuration or credentials.

## Installation

Recall is currently installed from source:

```bash
git clone https://github.com/SSBun/Recall.git
cd Recall
uv sync
uv run recall --help
```

To install into the active Python environment instead:

```bash
python -m pip install .
recall --help
```

The first indexing or retrieval operation may download `Qwen/Qwen3-Embedding-0.6B`. Model files are cached by the underlying Hugging Face tooling.

## Your first knowledge base

The shortest complete setup is:

```bash
# 1. Connect ChatGPT Plus/Pro through Codex OAuth
uv run recall provider login openai-codex

# 2. Choose tagging and answer models
uv run recall config

# 3. Index a directory
uv run recall index ~/Documents/notes --recursive

# 4. Search
uv run recall search "deployment checklist"

# 5. Ask a grounded question
uv run recall ask "What is our deployment checklist?"

# 6. Open the dashboard
uv run recall dashboard
```

By default, Recall stores the complete Chroma database under `~/.local/share/recall/db/`. Use `--store /path/to/db` to create or select another independent knowledge store.

## Provider authentication

### ChatGPT Plus/Pro OAuth

Recall currently exposes an interactive OAuth login for `openai-codex`:

```bash
uv run recall provider login
# or
uv run recall provider login openai-codex
```

The interactive flow supports browser and device-code login. Credentials are saved to `~/.config/recall/auth.json` with restricted permissions.

```bash
uv run recall provider list
uv run recall provider logout openai-codex
```

### API keys

You can use provider-standard environment variables, for example:

```bash
export OPENAI_API_KEY="..."
uv run recall config set models.ask openai/gpt-4o-mini
```

Do not commit credentials. Recall-owned credentials live in `~/.config/recall/auth.json`; they are separate from `config.toml` and from Pi's global configuration.

### Available model names

Run the menu wizard and edit either model setting:

```bash
uv run recall config
```

Recall lists every model in its bundled Pi SDK model catalog for providers that are configured through Recall credentials or the current environment. The catalog is local; opening the model selector does not fetch a model list from a remote service. The actual model call still goes to the selected provider.

For scripts, any syntactically valid `provider/model` can be preconfigured:

```bash
uv run recall config set models.tag openai-codex/gpt-5.4-mini
uv run recall config set models.ask openai-codex/gpt-5.4
```

A model is usable only if its provider is configured and supports that model.

## Configuration

The optional configuration file is `~/.config/recall/config.toml`.

```bash
uv run recall config             # interactive setup menu
uv run recall config list        # print effective values
uv run recall config set search.limit 10
uv run recall config set models.tag openai-codex/gpt-5.4-mini
uv run recall config set models.ask openai-codex/gpt-5.4
```

Example TOML:

```toml
[models]
tag = "openai-codex/gpt-5.4-mini"
ask = "openai-codex/gpt-5.4"

[search]
limit = 5

[index]
concurrency = 4
```

| Setting | Meaning | Default | Precedence, highest first |
|---|---|---|---|
| `models.tag` | Model used by `index` and `retag` | `openai/gpt-4o-mini` | `--tag-model`, `RECALL_TAG_MODEL`, TOML, default |
| `models.ask` | Model used by `ask` | `openai/gpt-4o-mini` | `--model`, `RECALL_ASK_MODEL`, TOML, default |
| `search.limit` | Default chunks for `search` and `ask` | `5` | `--limit`, TOML, default |
| `index.concurrency` | Documents admitted to preprocessing at once | `4` | `--concurrency`, `RECALL_INDEX_CONCURRENCY`, TOML, default |

`config set` supports `models.tag`, `models.ask`, and `search.limit`. Edit TOML directly for `index.concurrency`. Writes are validated and atomic, and preserve unrelated TOML content.

The embedding model is intentionally not configurable. Every store uses normalized 1024-dimensional `Qwen/Qwen3-Embedding-0.6B` vectors. Changing that model requires rebuilding the complete store.

The store path has separate precedence:

```text
--store > RECALL_STORE > ~/.local/share/recall/db/
```

## Indexing

Supported source formats:

- Markdown: `.md`
- Plain text: `.txt`
- PDF: `.pdf`

Index one or more files:

```bash
uv run recall index note.md handbook.pdf
```

Index a directory recursively:

```bash
uv run recall index ~/Documents/notes --recursive
```

### Automatic tagging

By default, Recall asks the configured tagging model for a validated document-level `category`, `tags`, and `summary` before committing the document.

```bash
uv run recall index note.md --tag-model openai-codex/gpt-5.4-mini
```

If tagging fails, that document is not written. To keep indexing fully local, skip tagging explicitly:

```bash
uv run recall index note.md --no-tag
```

When re-indexing an existing document with `--no-tag`, Recall preserves its current metadata.

### Identity and updates

`index` is an idempotent upsert. Each document receives a stable UUID-based `document_id`; its path is only a mutable locator.

- Same path: reuse the document ID.
- Unique renamed file with unchanged content: detect the rename and reuse the ID.
- Copy or ambiguous match: create a new ID.
- Path and content both changed: associate explicitly.

```bash
uv run recall index moved-and-edited.md --document-id doc_<id>
```

### Batch behavior

`--concurrency` limits how many documents enter preprocessing at once. It is not a count of parallel provider processes. Documents are committed independently: one failure does not roll back successful siblings or overwrite that document's previous index.

Use `--json` to obtain the complete per-document result and a nonzero exit code when any item fails:

```bash
uv run recall index ~/Documents/notes --recursive --json
```

## Search and Ask

### Search

```bash
uv run recall search "How do we test IP quality?"
uv run recall search "release process" --limit 10
uv run recall search "deployment" --category engineering --tag operations
uv run recall search "cross-language question in English" --json
```

Search returns matching chunks with distance, path, content, and document metadata. `--json` is the best way to inspect the exact context supplied to `ask`.

### Ask

```bash
uv run recall ask "Which database does this project use?"
uv run recall ask "Summarize the release process" --limit 8
uv run recall ask "Compare the options" --model openai-codex/gpt-5.4
```

`ask` is grounded by default: it must answer from retrieved chunks, cite sources, and say when the evidence is insufficient.

To permit clearly separated model knowledge:

```bash
uv run recall ask "Compare our design with common alternatives" \
  --allow-general-knowledge
```

Current `ask` behavior is retrieval followed by one model completion. It is not an autonomous retrieval loop.

## Document management

```bash
uv run recall list
uv run recall show doc_<id>
uv run recall retag doc_<id>
uv run recall retag doc_<id> --tag-model openai-codex/gpt-5.4-mini
uv run recall remove doc_<id>
```

`retag` reads the already indexed source and replaces document metadata only after the new result validates. `remove` accepts multiple document IDs.

Every RAG command supports:

```text
--store PATH   Select an independent Chroma store
--json         Emit the versioned machine envelope
```

## Web dashboard

```bash
uv run recall dashboard
uv run recall dashboard --store /path/to/db
```

The command starts or connects to the store daemon and opens the loopback dashboard in your default browser. JSON mode returns the URL without opening a browser:

```bash
uv run recall dashboard --json
```

The dashboard includes:

- Search with limit, category, and tag filters
- Ask with model selection and the general-knowledge option
- Expandable source, chunk, and metadata previews

The dashboard intentionally excludes file upload, indexing, and original-file full-text preview. Use the CLI for indexing.

## Per-store daemon

RAG commands automatically start one daemon per normalized store path. Each daemon keeps one `RecallApp`, Qwen3 model, and Chroma client resident and serializes requests from both transports:

- Unix socket for CLI commands
- Dynamic `127.0.0.1` HTTP port for the API and dashboard

The daemon exits after 30 minutes without CLI or HTTP activity.

```bash
uv run recall daemon status
uv run recall daemon status --store /path/to/db --json
uv run recall daemon stop
```

Runtime files live under `~/.local/state/recall/daemons/`. Provider and config commands remain foreground operations and do not start a daemon.

## HTTP API

### Discovery and authentication

Start the daemon and retrieve its URL without opening a browser:

```bash
uv run recall dashboard --json
```

The response contains `data.api_url`, for example `http://127.0.0.1:54321`. After the daemon is running, `uv run recall daemon status --json` reports the same URL. The shared Bearer token is generated at `~/.config/recall/api-token` with `0600` permissions.

```bash
API_URL="http://127.0.0.1:54321"
TOKEN="$(cat ~/.config/recall/api-token)"

curl "$API_URL/v1/health" \
  -H "Authorization: Bearer $TOKEN"
```

OpenAPI is available at:

```text
GET /openapi.json
```

All `/v1/*` routes require the Bearer token. The server binds only to `127.0.0.1`, validates Host and Origin, and does not enable CORS. It is not a remote or LAN API.

### Core endpoints

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/v1/health` | Health check |
| `GET` | `/v1/models` | Models available from configured providers |
| `GET` | `/v1/documents` | List documents |
| `GET` | `/v1/documents/{id}` | Show one document |
| `POST` | `/v1/documents/index` | Index daemon-local paths |
| `POST` | `/v1/documents/remove` | Remove document IDs |
| `POST` | `/v1/documents/retag` | Regenerate metadata |
| `POST` | `/v1/search` | Search chunks |
| `POST` | `/v1/ask` | Produce a grounded answer |
| `GET` | `/v1/config` | Read common settings |
| `PATCH` | `/v1/config` | Update common settings |
| `GET` | `/v1/providers` | List connected providers |
| `POST` | `/v1/providers/{id}/login` | Start an OAuth session |
| `DELETE` | `/v1/providers/{id}` | Remove provider credentials |
| `GET` | `/v1/auth-sessions/{id}` | Poll an OAuth session |
| `POST` | `/v1/auth-sessions/{id}/code` | Submit a manual OAuth code |
| `DELETE` | `/v1/auth-sessions/{id}` | Cancel an OAuth session |
| `GET` | `/v1/daemon` | Read daemon status |
| `POST` | `/v1/daemon/stop` | Stop the daemon |

Indexing through HTTP accepts local filesystem paths visible to the daemon; it does not upload files.

### Request examples

```bash
curl "$API_URL/v1/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"release process","limit":5}'
```

```bash
curl "$API_URL/v1/ask" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"What is our release process?","limit":5}'
```

```bash
curl "$API_URL/v1/documents/index" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"paths":["/Users/me/Documents/notes"],"recursive":true}'
```

### Response protocol

Success:

```json
{"version":1,"ok":true,"data":{}}
```

Failure:

```json
{"version":1,"ok":false,"error":{"code":"USAGE_ERROR","message":"Invalid request."}}
```

Batch partial failure uses HTTP `207` with `error.code = "PARTIAL_FAILURE"`. Common status codes include `400`, `401`, `403`, `404`, `409`, `410`, `500`, and `503`.

The API is the intended integration boundary for future local MCP servers and other agents.

## Data, privacy, and backups

### Local paths

| Data | Default path |
|---|---|
| Chroma store | `~/.local/share/recall/db/` |
| Recall config | `~/.config/recall/config.toml` |
| Provider credentials | `~/.config/recall/auth.json` |
| API token | `~/.config/recall/api-token` |
| Daemon runtime files | `~/.local/state/recall/daemons/` |

### Privacy boundary

Locally retained:

- Source files
- Extracted text and chunks
- Qwen3 embeddings
- Chroma database and metadata

Potentially sent to the configured provider:

- Document content needed for automatic tagging or retagging
- Retrieved chunks and the question used by `ask`

Use `index --no-tag` to avoid provider calls while indexing. Search and embedding remain local; `ask` requires a configured answer model.

### Backup and migration

Back up the **entire** Chroma store directory, not only `chroma.sqlite3`. The directory also contains HNSW index files.

Stop the corresponding daemon before a consistent backup:

```bash
uv run recall daemon stop --store ~/.local/share/recall/db
cp -a ~/.local/share/recall/db /path/to/backup/
```

A store records its embedding model and dimensions. A nonempty store created with an incompatible or legacy embedding model fails closed; rebuild it rather than mixing vector spaces.

## Pi extension and agent integrations

The included Pi extension registers a `recall_search` tool and calls only the public CLI machine boundary:

```bash
npm install --ignore-scripts
pi -e ./agent/extensions/rag-search.ts
```

For new integrations, prefer the authenticated HTTP/OpenAPI API. A future MCP server can wrap those endpoints without directly importing Chroma or duplicating Recall's storage rules.

## Troubleshooting

### `Provider is not configured`

The selected `provider/model` does not match an available credential. Check both:

```bash
uv run recall provider list
uv run recall config list
```

Then choose a model from `uv run recall config`, set the matching provider environment variable, or log in to `openai-codex`.

### Node.js or bridge errors

Confirm Node.js 22.19 or newer:

```bash
node --version
```

When running from a source checkout after changing the bridge, rebuild it:

```bash
npm install
npm run build:bridge
```

### First command is slow

The first indexing or retrieval operation may download and load Qwen3 Embedding. Later commands reuse the model through the per-store daemon.

### Embedding model mismatch

Recall refuses to mix embeddings from different models or dimensions. Move or remove the incompatible store and re-index the original files. Do not copy records between vector spaces.

### Daemon is stale or unavailable

```bash
uv run recall daemon status --json
uv run recall daemon stop
uv run recall search "health check"
```

The final search transparently starts a fresh daemon. Logs and runtime state are under `~/.local/state/recall/daemons/`.

### Configuration errors

```bash
uv run recall config list
```

Model references must be nonempty `provider/model` strings. Search limits and indexing concurrency must be positive integers. Invalid TOML fails before Recall writes any update.

### Search quality is poor

- Inspect raw results with `search --json`.
- Increase `--limit` when relevant information is spread across chunks.
- Use `--category` or `--tag` only when metadata is populated.
- Verify the source was indexed and has not moved unexpectedly.
- Re-index changed files; indexing is idempotent.

## Development

Install both runtimes:

```bash
uv sync
npm install
```

Run validation:

```bash
npm run build:bridge
uv run python -m unittest discover -s tests -p 'test_*.py' -v
npm test
npm run check
uvx ruff check src tests
uv lock --check
npm audit --audit-level=high
uv build
```

Node tests use Pi SDK test providers and do not require real provider accounts or network access. When the bridge changes, validate both the generated `src/recall/model_bridge.mjs` and the bridge extracted from the built wheel.
