# 实现 Recall CLI MVP

Status (2026-07-28 16:55): Completed

## Scope

- 包含：可安装 Python CLI、Chroma/BGE 检索、Pi 自动标注与问答、批量索引、机器 JSON 协议、Pi Extension、文档和自动化测试。
- 不包含：后台 daemon、图形界面、多 store 管理、远程 Chroma、交互式供应商登录和发布流程。

## Target

- [x] T1：`recall` 提供已确认的 `index`、`remove`、`list`、`show`、`search`、`ask`、`retag` 命令及版本化 JSON envelope。
- [x] T2：索引支持稳定文档 ID、变更/重命名识别、Pi 批量标注、`--no-tag` 语义、可配置并发和逐文档失败隔离。
- [x] T3：检索使用 BGE-small-zh 与持久化 Chroma；`ask` 默认严格依据来源，并支持显式通用知识补充。
- [x] T4：Pi Extension 仅通过 `recall search --json` 暴露检索工具。
- [x] T5：README、设计文档和可重复验证覆盖安装、配置、命令、错误及关键验收场景。
- [x] T6：标注与问答由 Recall 内置的 Node bridge 调用 Pi SDK，运行时不再调用或读取外部 Pi CLI。
- [x] T7：Recall 自己解析模型默认值与覆盖项，并使用 Recall 专属认证/模型配置路径；既有 `--tag-model`、`--model` 和失败语义保持兼容。
- [x] T8：离线测试覆盖 Python/Node bridge 协议、模型解析和供应商失败，安装及架构文档与新边界一致。
- [x] T9：默认 `ask` 输出直接呈现答案和来源，不转储 JSON；BGE 初始化不输出 Hugging Face 未认证警告或权重进度条，`--json` 机器协议保持不变。
- [x] T10：顶层、所有子命令和嵌套子命令的 argparse help 全部使用英文，不残留中文帮助文本。

## Plan

1. 枚举顶层、RAG、provider 和 daemon 的全部 help 路径并增加语言回归测试。
2. 只翻译 argparse description/help 文案，不改变命令名、参数、运行输出或错误协议。
3. 验证每个 `--help` 输出均为英文且不会启动 daemon。

## Result

- T1：构建并安装 `recall` console script；CLI parser/JSON seam 测试覆盖成功、用法错误与 `PARTIAL_FAILURE`，`uv build` 成功生成 sdist 与 wheel。
- T2：索引服务测试覆盖重复 no-op、重命名、移动后编辑显式关联、`--no-tag` 新旧语义、Pi/文件/嵌入失败隔离及并发优先级。
- T3：真实 `BAAI/bge-small-zh-v1.5` smoke test得到 512 维向量；临时 Chroma store 完成索引、重开、过滤检索、更新与删除；最终 CLI/Chroma/BGE 端到端 smoke 通过。
- T4：Extension parser 的 Node 测试与 TypeScript 检查通过；`PI_OFFLINE=1 pi --no-extensions -e ./agent/extensions/rag-search.ts --list-models` 证明实际 Pi 可加载 Extension。
- T5：README、技术选型文档与 API 设计已同步；19 个 Python 测试、2 个 Node 测试、Ruff、TypeScript、`uv lock --check`、`npm audit`（0 漏洞）及 fake-Pi 端到端 smoke 全部通过。
- T6：`PiClient` 现以版本化 JSON stdin/stdout 调用随 wheel 分发的 `model_bridge.mjs`；bridge 直接使用 `@earendil-works/pi-ai`，提取 wheel 后在无 `node_modules` 环境启动并对错误返回结构化 envelope 与退出码 `1`。
- T7：模型优先级与 `provider/model` 校验由 Recall 配置层实现；bridge 仅使用供应商标准环境变量或 `~/.config/recall/auth.json` 静态 API key，源码与检索均确认没有外部 `pi` 或 Pi 全局认证依赖。
- T8：23 个 Python 测试、6 个 Node `fauxProvider` 测试、Ruff、TypeScript、`uv lock --check`、`npm audit`（0 漏洞）、`uv build` 和提取 wheel bridge smoke 全部通过；README、API 设计和技术选型文档已同步。
- T9：默认 `ask` 只打印答案，有来源时追加 `来源：` 和编号路径；`--json` 继续返回完整版本化 envelope。BGE 在导入模型前设置 Hugging Face/Transformers 静默环境，用户复现命令的 stderr 已为空。35 个 Python 测试、7 个 Node 测试、Ruff、TypeScript、lock、audit（0 漏洞）、真实 human/JSON ask smoke 与 `uv build` 全部通过。
- T10：顶层及 14 条 RAG/provider/daemon help 路径均改为英文；新增 subprocess 回归枚举全部 `--help` 并覆盖缺失顶层/provider/daemon 子命令的英文 help+`USAGE_ERROR`。43 个 Python 测试、Ruff、lock 与 wheel 文案检查通过。
- Review gate: Required（T1–T8）— 改动跨越 Python/Node 协议、供应商认证和分发边界；Decision: `APPROVED` — [对抗审查报告](../../reports/adversarial-review/implement-recall-cli.md)。T9–T10 Review gate: Skipped — 仅调整人类展示、第三方库日志环境与 argparse help 文案，数据、命令参数和机器协议未改，默认/JSON/help/error 输出均有确定性验证。
