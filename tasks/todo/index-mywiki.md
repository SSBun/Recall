# 索引 MyWiki 并自动标注

Status (2026-07-28 19:22): Completed

Goal:
- 将 MyWiki 下 Recall 支持的文档递归索引到默认 store，并为每份文档生成 category、tags 和 summary。

Scope:
- 来源：`/Users/caishilin/Library/Mobile Documents/com~apple~CloudDocs/MyWiki`
- Store：`/Users/caishilin/.local/share/recall/db`
- 标注模型：`openai-codex/gpt-5.4-mini`（当前已连接的 OpenAI Codex provider）

Targets:
- [x] T1：发现并提交全部 Markdown、TXT 和 PDF 文档。
- [x] T2：成功文档包含自动标注结果，失败文档保留逐项错误。
- [x] T3：索引结果可通过 `recall list/search` 查询。

Plan:
1. 核对来源目录、支持文件数量、默认 store、模型配置及认证状态。
2. 使用显式 Codex 标注模型递归执行幂等索引。
3. 检查命令结果及数据库列表，记录成功、失败和可复现查询。

## Result

- T1：递归发现并索引 118 份受支持文档；并发值为 4，命令退出码为 0，`indexed=118`、`unchanged=0`、`failed=0`。
- T2：以 `openai-codex/gpt-5.4-mini` 完成自动标注；按来源根路径复核后 118/118 文档均具有非空 category、tags 和 summary。
- T3：`recall list --json` 返回全部 118 份 MyWiki 文档；`recall search 'RAG 技术选型' --limit 3 --json` 返回 3 条相关结果。
- Review gate: Skipped — 本任务仅通过既有、已验证的幂等 CLI 写入用户明确指定的本地知识库；结果已用列表、标注完整性和检索检查直接验证。
