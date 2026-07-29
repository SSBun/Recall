---
created: 2026-07-29
task: add-config-command
review_cycles: 4
---

# Config 命令与菜单式 Setup 向导对抗审查

Topic: 脚本化配置、默认检索数量与 daemon 边界

> **E1:** 新增 `config list/set`；`search.limit` 同时成为 search/ask 默认值，显式 `--limit` 优先。config 前台执行，不创建 RAG app 或 daemon。
>
> **R1:** 初审验证 CLI、人类/JSON 输出、英文 help、daemon 每请求重读配置、模型优先级和 wheel 分发，未发现 blocker；确认 cmd2 是既有直接依赖。
>
> **E2:** 保持当前命令面，不扩大 `--json` 解析范围；完整回归和提取 wheel smoke 通过。
>
> **R2:** 复审确认配置即时生效、config 不启动 daemon，返回 `APPROVED`。

**Conclusion:** `config list/set` 和 `search.limit` 行为满足脚本化及运行时要求。

Topic: TOML 原子更新与用户文件保真

> **E1:** 使用 stdlib 定点更新三个支持键，写入前解析验证，再通过同目录临时文件和 `replace` 原子提交。
>
> **R1:** 初审记录两个 NOTE：symlink 会使 link/target 静默分叉；在下一 section 前插入缺失键会移动空行分隔。
>
> **E2:** 写入时解析 symlink target，在 target 目录原子替换并保留 symlink；缺失键改为插入尾部空行之前，新增回归测试。
>
> **R2:** 复审验证跨目录 symlink、缺失父目录、多个空行、array-of-tables 邻接和重复键，所有 NOTE 关闭。

**Conclusion:** 配置更新不会静默破坏 symlink、覆盖无关 TOML 内容或留下部分写入。

Topic: 用户纠正——菜单式交互而非命令 Shell

> **E1:** 初版将纯 `recall config` 实现成 `recall-config> list/set` 受限命令 shell。
>
> **R1:** 虽然安全边界通过技术审查，用户明确拒绝该交互，要求匹配 setup 风格的 `●/○` 单选菜单。
>
> **E2:** 删除 `config_shell.py`，新增 `config_prompt.py`：首屏显示 Recall setup、三个设置当前值和 Exit；TTY 使用 cmd2 的方向键选择器，非 TTY 使用 `●/○` 编号 fallback；编辑后返回刷新菜单，不进入 cmdloop，也不接受 shell 命令。
>
> **R2:** 纠正初审确认行为匹配示例，但报告一个 blocker：工作区上下文仍被判定引用旧 shell 文件；同时记录无害 pyc 残留。
>
> **E3:** 直接核对并确保上下文只引用 `config_prompt.py`，清理旧 pyc 和任务中的 shell 措辞；`rg` 与 wheel 均无 `config_shell` 残留。
>
> **R3:** 纠正复审确认菜单视觉、当前值刷新、TTY selector 路径、非菜单输入拒绝、EOF/Ctrl-C、脚本化兼容和打包边界，返回 `APPROVED`。

**Conclusion:** 纯 `recall config` 现在是用户要求的 setup 选择向导，不是命令 shell。

---

**Final decision:** `APPROVED`

**Outcome:** Config 命令、默认检索数量、TOML 安全和纠正后的菜单式 setup 向导通过四轮独立对抗审查。

**Remaining:** none
