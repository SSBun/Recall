# 2026-07-29 区分交互选择向导与命令 Shell

Trigger:
- 用户要求纯命令进入 interactive mode、setup、wizard 或给出单选菜单示例。
- “interactive” 既可能表示持续输入子命令，也可能表示方向键/编号选择菜单。

Rule:
- 用户给出 `●/○` 单选项、setup 菜单或逐步配置示例时，必须实现选择向导，而不是 `prompt> list/set` 命令 Shell。
- 保留脚本化子命令作为独立入口；纯命令只负责菜单式配置，不暴露通用 shell 能力。

Check:
- 复述纯命令的首屏交互形态并与用户示例逐项比对：标题、当前值、单选项、退出项。
- 用真实 TTY 或可注入 selector 验证选择、编辑、返回主菜单和退出，而不只验证管道输入。

# 2026-07-28 让所选模型与已配置 Provider 对齐

Trigger:
- 执行或交付会真实调用模型的 `index`、`retag` 或 `ask` 流程。
- 已连接的 OAuth provider 与当前默认模型的 provider 不同。

Rule:
- 执行前同时核对最终解析出的 `provider/model` 和可用认证；不得只验证“存在某个 provider 凭据”便假设默认模型可调用。
- 临时操作使用显式模型；用户期望后续命令直接工作时，把已确认的模型写入 Recall 配置，而不是依赖一次性参数。

Check:
- 输出 `resolve_model` 的 tag/ask 结果并与 `provider list` 或对应环境变量核对。
- 用用户原始命令完成一次端到端复验，确认不再出现 `Provider is not configured`。

# 2026-07-28 保持 CLI Help 语言一致

Trigger:
- 新增或修改 argparse 命令、子命令、description、help 或参数说明。
- 用户指定 CLI help 的统一语言。

Rule:
- 所有层级的 `--help` 文案必须使用英文，包括顶层描述、命令摘要和嵌套子命令摘要。
- 不得因翻译 help 改变命令名、参数、运行输出或机器错误协议。

Check:
- 枚举顶层及全部命令路径执行 `--help`，断言退出 `0` 且不含中文字符。
- 缺失命令等 argparse 错误仍附带对应英文 help。

# 2026-07-28 区分人类输出与机器 JSON

Trigger:
- 新增或修改同时支持默认输出和 `--json` 的 CLI 命令。
- 命令结果是内部字典、列表或协议对象。

Rule:
- 默认输出必须按用户任务表达语义，不得直接打印内部 JSON 结构。
- 只有显式 `--json` 才输出版本化机器 envelope，并保持 stdout 可解析。

Check:
- 人类模式测试断言可读状态或结果，且不含 JSON 字段名、花括号或敏感字段。
- `--json` 测试独立断言 envelope、稳定字段和无敏感信息。

# 2026-07-28 验证生成 bridge 的动态依赖

Trigger:
- 修改会被打包进 Python wheel 的 Node bridge 或其 SDK 依赖加载方式。
- 新增包含动态 `import()`、懒加载或运行时相对路径解析的 provider 操作。

Rule:
- 不得只测试 TypeScript 源码或不触发懒加载的相邻操作。
- 必须让生成的 `src/recall/model_bridge.mjs` 和 wheel 内 bridge 执行受影响操作直到越过动态依赖加载点。
- 独立 bundle 必须使用 SDK 支持的静态注册入口或完整包含所有运行时依赖。

Check:
- 受影响操作的生成物级回归测试在无真实账号和网络条件下证明不再出现模块解析错误。
- 构建 wheel 后从提取产物重复同一回归测试。
