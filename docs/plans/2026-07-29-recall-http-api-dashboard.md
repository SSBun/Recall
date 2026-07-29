# Recall 标准 HTTP API 与 Web Dashboard 实施计划

## 1. 目标

把现有 per-store daemon 扩展为 Recall 的统一本地服务边界：继续保留 CLI 使用的 Unix socket，同时在同一进程内启动仅监听 loopback 的 HTTP API。CLI、Web Dashboard 和未来 MCP 都消费同一套 `RecallApp`、Chroma、Qwen 与 Pi provider 能力，不创建第二份模型或 store 状态。

## 2. 已确认的产品决策

- 每个规范化 store 对应独立 daemon，也对应独立动态 HTTP 地址 `http://127.0.0.1:<port>`。
- daemon 启动时 HTTP API 一并启动；daemon stop 或空闲 30 分钟退出时 HTTP API 一并停止。
- `recall daemon status --json` 返回当前 store 的 `api_url`。
- API Token 全局保存在 `~/.config/recall/api-token`，首次生成后复用；目录/文件权限为 `0700`/`0600`。
- 所有 `/v1/*` 端点要求 `Authorization: Bearer <token>`；服务只绑定 `127.0.0.1`，校验 Host/Origin，不启用 CORS，也不提供关闭认证的模式。
- API 使用 FastAPI + Uvicorn，提供 `/openapi.json`。
- API 覆盖现有 CLI 的 RAG、provider、config 和 daemon 能力；index 只接受 daemon 所在机器的路径，不接受上传内容。
- Provider OAuth 使用 daemon 内存中的异步会话，支持 browser/device-code、状态查询、手动 code、取消和超时。
- Dashboard 只提供 Search、Ask 和命中 chunk/metadata 预览；不提供索引、上传、配置、provider 管理或原文件全文预览。
- Dashboard 使用无框架 HTML/CSS/JavaScript，采用克制的 Linear dark 风格；静态资源随 wheel 分发。
- 本次不实现 MCP Server；后续 MCP 通过稳定 OpenAPI/HTTP 契约接入。

## 3. 固定 API 契约

### 3.1 通用协议

成功：

```json
{"version": 1, "ok": true, "data": {}}
```

失败：

```json
{"version": 1, "ok": false, "error": {"code": "...", "message": "..."}}
```

批量部分成功返回 HTTP `207 Multi-Status`，body 继续使用 `PARTIAL_FAILURE` envelope，并在 `error.details` 中保留全部成功项与失败项。

稳定状态映射：

| 结果 | HTTP |
|---|---:|
| 成功 | 200 |
| 参数、配置或 schema 错误 | 400 |
| Token 缺失或错误 | 401 |
| Host/Origin 不允许 | 403 |
| 文档或认证会话不存在 | 404 |
| OAuth 会话冲突 | 409 |
| OAuth 会话已过期 | 410 |
| 批量部分成功 | 207 |
| daemon 正在停止或不可用 | 503 |
| store、embedding、Pi、tagging 或内部错误 | 500 |

FastAPI 默认 validation error 必须转换成相同的 `USAGE_ERROR` envelope，不暴露框架默认响应。

### 3.2 端点

```text
GET    /openapi.json
GET    /
GET    /dashboard/app.css
GET    /dashboard/app.js
GET    /dashboard/config.js

GET    /v1/health
GET    /v1/models

GET    /v1/documents
GET    /v1/documents/{document_id}
POST   /v1/documents/index
POST   /v1/documents/remove
POST   /v1/documents/retag

POST   /v1/search
POST   /v1/ask

GET    /v1/config
PATCH  /v1/config

GET    /v1/providers
POST   /v1/providers/{provider_id}/login
DELETE /v1/providers/{provider_id}
GET    /v1/auth-sessions/{session_id}
POST   /v1/auth-sessions/{session_id}/code
DELETE /v1/auth-sessions/{session_id}

GET    /v1/daemon
POST   /v1/daemon/stop
```

