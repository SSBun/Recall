# Recall 中文指南

[项目首页](../README.zh-CN.md) · [English Guide](./GUIDE.md)

本指南覆盖安装、认证、配置、索引、检索、Dashboard、HTTP API、数据管理、故障排查与开发验证。

## 目录

- [环境要求](#环境要求)
- [安装](#安装)
- [建立第一个知识库](#建立第一个知识库)
- [供应商认证](#供应商认证)
- [配置](#配置)
- [索引](#索引)
- [检索与问答](#检索与问答)
- [文档管理](#文档管理)
- [Web Dashboard](#web-dashboard)
- [每 Store 独立 Daemon](#每-store-独立-daemon)
- [HTTP API](#http-api)
- [数据、隐私与备份](#数据隐私与备份)
- [Pi Extension 与 Agent 集成](#pi-extension-与-agent-集成)
- [故障排查](#故障排查)
- [开发](#开发)

## 环境要求

| 依赖 | 支持版本 | 用途 |
|---|---:|---|
| Python | 3.11–3.13 | Recall CLI、Chroma 与嵌入 |
| Node.js | 22.19+ | 内置 Pi SDK 模型 bridge |
| uv | 当前稳定版 | 推荐的环境和命令运行工具 |
| 模型凭据 | 取决于供应商 | 自动标注与 `ask` |

Recall 不要求安装 Pi CLI，也不会读取 Pi 的全局配置或凭据。

## 安装

Recall 目前从源码安装：

```bash
git clone https://github.com/SSBun/Recall.git
cd Recall
uv sync
uv run recall --help
```

也可以安装到当前 Python 环境：

```bash
python -m pip install .
recall --help
```

首次索引或检索时可能下载 `Qwen/Qwen3-Embedding-0.6B`，模型文件由底层 Hugging Face 工具缓存。

## 建立第一个知识库

最短完整流程如下：

```bash
# 1. 通过 Codex OAuth 连接 ChatGPT Plus/Pro
uv run recall provider login openai-codex

# 2. 选择标注和问答模型
uv run recall config

# 3. 索引目录
uv run recall index ~/Documents/notes --recursive

# 4. 检索
uv run recall search "部署检查清单"

# 5. 基于证据提问
uv run recall ask "我们的部署检查清单是什么？"

# 6. 打开 Dashboard
uv run recall dashboard
```

默认完整 Chroma 数据库保存在 `~/.local/share/recall/db/`。通过 `--store /path/to/db` 可创建或选择另一个相互独立的知识库。

## 供应商认证

### ChatGPT Plus/Pro OAuth

Recall 当前为 `openai-codex` 提供交互式 OAuth 登录：

```bash
uv run recall provider login
# 或
uv run recall provider login openai-codex
```

交互流程支持浏览器和设备码登录。凭据以受限权限保存在 `~/.config/recall/auth.json`。

```bash
uv run recall provider list
uv run recall provider logout openai-codex
```

### API Key

也可以使用供应商标准环境变量，例如：

```bash
export OPENAI_API_KEY="..."
uv run recall config set models.ask openai/gpt-4o-mini
```

不要提交凭据。Recall 自有凭据位于 `~/.config/recall/auth.json`，它独立于 `config.toml` 和 Pi 的全局配置。

### 可用模型名称

运行菜单向导并编辑任一模型设置：

```bash
uv run recall config
```

Recall 会列出其内置 Pi SDK 模型目录中，已通过 Recall 凭据或当前环境配置供应商的全部模型。模型选择器读取本地目录，不会从远程服务拉取模型列表；真正调用模型时仍会请求所选供应商。

脚本可以预设任何语法有效的 `provider/model`：

```bash
uv run recall config set models.tag openai-codex/gpt-5.4-mini
uv run recall config set models.ask openai-codex/gpt-5.4
```

只有对应供应商已经配置并支持该模型时，模型才真正可用。

## 配置

可选配置文件位于 `~/.config/recall/config.toml`。

```bash
uv run recall config             # 交互式设置菜单
uv run recall config list        # 显示有效配置
uv run recall config set search.limit 10
uv run recall config set models.tag openai-codex/gpt-5.4-mini
uv run recall config set models.ask openai-codex/gpt-5.4
```

TOML 示例：

```toml
[models]
tag = "openai-codex/gpt-5.4-mini"
ask = "openai-codex/gpt-5.4"

[search]
limit = 5

[index]
concurrency = 4
```

| 设置 | 含义 | 默认值 | 优先级，从高到低 |
|---|---|---|---|
| `models.tag` | `index` 与 `retag` 使用的模型 | `openai/gpt-4o-mini` | `--tag-model`、`RECALL_TAG_MODEL`、TOML、默认值 |
| `models.ask` | `ask` 使用的模型 | `openai/gpt-4o-mini` | `--model`、`RECALL_ASK_MODEL`、TOML、默认值 |
| `search.limit` | `search` 与 `ask` 默认检索 chunk 数 | `5` | `--limit`、TOML、默认值 |
| `index.concurrency` | 同时进入预处理的文档数 | `4` | `--concurrency`、`RECALL_INDEX_CONCURRENCY`、TOML、默认值 |

`config set` 支持 `models.tag`、`models.ask` 和 `search.limit`。`index.concurrency` 需要直接编辑 TOML。写入前会完成校验，更新采用原子替换，并保留不相关 TOML 内容。

嵌入模型有意设为不可配置。每个 store 都使用归一化的 1024 维 `Qwen/Qwen3-Embedding-0.6B` 向量；切换模型必须重建整个 store。

Store 路径采用独立优先级：

```text
--store > RECALL_STORE > ~/.local/share/recall/db/
```

## 索引

支持的源文件格式：

- Markdown：`.md`
- 纯文本：`.txt`
- PDF：`.pdf`

索引一个或多个文件：

```bash
uv run recall index note.md handbook.pdf
```

递归索引目录：

```bash
uv run recall index ~/Documents/notes --recursive
```

### 自动标注

默认情况下，Recall 会在提交文档前，请配置的标注模型生成并校验文档级 `category`、`tags` 和 `summary`。

```bash
uv run recall index note.md --tag-model openai-codex/gpt-5.4-mini
```

如果标注失败，该文档不会写入。若希望索引过程完全本地化，请显式跳过标注：

```bash
uv run recall index note.md --no-tag
```

使用 `--no-tag` 重新索引已有文档时，Recall 会保留当前元数据。

### 身份与更新

`index` 是幂等 upsert。每篇文档会获得基于 UUID 的稳定 `document_id`，路径只是可变 locator。

- 路径相同：沿用文档 ID。
- 唯一缺失来源与新文件内容一致：识别为重命名并沿用 ID。
- 复制或匹配有歧义：创建新 ID。
- 路径和内容同时变化：显式关联。

```bash
uv run recall index moved-and-edited.md --document-id doc_<id>
```

### 批量行为

`--concurrency` 限制同时进入预处理的文档数量，它不是并行供应商进程数。文档逐篇独立提交：一篇失败不会回滚已成功文档，也不会覆盖该失败文档原有的索引。

使用 `--json` 获取完整逐文档结果；任意项目失败时命令返回非零状态：

```bash
uv run recall index ~/Documents/notes --recursive --json
```

## 检索与问答

### Search

```bash
uv run recall search "如何测试 IP 质量？"
uv run recall search "发布流程" --limit 10
uv run recall search "部署" --category engineering --tag operations
uv run recall search "用英文检索中文内容" --json
```

Search 返回匹配 chunk 的距离、路径、内容和文档元数据。`--json` 最适合检查后续提供给 `ask` 的准确上下文。

### Ask

```bash
uv run recall ask "这个项目使用哪个数据库？"
uv run recall ask "总结发布流程" --limit 8
uv run recall ask "比较这些方案" --model openai-codex/gpt-5.4
```

`ask` 默认严格基于知识库：必须依据检索 chunk 回答、附上来源，并在证据不足时明确说明。

若要允许明确分隔的模型常识：

```bash
uv run recall ask "将我们的设计与常见方案比较" \
  --allow-general-knowledge
```

当前 `ask` 的执行方式是先检索，再进行一次模型补全；它不是自主循环检索的 Agent。

## 文档管理

```bash
uv run recall list
uv run recall show doc_<id>
uv run recall retag doc_<id>
uv run recall retag doc_<id> --tag-model openai-codex/gpt-5.4-mini
uv run recall remove doc_<id>
```

`retag` 读取已索引来源，只有新元数据验证通过后才进行替换。`remove` 可同时接收多个文档 ID。

所有 RAG 命令均支持：

```text
--store PATH   选择独立 Chroma Store
--json         输出版本化机器 envelope
```

## Web Dashboard

```bash
uv run recall dashboard
uv run recall dashboard --store /path/to/db
```

命令会启动或连接对应 store daemon，并在默认浏览器打开 loopback Dashboard。JSON 模式只返回 URL，不打开浏览器：

```bash
uv run recall dashboard --json
```

Dashboard 包含：

- 带 limit、category 和 tag 过滤器的 Search
- 带模型选择和通用知识开关的 Ask
- 可展开的来源、chunk 和 metadata 预览

Dashboard 有意不提供文件上传、索引和原始文件全文预览；请使用 CLI 索引文件。

## 每 Store 独立 Daemon

RAG 命令会按规范化 store 路径自动启动一个 daemon。每个 daemon 常驻一个 `RecallApp`、Qwen3 模型和 Chroma client，并串行处理两种 transport 的请求：

- CLI 使用 Unix socket
- API 和 Dashboard 使用动态 `127.0.0.1` HTTP 端口

CLI 和 HTTP 均无活动 30 分钟后，daemon 自动退出。

```bash
uv run recall daemon status
uv run recall daemon status --store /path/to/db --json
uv run recall daemon stop
```

运行文件位于 `~/.local/state/recall/daemons/`。Provider 和 config 命令始终在前台执行，不会启动 daemon。

## HTTP API

### 发现与认证

启动 daemon 并在不打开浏览器的情况下获取 URL：

```bash
uv run recall dashboard --json
```

响应包含 `data.api_url`，例如 `http://127.0.0.1:54321`。Daemon 启动后，`uv run recall daemon status --json` 会报告相同 URL。共享 Bearer Token 生成在 `~/.config/recall/api-token`，权限为 `0600`。

```bash
API_URL="http://127.0.0.1:54321"
TOKEN="$(cat ~/.config/recall/api-token)"

curl "$API_URL/v1/health" \
  -H "Authorization: Bearer $TOKEN"
```

OpenAPI 位于：

```text
GET /openapi.json
```

所有 `/v1/*` 路由都要求 Bearer Token。服务只绑定 `127.0.0.1`、校验 Host 与 Origin，并且不启用 CORS；它不是远程或局域网 API。

### 核心端点

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/v1/health` | 健康检查 |
| `GET` | `/v1/models` | 已配置供应商的可用模型 |
| `GET` | `/v1/documents` | 列出文档 |
| `GET` | `/v1/documents/{id}` | 查看单篇文档 |
| `POST` | `/v1/documents/index` | 索引 daemon 可访问的本地路径 |
| `POST` | `/v1/documents/remove` | 删除文档 ID |
| `POST` | `/v1/documents/retag` | 重新生成元数据 |
| `POST` | `/v1/search` | 检索 chunk |
| `POST` | `/v1/ask` | 生成基于证据的回答 |
| `GET` | `/v1/config` | 读取常用设置 |
| `PATCH` | `/v1/config` | 更新常用设置 |
| `GET` | `/v1/providers` | 列出已连接供应商 |
| `POST` | `/v1/providers/{id}/login` | 启动 OAuth 会话 |
| `DELETE` | `/v1/providers/{id}` | 删除供应商凭据 |
| `GET` | `/v1/auth-sessions/{id}` | 轮询 OAuth 会话 |
| `POST` | `/v1/auth-sessions/{id}/code` | 提交手动 OAuth Code |
| `DELETE` | `/v1/auth-sessions/{id}` | 取消 OAuth 会话 |
| `GET` | `/v1/daemon` | 读取 daemon 状态 |
| `POST` | `/v1/daemon/stop` | 停止 daemon |

通过 HTTP 索引时，body 中的路径必须是 daemon 可见的本地文件系统路径；API 不上传文件。

### 请求示例

```bash
curl "$API_URL/v1/search" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"query":"发布流程","limit":5}'
```

```bash
curl "$API_URL/v1/ask" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"question":"我们的发布流程是什么？","limit":5}'
```

```bash
curl "$API_URL/v1/documents/index" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"paths":["/Users/me/Documents/notes"],"recursive":true}'
```

### 响应协议

成功：

```json
{"version":1,"ok":true,"data":{}}
```

失败：

```json
{"version":1,"ok":false,"error":{"code":"USAGE_ERROR","message":"Invalid request."}}
```

批量部分失败使用 HTTP `207`，且 `error.code = "PARTIAL_FAILURE"`。常见状态码包括 `400`、`401`、`403`、`404`、`409`、`410`、`500` 和 `503`。

HTTP API 是未来本地 MCP Server 与其他 Agent 的推荐集成边界。

## 数据、隐私与备份

### 本地路径

| 数据 | 默认路径 |
|---|---|
| Chroma Store | `~/.local/share/recall/db/` |
| Recall 配置 | `~/.config/recall/config.toml` |
| 供应商凭据 | `~/.config/recall/auth.json` |
| API Token | `~/.config/recall/api-token` |
| Daemon 运行文件 | `~/.local/state/recall/daemons/` |

### 隐私边界

保留在本地：

- 源文件
- 提取文本和 chunk
- Qwen3 嵌入
- Chroma 数据库和元数据

可能发送给配置的供应商：

- 自动标注或重新标注所需的文档内容
- `ask` 使用的检索 chunk 和问题

使用 `index --no-tag` 可在索引时避免供应商调用。Search 和嵌入保持本地；`ask` 需要配置问答模型。

### 备份与迁移

请备份**整个** Chroma Store 目录，而不只是 `chroma.sqlite3`，因为目录中还包含 HNSW 索引文件。

进行一致性备份前，先停止对应 daemon：

```bash
uv run recall daemon stop --store ~/.local/share/recall/db
cp -a ~/.local/share/recall/db /path/to/backup/
```

Store 会记录嵌入模型和维度。非空 store 如果来自不兼容或旧嵌入模型，会拒绝继续使用；请重新索引，而不是混合不同向量空间。

## Pi Extension 与 Agent 集成

项目内置 Pi Extension 会注册 `recall_search` 工具，并且只调用公开 CLI 机器边界：

```bash
npm install --ignore-scripts
pi -e ./agent/extensions/rag-search.ts
```

新集成应优先使用带认证的 HTTP/OpenAPI。未来 MCP Server 可以封装这些端点，无需直接导入 Chroma，也不必重复 Recall 的存储规则。

## 故障排查

### `Provider is not configured`

所选 `provider/model` 与可用凭据不匹配。请同时检查：

```bash
uv run recall provider list
uv run recall config list
```

然后通过 `uv run recall config` 选择模型、设置对应供应商环境变量，或登录 `openai-codex`。

### Node.js 或 bridge 错误

确认 Node.js 不低于 22.19：

```bash
node --version
```

从源码运行且修改过 bridge 时，需要重新构建：

```bash
npm install
npm run build:bridge
```

### 第一条命令很慢

首次索引或检索时，可能需要下载并加载 Qwen3 Embedding。后续命令会通过 per-store daemon 复用模型。

### 嵌入模型不匹配

Recall 拒绝混合不同模型或维度的嵌入。请移动或删除不兼容 store，并从原始文件重新索引；不要跨向量空间复制记录。

### Daemon 状态异常

```bash
uv run recall daemon status --json
uv run recall daemon stop
uv run recall search "health check"
```

最后一条搜索会透明启动新 daemon。日志和运行状态位于 `~/.local/state/recall/daemons/`。

### 配置错误

```bash
uv run recall config list
```

模型引用必须是非空 `provider/model`；检索数量和索引并发必须是正整数。TOML 无效时，Recall 会在写入任何更新前失败。

### 检索质量不理想

- 使用 `search --json` 检查原始结果。
- 相关信息分布在多个 chunk 时提高 `--limit`。
- 只有存在元数据时才使用 `--category` 或 `--tag`。
- 确认来源已索引且没有被意外移动。
- 重新索引发生变化的文件；索引是幂等的。

## 开发

安装两套运行环境：

```bash
uv sync
npm install
```

运行验证：

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

Node 测试使用 Pi SDK 测试供应商，不需要真实账号或网络。Bridge 发生变化时，必须同时验证生成的 `src/recall/model_bridge.mjs` 和从 wheel 提取出的 bridge。
