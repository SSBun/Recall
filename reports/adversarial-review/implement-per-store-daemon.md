---
created: 2026-07-28
task: implement-per-store-daemon
review_cycles: 2
---

# 每 Store 独立 Recall Daemon 对抗审查

Topic: Store 隔离、单实例与进程生命周期

> **E1:** 以规范化 store 路径哈希定位 Unix socket、锁、PID 和日志；`fcntl` 保证每 store 单实例，daemon 串行复用一个 `RecallApp`，请求完成后空闲 30 分钟退出，并提供自动启动及 status/stop。
>
> **R1:** 初审确认并发启动、失效 socket、store PID/socket 隔离、权限、空闲退出和 wheel 运行均有证据；记录同用户客户端连接后不发送可阻塞串行 handler，以及启动失败固定等待 10 秒的非阻塞 NOTE。
>
> **E2:** 确认真实 CLI 在 connect 后立即发送，socket/root 权限为 `0600`/`0700`，前者仅是同用户本地加固项；确认短生命周期 CLI、`setsid`、PID 元数据和日志路径使启动/回收行为充分，因此不扩大当前范围。
>
> **R2:** 复审验证 NOTE 均已闭环，重跑单实例、隔离、停止、权限、idle 和构建测试后返回 `APPROVED`。

**Conclusion:** 每 store daemon 的进程隔离、串行状态边界、自动生命周期和故障恢复满足当前本地个人知识库要求。

Topic: CLI 协议、环境兼容与凭据安全

> **E1:** RAG 命令通过版本化 JSON Unix socket 请求复用现有本地 CLI 分发；只在 connect 失败且尚未发送请求时启动并重试。每次请求转发调用方环境，daemon 串行临时应用并在 `finally` 恢复；provider 命令不经过 daemon。
>
> **R1:** 初审确认 human/JSON、错误和部分失败 envelope 保持兼容；完整环境可能包含 API key，但只经过同用户 `0600` socket，不写入 PID、日志或其他持久文件，因此仅记录非阻塞 NOTE。
>
> **E2:** 确认环境映射经过字符串校验、请求期间内存应用、异常路径恢复，串行模型排除进程内环境竞争；保留该实现以维持模型、并发及 provider 环境变量语义。
>
> **R2:** 复审验证错误重建、`PARTIAL_FAILURE` 解包、argparse 错误和 provider 前台边界均正确，无新增 finding。

**Conclusion:** daemon transport 保持现有 CLI 语义，且环境与凭据没有跨越本地用户权限边界或被持久化。

---

**Final decision:** `APPROVED`

**Outcome:** 每 Store 独立 Recall daemon 通过两轮独立对抗审查。

**Remaining:** none
