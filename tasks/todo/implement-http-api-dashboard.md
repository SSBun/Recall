# 实现标准 HTTP API 与 Web Dashboard

Status (2026-07-29 16:27): Completed

## Scope

- 包含：每 store daemon 内嵌的 loopback HTTP API、Bearer Token、OpenAPI、全部现有 CLI 能力的 HTTP 映射、异步 Provider OAuth 会话、Search/Ask/结果预览 Dashboard，以及 daemon/CLI/打包/文档/测试集成。
- 不包含：文件上传、Dashboard 索引界面、原始文件全文预览、远程或局域网访问、无认证模式、MCP Server 实现；后续 MCP 只消费本次稳定 API。

## Target

- [x] T1：每个 store daemon 启动时同时提供 Unix socket 与独立的 `127.0.0.1:<dynamic-port>` HTTP API；两种 transport 串行复用同一 `RecallApp`，HTTP 活动刷新 30 分钟 idle timer，停止或超时会清理两种服务。
- [x] T2：daemon 状态返回该 store 的 `api_url`；API 使用 `0600` 持久化随机 Bearer Token、校验 Host/Origin 且不启用 CORS，未认证请求无法访问 `/v1/*`。
- [x] T3：FastAPI 提供 `/openapi.json` 与已确认的 `/v1` 完整 CLI 等价端点，保持版本化 envelope、稳定 HTTP 状态码、固定 store 边界及批量部分失败语义。
- [x] T4：OpenAI Codex 登录可通过 daemon 内存中的异步 auth session API 完成 browser/device-code 流程，支持查询、手动 code、取消、超时和凭据安全持久化。
- [x] T5：`recall dashboard --store <path>` 自动启动/连接 daemon 并打开同源 Web Dashboard；页面只提供 Search、Ask 与命中 chunk/metadata 预览，安全显示知识库及模型文本。
- [x] T6：API 资源、Dashboard 资源和新增依赖正确进入 wheel；README 记录发现 API、认证、端点、Dashboard 和后续 MCP 消费方式，所有现有 CLI 行为保持兼容。
- [x] T7：单元、API 契约、daemon 双 transport/串行/idle、OAuth、Dashboard 安全、生成 bridge、提取 wheel 与真实本机 smoke 全部通过。

## Plan

1. 固化 API schema、认证、HTTP 状态映射和 transport seam，补充 FastAPI/Uvicorn 依赖与失败测试。
2. 实现安全 Token 存储、HTTP application、完整 REST 路由及 CLI 语义适配。
3. 将 HTTP Server 纳入 per-store daemon 生命周期，统一请求锁、环境边界、activity 计时、动态端口发现和停止清理。
4. 扩展 Node bridge 与 Python client，提供可轮询、可取消、可超时的 OAuth 登录会话。
5. 实现并打包无框架 Dashboard，完成 Search、Ask、来源卡片、chunk 展开预览及安全错误状态。
6. 接入 `recall dashboard`、daemon status/API URL 与英文 help，更新配置、文档和工作区上下文。
7. 依次运行聚焦测试、全量 Python/Node/TypeScript/lint/audit/build、生成 bridge 与提取 wheel API/Dashboard smoke，并修复所有范围内回归。

## Result

- T1：`tests/test_daemon.py` 以临时 store 验证 Unix 与动态 loopback HTTP 同时可用、共享单一 app、HTTP 刷新 idle、HTTP stop 同时关闭两种 transport；真实默认 store smoke 也验证 status 的 `api_url` 可访问。
- T2：`tests/test_api_token.py` 验证跨进程首次创建返回同一 Token 及 `0700`/`0600` 权限；API 契约测试验证 Bearer、精确 Host/Origin、无 CORS、CORP/CSP、恶意 Origin 拒绝及公开脚本不泄漏 Token。
- T3：`tests/test_http_app.py` 验证固定 OpenAPI 路由集合、仅 `/v1/*` 标注 Bearer、完整 RAG/config/provider/daemon 端点、validation envelope、稳定状态映射和 HTTP `207 PARTIAL_FAILURE`。
- T4：Node controller、packaged bridge、Python session manager 与 HTTP 契约测试覆盖 browser/device code 事件、manual code、冲突、自动超时、HTTP 410、取消、bridge 崩溃和终态回收；凭据继续由既有 `FileCredentialStore` 安全持久化。
- T5：`recall dashboard` 默认调用系统浏览器，`--json` 不打开；Dashboard 使用本地模型目录、Search/Ask、键盘可展开的 source/chunk metadata 预览及 XSS-safe DOM API。真实本机 API smoke 得到 3 个搜索结果、3 个回答来源及 `content`/`metadata` 预览字段。
- T6：README 与工作区上下文已同步；`uv build` 产出的 wheel 包含 FastAPI/Uvicorn metadata、Dashboard 资源和生成 bridge，`tests/extracted_wheel_smoke.py` 在提取产物中验证 root、Bearer health/search 与 login-session loader。
- T7：最终验证通过：103 个 Python unittest、10 个 Node tests、TypeScript check、Ruff、`uv lock --check`、npm audit（0 vulnerabilities）、bridge build、sdist/wheel build、提取 wheel smoke及真实本机 Dashboard/Search/Ask/stop smoke。
- Review gate: Skipped — no explicit user request. 另执行三轮普通 fresh-context correctness/security/UI 复审；发现的 Token 跨站泄漏与 OAuth waiting-crash 问题均修复，最终复审无 blocker。
