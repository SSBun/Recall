# 添加配置命令与交互式配置向导

Status (2026-07-29 09:23): Completed

Goal:
- 提供可脚本化及交互式的配置入口，调整默认检索数量、标注模型和问答模型。

Scope:
- 新增 `recall config list` 与 `recall config set <key> <value>`。
- 纯 `recall config` 启动单选菜单式 setup 向导，显示当前值并可编辑 search limit、tag model、ask model 或退出。
- 支持 `search.limit`、`models.tag`、`models.ask`；`search.limit` 同时作为 `search` 和 `ask` 的默认值，显式 `--limit` 优先。
- 原子更新 `~/.config/recall/config.toml`，保留未修改的现有 TOML 内容。

Non-goals:
- 不增加通用 Recall shell、embedding 模型配置、凭据配置或远程配置。
- 不让 config 命令启动 RAG daemon。
- 不新增 TOML 写入依赖。

Targets:
- [x] T1：list/set 命令可在人类及 `--json` 模式读取、验证并更新三个支持键。
- [x] T2：纯 config 命令进入单选菜单式配置向导，可查看当前值、编辑三项设置、返回菜单并安全退出。
- [x] T3：search/ask 在未传 `--limit` 时读取 `search.limit`，显式参数保持最高优先级。
- [x] T4：配置写入原子化、权限收紧且保留现有 section、注释和未知设置。
- [x] T5：全部 help 保持英文，测试、静态检查、构建及真实 CLI smoke 通过。
- [x] T6：在菜单向导配置 tagging/ask model 时，列出当前已配置凭据实际可用的全部 `provider/model` 并允许直接选择，同时保留其他配置行为。

Plan:
1. 通过现有 Pi bridge 暴露已配置 provider 的可用模型引用，保持 Recall 专属凭据与环境变量认证边界。
2. 在 tagging/ask model 编辑路径复用现有选择器显示完整模型列表；search limit 与脚本化 list/set 不变。
3. 补充 bridge、Python client、TTY/非 TTY 菜单测试，更新文档并完成全量构建验证。

## Result

- T1：`recall config list/set` 以人类或版本化 JSON 管理 `search.limit`、`models.tag`、`models.ask`，无效值在写入前返回 `USAGE_ERROR`。
- T2：纯 `recall config` 启动菜单式 setup 向导；TTY 使用 cmd2 单选/输入，非 TTY 使用 `●`/`○` 编号 fallback，可编辑后刷新当前值并通过 Exit、EOF 或 Ctrl-C 结束；不调用 `cmdloop`，不暴露通用命令 shell。
- T3：search/ask 按 `--limit` > `[search].limit` > `5` 解析；daemon 每请求重读配置，无需重启。
- T4：配置定点更新保留未知 section、注释、格式分隔和 symlink，以同目录临时文件原子替换并维持 `0700`/`0600` 权限。
- T5：58 个 Python 测试、7 个 Node 测试、Ruff、`uv lock --check`、TypeScript、npm audit（0 漏洞）、构建和 wheel 内容检查通过；README、上下文和包内仅保留 `config_prompt.py`。
- Review gate: Required — 涉及用户配置写入、交互边界和后续 UX 修正；Decision: `APPROVED` — 四轮累计审查后无未解决 finding，[对抗审查报告](../../reports/adversarial-review/add-config-command.md)。
- T6：Pi bridge 通过 `Models.refresh()` 与 `getAvailable()` 返回 Recall 凭据文件或当前环境已配置 provider 的全部 `provider/model`；tagging/ask 编辑菜单显示所有引用、优先当前值并提供 Back。当前 Codex OAuth smoke 在源码和提取 wheel 中均列出 7 个模型；61 个 Python 测试、8 个 Node 测试、Ruff、TypeScript、`uv lock --check`、npm audit（0 漏洞）及 `uv build` 全部通过。
- Review gate (T6 follow-up): Skipped — no explicit user request.
