# Recall

Recall 是面向个人知识库的本地 RAG CLI：使用 Qwen3-Embedding 生成多语言嵌入、Chroma 持久化向量，并通过项目内置的 Pi SDK bridge 自动标注文档及生成带来源的回答。

完整 API 约定见 [CLI API 设计](./docs/plans/2026-07-27-recall-cli-api-design.md)，技术背景见 [RAG 技术选型文档](./RAG技术选型文档.md)。

## 环境

- Python 3.11–3.13（项目默认 Python 3.12）
- Node.js 22.19+
- 对应模型供应商的 API 凭据，或 ChatGPT Plus/Pro 订阅；不需要安装或登录 Pi CLI

## 安装

推荐使用 `uv`：

```bash
uv sync
uv run recall --help
```

也可以安装到当前 Python 环境：

```bash
python -m pip install -e .
recall --help
```

首次索引或检索时会下载 `Qwen/Qwen3-Embedding-0.6B`。Recall 分别使用模型的 document/query 编码入口，并将归一化的 1024 维向量写入 Chroma；该模型支持多语言及跨语言检索。

## 使用

```bash
# 默认调用 Pi 自动生成 category、tags、summary
uv run recall index ~/Documents/notes --recursive

# 跳过自动标注；已有文档会保留原 metadata
uv run recall index note.md --no-tag

# 机器可读检索
uv run recall search "如何设计 RAG？" --limit 5 --json

# 严格依据知识库回答并附来源；默认只显示答案和来源
uv run recall ask "项目使用什么向量数据库？"

# 机器可读问答
uv run recall ask "项目使用什么向量数据库？" --json

# 明确允许模型补充通用知识
uv run recall ask "比较向量数据库" --allow-general-knowledge

uv run recall list
uv run recall show doc_<id>
uv run recall retag doc_<id>
uv run recall remove doc_<id>
```

### 连接 ChatGPT Plus/Pro Codex

```bash
# 交互式选择 provider，再选择浏览器或设备码登录
uv run recall provider login

# 脚本或明确调用仍可指定 provider
uv run recall provider login openai-codex

uv run recall provider list
# OpenAI Codex（ChatGPT Plus/Pro OAuth）: 已连接

# 机器调用仍可获取版本化 JSON
uv run recall provider list --json

uv run recall ask "问题" --model openai-codex/gpt-5.4

# 删除本地 OAuth 凭据
uv run recall provider logout openai-codex
```

若要默认使用 Codex，可在配置中把 `[models].ask` 或 `[models].tag` 设置为 `openai-codex/<model>`。Recall 会在 token 过期时通过 Pi SDK 刷新，并持久化刷新结果。

文件路径只是 locator；Recall 为文档生成稳定 `document_id`。仅重命名且内容不变时会自动沿用 ID；路径和内容同时改变时显式关联：

```bash
uv run recall index moved.md --document-id doc_<id>
```

支持 PDF、TXT 和 Markdown。

### 每 Store 独立 Daemon

`index`、`remove`、`list`、`show`、`search`、`ask` 和 `retag` 会按规范化 store 路径自动连接或启动一个本地 daemon。每个 store 使用独立进程和 Unix socket，串行处理请求，并复用同一个 Chroma client、HNSW 索引和 Qwen3 模型；完成请求后空闲 30 分钟会自动退出。

```bash
# 查看默认 store daemon
uv run recall daemon status

# 查看或停止指定 store daemon
uv run recall daemon status --store /path/to/db
uv run recall daemon stop --store /path/to/db
```

运行文件位于 `~/.local/state/recall/daemons/`，目录和 socket 权限分别为 `0700` 与 `0600`。`provider login/list/logout` 不启动 daemon。daemon 仅支持本机 Unix socket，不提供 TCP/HTTP 或远程访问。

## 配置文件

配置文件是可选的 TOML 文件；不存在时 Recall 使用默认值。默认位置为 `~/.config/recall/config.toml`。推荐使用命令查看或修改常用设置：

```bash
uv run recall config list
uv run recall config set search.limit 10
uv run recall config set models.tag openai-codex/gpt-5.4-mini
uv run recall config set models.ask openai-codex/gpt-5.4
```

纯 `recall config` 会启动菜单式 setup 向导，显示每项当前值。编辑 tagging model 或 ask model 时，向导会列出 Recall 凭据文件或当前环境变量已配置的 provider 所有可用 `provider/model`；选择后会返回主菜单，选择 Exit 退出。它不会启动 RAG daemon：

```text
┌  Recall setup
│
◆  Configuration:
│  ● Edit search limit (5)
│  ○ Edit tagging model (openai-codex/gpt-5.4-mini)
│  ○ Edit ask model (openai-codex/gpt-5.4)
│  ○ Exit
└
```

