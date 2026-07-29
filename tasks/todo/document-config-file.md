# 配置文件使用指南

Status (2026-07-28 17:09): Completed

Goal:
- 在项目 README 中提供可直接操作的配置文件指南，让用户知道如何创建配置、可调整哪些设置、优先级和生效时机。

Scope:
- 更新 `README.md` 的配置说明。
- 只记录 `src/recall/config.py` 当前支持的设置，不新增配置能力或示例配置文件。

Non-goals:
- 不修改配置解析、默认值、CLI 参数或认证存储。
- 不创建第二份 README 或新的配置格式。

Targets:
- [x] T1：说明配置文件是可选 TOML、默认位置和创建方式。
- [x] T2：逐项说明 `[models].tag`、`[models].ask`、`[index].concurrency` 的用途、格式和默认值。
- [x] T3：说明 CLI、环境变量、配置文件和默认值的优先级，以及 store 和凭据不属于该 TOML。
- [x] T4：文档内容与当前实现和测试保持一致。

Plan:
1. 以 `src/recall/config.py` 和配置测试为事实来源核对全部支持项。
2. 将 README 现有简短配置段扩展为创建步骤、完整示例、设置表和覆盖规则。
3. 逐项对照源码，并运行配置测试及 Markdown 结构检查。

## Result

- T1：README 新增独立“配置文件”章节，说明文件可选、默认位置，并提供可直接执行的创建命令和完整 TOML。
- T2：设置表覆盖当前实现仅支持的三个键，并记录用途、格式和默认值；另给出 Codex 问答及并发调整示例。
- T3：覆盖表明确 CLI > 环境变量 > TOML > 默认值；单独说明 store 仅由 `--store`/`RECALL_STORE` 控制，凭据应使用供应商环境变量或 `auth.json`。
- T4：逐项对照 `src/recall/config.py`；4 个配置测试通过，README 结构脚本确认全部键和覆盖环境变量均已记录。
- Review gate: Skipped — 仅增加与现有实现一致的说明文档，不改变代码、配置语义或数据边界。
