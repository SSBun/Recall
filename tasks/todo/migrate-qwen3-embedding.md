# 切换 Qwen3 Embedding 并重建数据库

Status (2026-07-28 22:55): Completed

Goal:
- 将 Recall 的固定嵌入模型切换为 `Qwen/Qwen3-Embedding-0.6B`，使用适合 query/document 的独立编码入口，并将默认 store 安全重建到新的 1024 维向量空间。

Scope:
- 更新嵌入封装、Store 模型/维度约束、相关测试、README、技术选型和工作区上下文。
- 停止默认 store daemon；从现有 118 份记录及原始文件重建新 store，保留 document ID、category、tags、summary，并保留旧 BGE store 作为回滚备份。
- 使用归一化 1024 维向量和 cosine 距离。

Non-goals:
- 不新增可配置 embedding 模型、在线模型切换、自动多模型迁移或混合向量集合。
- 不重新调用 Pi 标注模型；来源内容未变化时复用现有文档级标注。
- 不修改历史 `docs/plans` 文档，除非用户另行确认。

Targets:
- [x] T1：文档使用 `encode_document`，查询使用 Qwen3 的 `encode_query` instruction，输出归一化 1024 维向量。
- [x] T2：Chroma collection 记录并校验 embedding 模型与维度，拒绝旧模型或错误维度向量混入。
- [x] T3：默认 store 的 118 份文档及全部 chunks 在新向量空间重建，保留 ID 和文档 metadata；旧 store 可回滚。
- [x] T4：英文查询能够跨语言检索到相关中文 MyWiki 文档，原有索引、检索、ask 和 daemon 行为保持通过。
- [x] T5：测试、静态检查、构建、真实模型 smoke、数据库完整性及独立对抗审查通过。

Plan:
1. 锁定旧 store 清单和来源哈希，停止 daemon，先为新模型行为与 Store 边界补充失败测试。
2. 最小替换嵌入实现并加入 collection 模型/维度 invariant，更新当前文档。
3. 下载并验证 Qwen3，离线构建临时 store；验证后原子切换目录并保留旧 store。
4. 运行完整测试、跨语言检索/问答、wheel 和 daemon smoke，完成独立审查。

## Result

- T1：`QwenEmbedder` 固定加载 `Qwen/Qwen3-Embedding-0.6B`，优先使用完整本地缓存、缺失时回退 Hugging Face 下载；实际模型确认内置 query instruction，document/query 输出均归一化为 1024 维。
- T2：Chroma collection metadata 持久化 `embedding_model` 和 `embedding_dimensions`；非空旧 collection 或任一非 1024 维文档/查询向量会在 Store 边界被拒绝，空 collection 可安全补齐 metadata。
- T3：迁移前 118 个来源哈希全部匹配；新 store 保留全部 document ID、category、tags、summary，最终为 118 documents/2124 chunks/118 fully tagged。旧 BGE store 保存在 `/Users/caishilin/.local/share/recall/db-bge-backup-20260728-2152`，旧清单保存在同名 `.manifest.json`。
- T4：英文 `How do I test my IP address quality?` 的 top 3 均命中中文网络文档；原始 `recall ask` 已返回基于 Check.Place、NodeQuality 和 UnlockTests 的 grounded answer。
- T5：46 个 Python 测试、7 个 Node 测试、Ruff、`uv lock --check`、TypeScript、npm audit（0 漏洞）和 `uv build` 全部通过；提取 wheel 通过独立 daemon 对新默认 store 完成真实 Qwen 英文跨语言检索。
- Review gate: Required — 涉及默认数据库替换、文档身份/metadata 保留及向量空间兼容；Decision: `APPROVED` — 一轮后无未解决 finding，[对抗审查报告](../../reports/adversarial-review/migrate-qwen3-embedding.md)。
