# 保留 cmd2 供应商向导并移除通用 Shell

Status (2026-07-28 14:16): Completed

## Scope

- 包含：`recall provider login` 省略 provider 时的 cmd2 选择向导，以及显式 provider 和 JSON 兼容边界。
- 不包含：通用交互式 shell、命令循环、历史、别名、脚本、全屏 TUI、自定义 provider 注册或新增认证方式。

## Target

- [x] T3：`recall provider login` 无 provider 参数时显示交互式选择向导；显式 `provider login openai-codex` 和机器 JSON 行为保持可用。
- [x] T5：按最新范围移除通用交互式 shell、历史及其命令入口，仅在 `provider login` 缺省 provider 时保留 cmd2 选择向导。

## Plan

1. 删除通用 shell 入口、会话实现和专属测试。
2. 把 provider 选择向导保留为独立 cmd2 prompt，并维持显式 provider/JSON 边界。
3. 更新文档与工作区事实，验证 CLI 命令面和 wheel 不再暴露 shell。

## Result

- T3：`provider login` 的 provider 参数保持可选，交互模式通过独立 `provider_prompt.py` 使用 cmd2 选择菜单；显式 provider 仍可脚本化，`--json` 缺少 provider 时 fail-closed 返回 `USAGE_ERROR`。
- T5：已删除 `recall shell`、`RecallShell`、历史、会话缓存及 shell 专属测试；帮助只列出一次性命令，wheel 包含 `provider_prompt.py` 且不含 `shell.py`。33 个 Python 测试、7 个 Node 测试、Ruff、TypeScript、lock、audit（0 漏洞）、构建、wheel 内容和无 shell CLI smoke 全部通过；README、API 设计、技术选型和工作区上下文已同步。
- Review gate: Skipped — 删除通用入口并保留单一 provider prompt，命令面、向导调用、JSON 边界和 wheel 内容均有确定性验证，无核心验证缺口。
