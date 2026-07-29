---
created: 2026-07-28
task: add-codex-oauth
review_cycles: 5
---

# Recall Codex OAuth 接入对抗审查

Topic: OAuth credential 的持久化、安全权限与并发刷新

> **E1:** 使用 Recall 专属 `FileCredentialStore` 保存静态 API key 与 OAuth credential；父目录和文件权限分别收紧为 `0700` 与 `0600`，读改写由跨进程锁串行化，临时文件以 `0600` 创建后原子替换。
>
> **R1:** 初审确认 OAuth 额外字段和旋转后的 refresh token 均被保留，并提出锁目录自身权限较宽的非阻塞 NOTE；该目录位于不可遍历的 `0700` 父目录下且不含秘密。
>
> **E2:** 拒绝增加无实际风险收益的锁目录 chmod，逐项确认 credential store 契约、原子写入、刷新持久化、并发更新与登出证据；未修改产物。
>
> **R2:** 复审确认全部 NOTE 已闭环并输出批准结论，但进程在输出后超出执行预算，因此继续保持 gate 阻塞。
>
> **E3:** 产物未变化，保留同一源码、测试和完整 finding ledger。
>
> **R3:** 独立终审确认 R1–R10 全部解决，无新增 finding，返回 `APPROVED`。

**Conclusion:** Recall 的 OAuth credential 存储、权限、刷新轮换和跨进程更新满足安全与数据完整性要求。

Topic: Codex 登录交互、CLI 协议与既有行为兼容

> **E1:** `provider login openai-codex` 直接调用内嵌 Pi SDK；浏览器/设备码提示写入 stderr，最终版本化结果写入 stdout；list/logout 不创建 Chroma、BGE 或 `RecallApp`。
>
> **R1:** 初审确认失败和取消会映射为 `PI_ERROR`，SDK 负责关闭 OAuth callback server，凭据列表不输出秘密，wheel 的 list/logout 操作可独立执行。
>
> **E2:** 对全部确认性 NOTE 给出源码和测试证据，不扩大到自定义 provider、API key 向导、daemon 或真实账号自动化。
>
> **R3:** 终审依据 26 个 Python 测试、7 个 Node 假 OAuth/供应商测试、Ruff、TypeScript、lock、audit、构建和 wheel smoke 证据批准当前范围。

**Conclusion:** Codex OAuth 交互和供应商命令保持机器协议、失败语义、分发能力与原 RAG 功能兼容。

Topic: wheel 内 Codex OAuth 动态加载修复

> **E4:** 用户实际登录发现生成 bridge 会从 wheel 内错误解析不存在的 `openai-codex.js`；改用 Pi SDK 面向独立 bundle 的公开 `registerBunOAuthFlows()` 静态注册入口，重建 bridge，并增加生成物及提取 wheel 的登录加载回归验证。
>
> **R4:** 初审确认登录已越过 OAuth 懒加载点、credential 安全边界未变且修复最小；仅记录即时 EOF 时既有顶层 await 警告与退出码 13 的非阻塞 NOTE。
>
> **E5:** 确认该 EOF 行为早于本次修复，`PiClient` 将任意非零退出码统一视为失败，且 TLA/EOF 重构属于明确非目标，因此不修改充分的产物。
>
> **R5:** 复审重跑 Node、Python、Ruff、lock、audit、build 与提取 wheel 验证，确认 NOTE 已闭环、无新增 finding，返回 `APPROVED`。

**Conclusion:** wheel 内 bridge 现已静态包含 Codex OAuth 登录与刷新实现，不再依赖不存在的运行时相对模块。

---

**Final decision:** `APPROVED`

**Outcome:** Recall 的 ChatGPT Plus/Pro Codex OAuth 接入通过独立对抗审查。

**Remaining:** none
