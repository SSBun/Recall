# Recall CLI API 设计

## 目标与边界

Recall 是本地个人知识库 CLI。Python 进程负责文档提取、分块、BGE-small-zh 嵌入和 Chroma 持久化；Python 通过包内 Node bridge 调用 `@earendil-works/pi-ai` 完成文档自动标注与最终回答；TypeScript Pi Extension 只适配 `recall search --json`，不复制业务逻辑。

Recall 自己解析模型配置并使用专属认证文件，不依赖外部 `pi` 可执行文件、`~/.pi/agent` 或 Pi 默认模型。v1 为 ChatGPT Plus/Pro 提供 `openai-codex` OAuth 登录，并以 cmd2 提供登录选择向导，但不提供通用交互式 shell、后台 daemon、多知识库管理、远程 Chroma、自定义供应商注册、API key 登录向导或全屏 TUI。

## 命令面

| 命令 | 语义 |
|---|---|
| `recall index <path...>` | 幂等新增或更新文件；目录需配合 `--recursive` |
| `recall remove <document-id...>` | 删除文档及其全部 chunks |
| `recall list` | 列出文档级索引信息 |
| `recall show <document-id>` | 查看单个文档及 metadata |
| `recall search <query>` | 返回 Top-K 相关 chunks |
| `recall ask <question>` | 检索后通过内置 Pi SDK bridge 生成回答 |
| `recall retag <document-id...>` | 重新调用 Pi 更新文档级 metadata |
| `recall provider login [provider]` | 通过 Pi SDK 登录 OAuth 供应商；省略时交互选择，当前支持 `openai-codex` |
| `recall provider list` | 人类模式按认证供应商显示已连接/未连接；`--json` 返回 provider ID 与类型，不输出秘密 |
| `recall provider logout <provider>` | 删除 Recall 保存的供应商凭据 |

`recall provider login` 省略 provider 时显示交互式选择；`--json` 模式必须显式传入 provider，避免提示文字污染机器 stdout。显式 `recall provider login openai-codex` 保持可脚本化。

公共选项包括 `--store` 与 `--json`。`index` 支持 `--recursive`、`--document-id`、`--no-tag`、`--tag-model`、`--concurrency`；`search` 支持 `--limit`、`--tag`、`--category`；`ask` 另支持 `--model` 与 `--allow-general-knowledge`。

## 存储与身份

默认 Chroma 数据目录为 `~/.local/share/recall/db/`，`--store` 可覆盖。一个 store 只承载一个知识库；SQLite 与 HNSW 文件整体备份。

首次索引生成 `doc_<uuid4>`。路径只是可变 locator，内容 SHA-256 用于变更检测：

1. 同路径重索引沿用 ID。
2. 新路径与唯一、来源已缺失的同哈希文档匹配时视为重命名。
3. 旧来源仍存在时视为复制并生成新 ID。
4. 路径和内容同时变化时通过 `--document-id` 显式关联。

## 索引流水线

索引先完成读取、哈希、Pi 标注、分块和嵌入，再修改 Chroma。默认 Pi 按文档批量返回：

```json
{
  "documents": [
    {
      "request_id": "req_1",
      "category": "engineering",
      "tags": ["rag", "chroma"],
      "summary": "文档摘要"
    }
  ]
}
```

标注结果逐项校验。Pi 或 schema 失败只使对应文档失败，旧索引不变；批量任务继续处理其他文档并最终返回非零退出码。

`--no-tag` 跳过 Pi：新文档写入空标注，已有文档保留原标注；它与 `--tag-model` 互斥。`retag` 只更新 metadata，不重新嵌入。

`index.concurrency` 限制同时进入文本读取、解析和哈希预处理的文档数，不代表并行 Pi 进程。优先级为：

```text
--concurrency > RECALL_INDEX_CONCURRENCY > ~/.config/recall/config.toml > 4
```

Pi SDK bridge 按 token 预算批处理，BGE 批量编码，Chroma 按文档提交。bridge 使用版本化 JSON stdin/stdout 协议，每次请求接收 prompt、`provider/model` 与 Recall 认证文件路径；供应商错误在 Python 边界统一映射为 `PI_ERROR`。

## 检索与问答

索引和查询均使用 `BAAI/bge-small-zh-v1.5`、归一化向量和 cosine 距离。`search` 返回 `document_id`、`chunk_id`、当前路径、正文、distance 及文档级 metadata。

`ask` 默认把检索片段视为不可信数据，只允许基于片段回答并要求 `[1]` 形式的来源引用；证据不足时明确说明。`--allow-general-knowledge` 允许模型补充，但输出必须区分“知识库结论”和“模型补充”。

标注模型优先级为 `--tag-model` > `RECALL_TAG_MODEL` > `[models].tag` > `openai/gpt-4o-mini`；问答模型优先级为 `--model` > `RECALL_ASK_MODEL` > `[models].ask` > `openai/gpt-4o-mini`。Pi SDK 首先使用供应商标准环境变量，也可从 `~/.config/recall/auth.json` 读取静态 API key 或 OAuth credential；不读取 Pi 全局认证。

`provider login openai-codex` 通过 SDK `Models.login()` 执行浏览器或设备码流程。认证文件和父目录分别收紧为 `0600` 与 `0700`；credential store 以跨进程文件锁和原子替换保护登录、刷新与登出，completion 路径复用同一 store，因此刷新 token 会持久化。

默认人类模式的 `ask` 只输出答案；有检索来源时追加编号路径，不转储内部 JSON。BGE 初始化关闭 Hugging Face 未认证提示和权重加载进度，实际命令错误仍通过 stderr 报告。

## 机器协议

`--json` 使用版本化 envelope：

```json
{"version": 1, "ok": true, "data": {}}
```

错误使用 `error.code` 与 `error.message`。stdout 只输出结果；stderr 输出诊断。参数/配置错误退出 `2`，运行失败或批量部分失败退出 `1`。

稳定错误类别包括 `USAGE_ERROR`、`SOURCE_ERROR`、`PI_ERROR`、`TAGGING_FAILED`、`EMBEDDING_FAILED`、`STORE_ERROR`、`DOCUMENT_NOT_FOUND` 和 `PARTIAL_FAILURE`。

## 验证边界

测试 seam 是 `recall` CLI/JSON 协议、cmd2 供应商选择、Python/Node bridge 协议与临时 store。Node bridge 使用 Pi SDK 的 `fauxProvider` 和假 OAuth provider，Python 客户端使用假的内部 bridge，不依赖真实账号或网络，并覆盖：OAuth 登录/刷新持久化、凭据权限与登出、模型解析与供应商失败、重复索引 no-op、重命名与显式身份关联、标注失败不破坏旧索引、`--no-tag` 新旧语义、批量部分失败、并发优先级、严格问答/通用知识模式以及临时 Chroma 集成。