`POST /v1/providers/{provider_id}/login` body 固定为：

```json
{"method": "browser"}
```

或：

```json
{"method": "device_code"}
```

返回 `202 Accepted` 和 session ID。`GET /v1/auth-sessions/{id}` 返回当前状态、`auth_url` 或 device code、错误和到期时间；manual code 只通过 `/code` 提交。stop endpoint 必须先发送响应，再触发 daemon 双 transport 停止。

## 4. 模块 seam

### 4.1 命令执行适配

新增一个 daemon 内部 runtime seam，统一拥有：

- 单一 `RecallApp`
- 单一可重入执行锁
- store 路径
- daemon activity/stop 状态
- `PiClient`
- `OAuthSessionManager`

Unix 请求和 HTTP 路由都通过该 seam 执行。RAG、config、provider list/logout 尽量复用 `cli.run(..., --json, use_daemon=False)` 的现有分发与 envelope，避免复制默认值、模型优先级、部分失败和错误逻辑；OAuth session、models、health 和 daemon lifecycle 使用专用调用。

同一把锁必须包住：

- Unix 请求临时替换 `os.environ` 的整个区间
- HTTP 对 `RecallApp`、config 和 provider 的调用
- 任何可能读取 daemon 全局环境的 resolver

这样 HTTP 线程不会观察到某个 Unix 调用者临时注入的环境。

### 4.2 HTTP application

新增 `src/recall/http_app.py`：

- Pydantic request models
- envelope 与 HTTP 状态映射
- Bearer dependency
- Host/Origin middleware
- activity middleware
- `/v1` 路由
- OpenAPI bearer security scheme
- Dashboard 静态资源与 CSP/安全响应头

不启用 CORSMiddleware。除 `/openapi.json` 和 Dashboard 静态资源外，所有业务 API 均需 Bearer Token。

### 4.3 Token

新增轻量 token helper（可位于 `http_app.py` 或独立 `api_token.py`）：

- 默认路径：`DEFAULT_CONFIG_PATH.with_name("api-token")`
- `secrets.token_urlsafe(32)`
- 写入前创建 `0700` 父目录
- 原子替换并设置 `0600`
- 已有 token 读取后校验非空
- 使用 `secrets.compare_digest`
- 不写日志、不进入 status、OpenAPI 或错误 body

Dashboard 通过同源根文档内联的 escaped `<meta>` 值读取 API base 与 token；公开脚本资源不得包含 token。由于浏览器同源策略、严格 Host/Origin、`Cross-Origin-Resource-Policy: same-origin` 和无 CORS，其他网页无法读取这些值；同一用户本地进程本就能读取 token 文件。Token 不进入 URL、history、referrer 或公开脚本资源。

### 4.4 Daemon 双 transport

修改 `src/recall/daemon.py`：

1. 创建 Unix server 和 runtime。
2. 预先创建 TCP socket，绑定 `127.0.0.1:0`，从 `getsockname()` 得到端口。
3. 把该 socket 传给 `uvicorn.Server.run(sockets=[socket])`，在独立线程启动。
4. 等待 `uvicorn_server.started`，然后才进入 Unix request loop，使第一次 status 必然包含可连接 `api_url`。
5. HTTP middleware 和 Unix handler 更新同一 activity clock。
6. stop、SIGTERM、idle timeout 或启动失败均设置 Uvicorn `should_exit`，join 线程并关闭两个 socket。
7. HTTP OAuth 会话进行期间视为 activity；daemon 退出时取消全部 session。

Token 不按 store 复制；所有 per-store daemon 读取同一个 Recall API Token。不同 store 仍有不同 `api_url`。

### 4.5 OAuth bridge

扩展 `runtime/model-bridge.ts`，新增独立流模式：

```text
node model_bridge.mjs provider login-session <provider> <authPath> <method>
```

