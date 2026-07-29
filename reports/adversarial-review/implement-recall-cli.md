---
created: 2026-07-28
task: implement-recall-cli
review_cycles: 3
---

# Recall 内置 Pi SDK bridge 对抗审查

Topic: bridge 失败响应与进程退出码是否保持 fail-closed

> **E1:** bridge 捕获模型错误后输出版本化 `ok:false` envelope，并设置 `process.exitCode = 1`；Python 同时校验退出码和响应 envelope。
>
> **R1:** 初审怀疑“模型存在但认证缺失”路径可能退出 `0`，要求核实；该轮在输出完整 finding 后超出执行预算，不能作为批准。
>
> **E2:** 使用 `${PIPESTATUS[1]}` 精确捕获 Node 退出码，确认认证缺失、模型不存在、无效 JSON 和空 prompt 均退出 `1`；拒绝改用可能截断 stdout 的 `process.exit(1)`，未修改产物。
>
> **R2:** 复审确认初审 finding 被证伪并给出批准结论，但进程在输出后超出执行预算，因此继续保持 gate 阻塞。
>
> **E3:** 产物未变化，保留同一源码、运行证据和完整 finding ledger。
>
> **R3:** 独立终审确认 R1–R7 全部解决，无新增 finding，返回 `APPROVED`。

**Conclusion:** 所有 bridge 失败路径均返回结构化错误和退出码 `1`，Python 消费边界继续 fail-closed。

Topic: 模型、认证、打包和范围边界

> **E1:** Recall 通过 wheel 内置的 Node bridge 调用 `@earendil-works/pi-ai`；模型由 Recall 参数、环境变量和 TOML 解析，认证只读取供应商环境变量或 Recall 专属静态 API key 文件。
>
> **R1:** 初审确认无外部 `pi`、无 `~/.pi/agent`、无密钥回显，wheel 可脱离 `node_modules` 启动，模型优先级、格式校验和既有失败隔离均有测试覆盖。
>
> **E2:** 对全部确认性 NOTE 逐项回应，不扩大到交互登录、自定义供应商或 daemon，也未修改产物。
>
> **R3:** 终审依据 23 个 Python 测试、6 个 Node `fauxProvider` 测试、Ruff、TypeScript、lock、audit、构建和 wheel smoke 证据批准当前范围。

**Conclusion:** 内置 SDK、Recall 自有配置/认证边界、离线验证和可分发产物均满足已确认架构。

---

**Final decision:** `APPROVED`

**Outcome:** Recall 的内置 Pi SDK bridge、模型/认证边界与 wheel 分发通过独立对抗审查。

**Remaining:** none
