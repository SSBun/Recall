# RAG 系统技术选型文档

> 日期：2026-07-27
> 项目：Recall - 个人知识库 RAG 系统

---

## 一、需求概述

构建一个轻量级 RAG（Retrieval-Augmented Generation）系统，核心能力：

| 需求 | 说明 |
|---|---|
| **文档入库** | 读取本地文档，分块，打标签，存入向量数据库 |
| **语义检索** | 输入问题，返回最相关的文档片段 |
| **持久化存储** | 数据存本地，下次启动可复用 |
| **增删改查** | 支持文档的添加、更新、删除 |
| **Agent 集成** | 对外提供检索接口，供 AI Agent 调用 |

---

## 二、技术选型

### 2.1 向量数据库：Chroma

| 维度 | 选择 | 理由 |
|---|---|---|
| **产品** | Chroma | 轻量、嵌入式、零配置 |
| **运行模式** | PersistentClient | 数据持久化到本地 SQLite 文件 |
| **索引算法** | HNSW（默认） | 高效近似最近邻搜索 |
| **存储方式** | SQLite + HNSW 索引文件 | 完整 store 目录可整体备份迁移 |
| **数据量上限** | 百万级 | 满足个人知识库需求 |

**备选方案对比：**

| 方案 | 优势 | 劣势 | 结论 |
|---|---|---|---|
| **Chroma** | 零配置，4 个 API，自动持久化 | 不支持分布式 | ✅ 首选 |
| **FAISS** | 性能最好，支持亿级 | 只存向量，不存文本，需自己管理 | ❌ 太重 |
| **NumPy 纯内存** | 最简单，无依赖 | 不持久化，重启需重新加载 | ❌ 不满足持久化需求 |
| **JSON 文件** | 零依赖 | 存浮点数效率低，大文件慢 | ❌ 不推荐 |

### 2.2 嵌入模型：Qwen3-Embedding-0.6B

| 维度 | 选择 | 理由 |
|---|---|---|
| **模型** | Qwen/Qwen3-Embedding-0.6B | 支持 100+ 语言和跨语言检索，适合中英混合知识库 |
| **维度** | 1024 维 | 使用完整输出维度保证检索质量 |
| **框架** | Sentence-Transformer | 提供独立 `encode_document` / `encode_query` 入口及 query instruction |
| **规模** | 0.6B 参数 | daemon 常驻后在多次命令间复用模型 |

**备选方案对比：**

| 模型 | 维度 | 跨语言效果 | 规模 | 结论 |
|---|---|---|---|---|
| **Qwen3-Embedding-0.6B** | 1024 | 好 | 0.6B 参数 | ✅ 首选 |
| **BGE-small-zh** | 512 | 弱 | ~92MB | 中文轻量备选 |
| **BGE-large-zh** | 1024 | 弱 | 300MB | 中文精度备选 |
| **OpenAI text-embedding-3-small** | 1536 | 好 | API 调用 | ❌ 依赖网络，有成本 |

### 2.3 LLM 提供商集成：内置 Pi SDK bridge

| 维度 | 选择 | 理由 |
|---|---|---|
| **集成方式** | `@earendil-works/pi-ai` | 由 Recall 直接复用 Pi 的多供应商模型与认证抽象 |
| **用途** | 文档自动打标签 + CLI 回答生成 |
| **认证** | 供应商环境变量、Recall 静态 API key、ChatGPT Plus/Pro OAuth | 不读取 Pi 全局认证 |
| **调用方式** | Python 启动包内 Node bridge，以 JSON stdin/stdout 通信 | 保留 Python 的 Qwen3/Chroma 核心，同时不依赖外部 Pi CLI |

**Pi SDK 的核心价值：**

```
不用 Pi SDK：Recall 需要自行维护各模型供应商 SDK、认证和请求差异

使用 Pi SDK：Recall 拥有模型配置边界，内部 bridge 统一调用供应商
```

### 2.4 技术栈总览

```
┌─────────────────────────────────────────────┐
│              应用层                          │
│  Python Recall CLI (文档 CRUD + 检索)        │
├─────────────────────────────────────────────┤
│              Pi 集成层                       │
│  ├── 内置 Pi SDK bridge: 文档标注与回答     │
│  └── TypeScript Extension: RAG 检索工具     │
├─────────────────────────────────────────────┤
│              存储层                          │
│  Chroma (向量数据库)                        │
│  ├── HNSW 索引 (快速检索)                   │
│  └── SQLite 持久化 (本地文件)               │
├─────────────────────────────────────────────┤
│              嵌入层                          │
│  Sentence-Transformer + Qwen3-Embedding     │
│  (文字 → 归一化 1024 维向量)                │
└─────────────────────────────────────────────┘
```

---

## 三、核心流程

### 3.1 文档入库流程

```
原始文档 (PDF/TXT/MD)
    ↓
① 读取内容
    ↓
② 分块 (内置文本分块器，500字/块，50字重叠)
    ↓
③ Pi 调 LLM 打标签 (category, tags, summary)
    ↓
④ Sentence-Transformer 向量化 (1024维)
    ↓
⑤ 存入 Chroma (向量 + 文本 + metadata)
```

### 3.2 检索流程

```
用户提问
    ↓
① 同款嵌入模型向量化
    ↓
② Chroma HNSW 索引搜索 top_k
    ↓
③ 返回文档片段 + 相似度分数
    ↓
④ 构造带来源 Prompt → LLM 生成回答
```

---

## 四、关键依赖

| 依赖 | 版本 | 用途 |
|---|---|---|
| chromadb | >=1.5.9,<2 | 向量数据库 |
| sentence-transformers | >=5.6.1,<6 | 嵌入模型框架 |
| numpy | >=1.24 | 向量运算 |
| pypdf | >=6.14.2,<7 | PDF 文本提取 |
| @earendil-works/pi-ai | 0.82.1 | 多供应商模型调用与 OAuth |
| proper-lockfile | 4.1.2 | OAuth credential 跨进程刷新锁 |
| cmd2 | >=4.1.2,<5 | OAuth 供应商登录选择向导 |

---

## 五、项目结构规划

```
recall/
├── src/recall/              # Python CLI、每 store daemon、核心实现与 bridge 构建产物
├── runtime/
│   └── model-bridge.ts      # Pi SDK bridge 源码
├── agent/extensions/
│   └── rag-search.ts        # Pi 检索 Extension
├── tests/                   # CLI、bridge 与 Chroma 验证
├── docs/plans/              # 已确认的 API 设计
├── pyproject.toml           # Python 包与 recall 命令
├── package.json             # Extension 开发配置
└── README.md
```

---

## 六、选型总结

| 组件 | 选型 | 理由 |
|---|---|---|
| **本地运行时** | 每 store Unix socket daemon | 复用 Chroma/HNSW/Qwen3，store 间隔离 |
| **向量数据库** | Chroma | 轻量、持久化、CRUD 完整 |
| **嵌入模型** | Qwen3-Embedding-0.6B | 多语言、跨语言、1024 维 |
| **嵌入框架** | Sentence-Transformer | 开箱即用，自动 Pooling |
| **LLM 调度** | 内置 Pi SDK bridge | Recall 自有配置边界，统一多厂商 API |
| **打标签** | Pi + GPT-4o-mini | 成本低，精度够 |
| **回答生成** | Pi + Claude/GPT | 按需选择 |