- `<method>` 只允许 `browser` 或 `device_code`。
- Streaming `AuthInteraction.prompt` 自动回答最初的 method select。
- `notify(auth_url|device_code|info|progress)` 作为 JSONL event 输出。
- browser 流程的 `manual_code` prompt 作为 JSONL waiting event 输出并等待 stdin JSONL code。
- stdin `cancel` 调用 `AbortController.abort()`。
- 成功输出 completed；错误输出 error。
- 其他现有 bridge 命令保持一次性 JSON 协议不变。

新增 `src/recall/auth_session.py`：

- `OAuthSession` 用 `subprocess.Popen` 维持 bridge，后台线程持续读取 stdout，捕获 stderr 诊断但不泄漏凭据。
- `OAuthSessionManager` 管理 session ID、provider 唯一活跃会话、状态、事件、manual-code 输入、deadline、取消和清理。
- 默认 timeout 采用 15 分钟；完成状态可短暂保留供客户端读取，随后清理。
- 本地取消可靠终止 bridge；provider 已发起流程按 SDK 行为自然过期。

现有同步 `recall provider login` 继续使用旧 bridge 路径，保持终端 UX 不变。

### 4.6 Dashboard

资源：

```text
src/recall/dashboard/index.html
src/recall/dashboard/app.css
src/recall/dashboard/app.js
```

Linear dark 约束：

- 背景 `#0a0a0b`
- 主色 `#5e6ad2`
- 白色主文本、zinc 风格次文本
- 1px 低对比边框，最大 8px radius
- 无渐变文字、无大阴影、无 glassmorphism、无装饰图形
- 系统字体优先，离线运行，不从 CDN 加载字体或资源
- 键盘可操作、清晰 focus、`prefers-reduced-motion`、WCAG AA 对比

页面包含 Search/Ask tabs、主输入、limit 和 Search filters、loading/empty/error、结果/来源卡片以及可展开 chunk preview。所有不可信内容只用 `textContent`/`createTextNode`，不使用 `innerHTML`、`insertAdjacentHTML` 或动态 HTML 字符串。API 响应无论 2xx/非 2xx 都解析 envelope。

安全头至少包含：

```text
Content-Security-Policy: default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; frame-ancestors 'none'; form-action 'self'
X-Content-Type-Options: nosniff
Referrer-Policy: no-referrer
Cache-Control: no-store          # root/config bootstrap responses
```

### 4.7 CLI

新增：

```bash
recall dashboard [--store PATH] [--json]
```

- `DaemonClient.start()` 成为公开、幂等的 ensure-running 操作并返回 status。
- 人类模式启动 daemon、读取 `api_url`、用 `webbrowser.open(api_url)` 打开页面并打印 URL。
- `--json` 只返回 envelope 与 `dashboard_url`，不打开浏览器。
- 不启动第二个 HTTP server。
- 所有 argparse help 保持英文并进入 help 枚举测试。

## 5. 串行实施里程碑

### M1：依赖、schema 与安全底座

- 在 `pyproject.toml`、`requirements.txt` 明确加入 FastAPI/Uvicorn；更新 lock。
- 先新增 API token、请求模型、envelope、validation/error/security middleware 测试。
- 实现 HTTP app 的 health、models、documents、search、ask、index/remove/retag、config、provider list/logout 路由。
- 验证完整 OpenAPI 路由与 bearer scheme。

**Gate**：API contract tests 使用 fake app/provider/config 全绿，不启动真实 Qwen/Chroma/网络。

### M2：daemon 双 transport

- 引入 runtime seam、共享锁和 activity/stop 状态。
- 启动预绑定动态端口 Uvicorn thread。
- status 返回 `api_url`；stop/idle 清理 HTTP 与 Unix。
- 添加双 transport、单 app、串行、HTTP activity 延长 idle、不同 store 不同 URL 测试。

**Gate**：现有 daemon 测试不回归；真实临时 daemon 的 Unix 与 HTTP 都可访问并正确停止。

### M3：OAuth session

