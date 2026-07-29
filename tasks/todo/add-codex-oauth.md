# 为 Recall 接入 ChatGPT Codex OAuth

Status (2026-07-28 14:08): Completed

## Scope

- 包含：`openai-codex` OAuth 登录、凭据持久化与刷新、登录状态查看、登出、CLI/JSON 边界、打包、文档和离线测试。
- 不包含：自定义供应商注册、复制 Pi 全局凭据、API key 登录向导、后台 daemon 或真实账号自动化登录测试。

## Target

- [x] T1：`recall provider login openai-codex` 通过内置 Pi SDK 完成 ChatGPT Plus/Pro OAuth，并把凭据以仅当前用户可读的方式保存到 Recall 专属 `auth.json`。
- [x] T2：`provider list` 不暴露秘密，`provider logout openai-codex` 可删除凭据；供应商命令不初始化 Chroma 或 BGE。
- [x] T3：标注与问答使用同一持久化 credential store，OAuth 刷新结果可跨进程保存，同时保留静态 API key 与既有错误语义。
- [x] T4：离线测试覆盖登录持久化、刷新、登出、CLI 和 wheel bridge；README 与架构文档说明 Codex OAuth 用法和安全边界。
- [x] T5：包内 `model_bridge.mjs` 的 Codex OAuth 登录和刷新不依赖 wheel 中不存在的动态相对模块。
- [x] T6：人类可读的 `provider list` 按认证供应商显示已连接/未连接状态，不输出 JSON 对象；`--json` 机器协议保持不变。

## Plan

1. 为 provider list 的人类输出补充连接/未连接状态回归测试。
2. 仅在非 JSON provider list 路径格式化已支持认证供应商状态。
3. 验证机器 JSON、安全边界和既有命令保持不变。

## Result

- T1：`provider login openai-codex` 通过打包 bridge 调用 Pi SDK；生成物回归和用户原始 CLI 路径均越过 OAuth 加载点并显示浏览器/设备码登录选择，凭据仍由 `FileCredentialStore` 以 `0700`/`0600` 权限持久化。
- T2：`provider list` 仅返回 provider ID 与 credential 类型，`provider logout` 幂等删除；CLI 测试证明供应商分支不会创建 `RecallApp`、Chroma 或 BGE。
- T3：completion 与 provider 命令继续复用 `FileCredentialStore`；Pi SDK 的静态 loader 注册同时提供同一 Codex OAuth 对象的 login、refresh 和 toAuth，既有假 OAuth 刷新持久化及并发更新测试全部通过。
- T4：34 个 Python 测试、7 个 Node 测试、Ruff、TypeScript、`uv lock --check`、`npm audit`（0 漏洞）、`uv build` 与提取 wheel 的 Codex 登录加载验证全部通过；真实账号授权仍按范围由用户手动执行。
- T5：根因是 Pi SDK 为普通包设计的动态相对 OAuth import 被保留在独立 esbuild bundle 中；bridge 现调用公开 `registerBunOAuthFlows()` 静态嵌入 OAuth loader，生成物与 wheel 均不再出现 `Cannot find module`。
- T6：`provider list` 默认输出 `OpenAI Codex（ChatGPT Plus/Pro OAuth）: 已连接|未连接`，不包含内部 JSON 字段或花括号；`provider list --json` 的版本化 envelope、provider ID/type 与无秘密契约保持不变。35 个 Python 测试、7 个 Node 测试、Ruff、TypeScript、lock、audit（0 漏洞）及真实本地已连接/机器输出 smoke 全部通过。
- Review gate: Required（T1–T5）— OAuth 登录/刷新涉及 secret、权限和跨进程状态；Decision: `APPROVED` — 5 个累计 Reviewer pass 后无未解决 finding，[对抗审查报告](../../reports/adversarial-review/add-codex-oauth.md)。T6 Review gate: Skipped — 仅改变非 JSON 展示层，机器协议和 credential store 均未修改，已连接/未连接及 `--json` 均有确定性回归与实际 CLI smoke。
