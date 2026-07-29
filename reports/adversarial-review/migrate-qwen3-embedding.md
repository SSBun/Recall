---
created: 2026-07-28
task: migrate-qwen3-embedding
review_cycles: 1
---

# Qwen3 Embedding 切换与数据库迁移对抗审查

Topic: 模型语义、向量空间约束与运行时兼容

> **E1:** 将固定嵌入模型切换到 `Qwen/Qwen3-Embedding-0.6B`；文档和查询分别调用 `encode_document` / `encode_query`，输出归一化 1024 维向量。Chroma collection 记录模型和维度，并在 upsert/query 及旧 store 打开路径上 fail closed。
>
> **R1:** 初审逐项验证 Qwen3 query instruction、缓存优先/下载回退、1024 维检查、非空旧 collection 拒绝、daemon 单模型复用和 wheel 分发，未发现 blocker 或 question，返回 `APPROVED`。

**Conclusion:** 模型调用语义、维度 invariant 和旧数据拒绝边界正确且保持最小实现。

Topic: 默认 Store 数据迁移与检索结果

> **E1:** 在来源哈希全部未变化后，从旧清单重建 sibling store，保留 118 个 document ID、category、tags 和 summary；验证 2124 chunks 后原子替换默认目录，并保留旧 BGE store 与 manifest 回滚副本。
>
> **R1:** 初审核对新旧 ID 集合、collection 元数据、跨语言 English→Chinese 检索、grounded ask、46 个 Python 测试、7 个 Node 测试、Ruff、lock、TypeScript、audit、构建及提取 wheel smoke，确认迁移完整。仅记录任务清单尚待正常收尾勾选的非阻塞 NOTE。

**Conclusion:** 默认数据库已完整进入 Qwen3 向量空间，标注和稳定身份未丢失，回滚材料完整。

---

**Final decision:** `APPROVED`

**Outcome:** Qwen3 Embedding 切换与默认 Store 迁移通过一轮独立对抗审查。

**Remaining:** none