- 先用 Node faux provider 测 StreamingAuthInteraction。
- 实现 bridge JSONL login-session；重新生成 `model_bridge.mjs`。
- 实现 Python session manager 与 fake bridge 测试。
- 接入 API create/poll/code/cancel/timeout，daemon shutdown 清理。

**Gate**：browser、device code、manual code、cancel、timeout、provider conflict 均有离线确定性测试；生成 bridge 与提取 wheel 越过 OAuth loader。

### M4：Dashboard 与 CLI

- 实现并打包静态资源。
- 接入同源 routes、root meta bootstrap、CSP 和 XSS-safe rendering。
- 实现 `recall dashboard` 与 browser 注入测试。
- 用真实本机 daemon/API 完成 Search、Ask 和 preview smoke。

**Gate**：页面无外部请求、无 unsafe DOM API、无 CORS；CLI help/JSON/人类模式均通过。

### M5：文档、打包与总验收

- 更新 README、OpenAPI 使用、token 路径、API URL 发现、完整端点、Dashboard、MCP 接入说明。
- 更新 `tasks/context.md` 的 durable 架构事实。
- 构建 sdist/wheel，核对 Dashboard、bridge 和 metadata。
- 完成全量 Python/Node/TS/Ruff/lock/audit/build 与真实 smoke。

## 6. 测试矩阵

| 层 | 必测行为 |
|---|---|
| Token | 首次生成、复用、0700/0600、空/错 token、constant-time compare |
| HTTP security | Host、Origin、无 CORS、CSP、安全头、validation envelope |
| REST | 每个已确认 endpoint 的成功/错误/default/partial semantics |
| OpenAPI | 全部 routes、Bearer scheme、request schema、response envelope |
| Daemon | HTTP+Unix 同时启动、同一 app、共享锁、activity、stop、SIGTERM、idle、store 隔离 |
| OAuth bridge | method、auth_url、device_code、manual code、completed、cancel、error |
| OAuth manager | polling、timeout、provider conflict、cleanup、bridge crash |
| Dashboard | Search、Ask、source preview、loading/empty/error、XSS payload、keyboard/focus |
| CLI | dashboard help、人类模式打开 browser、JSON 不打开、daemon status api_url |
| Packaging | fastapi/uvicorn lock、Dashboard assets、generated bridge、extracted-wheel smoke |
| Regression | 全部既有 CLI、daemon、config、OAuth、Qwen/Chroma 测试 |

## 7. 验证命令

```bash
uv run python -m unittest discover -s tests -p 'test_*.py' -v
uvx --offline ruff check src tests
uv lock --check
npm test
npm run check
npm audit --audit-level=high
npm run build:bridge
uv build
```

提取 wheel 后必须再次执行：

- generated bridge 的 `provider login-session` OAuth loader smoke
- Dashboard 资源存在性与 HTTP serve smoke
- Bearer API health/search 契约 smoke

真实本机 smoke 必须验证：

1. `recall dashboard` 自动启动默认 store daemon。
2. `daemon status --json` 的 `api_url` 可访问。
3. 无 Token 请求返回 401；正确 Token 可 search/ask。
4. Dashboard 可完成 Search、Ask 和 chunk preview。
5. Ctrl-C/daemon stop 后 HTTP 与 Unix socket 均不可访问。

## 8. 子代理执行策略

- 三个只读 context-builder 已分别核对 daemon/API、OAuth 和 Dashboard/契约 seam。
- 一个 planner 已提供初步合成；本计划修正其与用户已确认决策冲突的部分：全局 token 路径、完整 config/provider/daemon API、`207` partial semantics、无 URL token。
- 后续只派一个 worker 作为主工作树唯一 writer，按 M1→M5 串行实现。
- worker 完成后并行派出只读 validator，分别检查 correctness/lifecycle、security/OAuth、API/UI/packaging。
- 父代理汇总 validator 结果；若存在范围内缺陷，只派一个 fix worker 修改主工作树。
