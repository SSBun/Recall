# 优化公开文档并创建公开仓库

Status (2026-07-29 18:41): Completed

## Scope

- 包含：面向公开发布的中英文 README、中英文完整使用指南、文档内视觉排版、MIT 许可证，以及创建并关联公开 GitHub 仓库。
- 不包含：Logo 图片或其他生成图像、发布到 PyPI、社交平台文案或宣传视频。

## Target

- [x] T1：英文与中文 README 均能清晰传达 Recall 的价值、核心能力、快速开始、安全边界和深入文档入口，并且所有声明与当前实现一致。
- [x] T2：英文与中文 GUIDE 覆盖安装、认证、配置、索引、检索、问答、Dashboard、HTTP API、数据管理、故障排查和开发验证，代码示例可复制执行。
- [x] T4：文档链接、Markdown 结构、关键 CLI 示例和打包流程经过可复现验证，不虚构尚未存在的发布渠道、Logo 或许可证。
- [x] T5：创建公开 GitHub 仓库并配置当前仓库的 `origin`，推送完整提交历史且远端默认分支与本地 `main` 一致。
- [x] T6：项目以 MIT License 公开，源码、Python 包元数据、中英文 README 与构建产物使用一致的 SPDX 标识并可被 GitHub 和打包工具识别。

## Plan

1. 基于当前 CLI、Dashboard、API 与打包配置提炼公开定位和信息架构。
2. 将 README 重构为简洁的公开项目主页，把完整操作细节迁移到双语 GUIDE，并使用纯 Markdown/HTML 排版建立视觉层次。
3. 校验语言切换、相对链接、命令示例、Markdown 结构和构建结果，修正不准确内容。
4. 创建并配置公开 GitHub 仓库，在本地文档提交完成后推送 `main`。
5. 添加 MIT License、同步项目元数据与双语文档，并验证构建产物及 GitHub 许可证识别。

## Result

- T1：`README.md` 与 `README.zh-CN.md` 已重构为双语公开项目首页，包含价值主张、能力矩阵、快速开始、Mermaid 架构图、本地优先隐私边界和完整指南入口；两种语言结构一致。
- T2：`docs/GUIDE.md` 与 `docs/GUIDE.zh-CN.md` 分别提供英文和中文完整指南，覆盖安装、供应商与本地模型目录、配置、索引语义、检索问答、文档管理、Dashboard、daemon、HTTP API、备份、集成、故障排查和开发验证。
- T4：自定义链接检查确认 4 份文档的相对链接全部存在；全部 CLI help 路径可解析且英文 help 测试通过；`git diff --check` 与 `uv build` 通过，wheel metadata 已包含新版 README；按用户最新范围未生成 Logo，也未声明许可证或 PyPI 发布。
- T5：已创建公开仓库 `https://github.com/SSBun/Recall`，配置 `origin` 并推送完整 `main` 历史；GitHub API 确认远端默认分支为 `main`、README 与 GUIDE 可访问，且本地 HEAD 与 `origin/main` 一致；已添加 RAG、local-first、knowledge-base、ChromaDB、Qwen3、CLI、FastAPI、OpenAPI topics。
- T6：新增标准 MIT `LICENSE`（版权主体 `SSBun`），`pyproject.toml` 使用 SPDX `license = "MIT"` 并声明 license file，中英文 README 均加入 MIT badge 与许可证章节；`uv build` 验证 sdist 包含 `LICENSE`，wheel 包含 `License-Expression: MIT` 和 `dist-info/licenses/LICENSE`，GitHub GraphQL 识别为 `MIT License`。
- Review gate: Skipped — no explicit user request.