例如选择 ask model 后：

```text
◆  Select ask model:
│  ● openai-codex/gpt-5.4 (current)
│  ○ openai-codex/gpt-5.3-codex-spark
│  ○ openai-codex/gpt-5.4-mini
│  ○ openai-codex/gpt-5.5
│  ○ openai-codex/gpt-5.6-luna
│  ○ openai-codex/gpt-5.6-sol
│  ○ openai-codex/gpt-5.6-terra
│  ○ Back
```

未配置认证的 provider 不会出现在选择列表中；仍可通过 `recall config set` 或直接编辑 TOML 预先设置任意有效的 `provider/model`。

也可以直接创建或编辑 TOML：

```bash
mkdir -p ~/.config/recall
cat > ~/.config/recall/config.toml <<'EOF'
[models]
tag = "openai/gpt-4o-mini"
ask = "openai/gpt-4o-mini"

[search]
limit = 5

[index]
concurrency = 4
EOF
```

当前支持以下设置：

| 设置 | 用途 | 格式 | 默认值 |
|---|---|---|---|
| `models.tag` | `index` 自动标注及 `retag` 使用的模型 | `provider/model` | `openai/gpt-4o-mini` |
| `models.ask` | `ask` 生成回答使用的模型 | `provider/model` | `openai/gpt-4o-mini` |
| `search.limit` | `search` 和 `ask` 默认检索的 chunk 数量 | 正整数 | `5` |
| `index.concurrency` | 索引流水线同时处理的文档上限 | 正整数 | `4` |

例如，登录 ChatGPT Plus/Pro 后，可让问答使用 Codex、标注继续使用默认模型：

```toml
[models]
tag = "openai/gpt-4o-mini"
ask = "openai-codex/gpt-5.4"

[search]
limit = 10

[index]
concurrency = 8
```

各项设置按以下顺序覆盖，左侧优先：

| 设置 | 优先级 |
|---|---|
| 标注模型 | `--tag-model` > `RECALL_TAG_MODEL` > `models.tag` > 默认值 |
| 问答模型 | `--model` > `RECALL_ASK_MODEL` > `models.ask` > 默认值 |
| 检索数量 | `--limit` > `search.limit` > `5` |
| 索引并发 | `--concurrency` > `RECALL_INDEX_CONCURRENCY` > `index.concurrency` > `4` |

`config set` 支持 `models.tag`、`models.ask` 和 `search.limit`；其他设置仍可直接编辑 TOML。修改配置后无需重启 daemon，下一条命令会重新读取配置。模型值必须是非空的 `provider/model`，`search.limit` 和 `index.concurrency` 必须是正整数。TOML 语法错误或无效值会返回 `USAGE_ERROR` 并以状态码 `2` 退出。

嵌入模型不由该 TOML 配置：当前固定为 `Qwen/Qwen3-Embedding-0.6B`。Store 会记录 embedding 模型和维度；旧模型产生的向量不能与 Qwen3 向量混用，切换模型后必须完整重建对应 store。

Store 路径不写在该 TOML 中，其优先级为 `--store` > `RECALL_STORE` > `~/.local/share/recall/db/`。备份时应复制整个 store 目录，而不只是 SQLite 文件。

### 供应商凭据

API key 或 OAuth 凭据也不写在 `config.toml` 中。供应商凭据优先使用其标准环境变量，例如 `OPENAI_API_KEY`、`ANTHROPIC_API_KEY`。静态 API key 与 OAuth 凭据也可保存在 Recall 专属的 `~/.config/recall/auth.json`：

```json
{
  "openai": {"type": "api_key", "key": "..."}
}
```

Recall 创建或更新该文件时会将权限收紧为 `0600`，并用跨进程文件锁保护 OAuth 刷新。该文件包含敏感凭据，不应复制到仓库。Recall 不读取 `~/.pi/agent` 的设置或认证。

## JSON 协议

`--json` 的 stdout 只包含版本化 envelope：

```json
{"version": 1, "ok": true, "data": {}}
```

参数错误退出 `2`；运行失败或批量部分失败退出 `1`；诊断信息写入 stderr。

## Pi Extension

安装开发依赖并加载 Extension：

```bash
npm install --ignore-scripts
pi -e ./agent/extensions/rag-search.ts
```

Extension 注册 `recall_search` 工具，并且只调用 `recall search --json`，不直接访问 Chroma。

## 开发验证

修改模型 bridge 后先重建 Python 包内的运行产物：

```bash
npm install
npm run build:bridge
uv run python -m unittest discover -s tests -p 'test_*.py' -v
npm test
npm run check
npm audit --audit-level=high
```

Node 测试使用 Pi SDK 的 `fauxProvider`，不访问真实供应商。
