# 实现每 Store 独立的 Recall Daemon

Status (2026-07-28 16:43): Completed

## Scope

- 包含：RAG 命令按规范化 store 路径自动连接或启动本地 daemon、每 store 单实例、Unix socket、串行处理、空闲 30 分钟退出，以及 `daemon status/stop`。
- 不包含：TCP/HTTP 服务、远程访问、Windows transport、通用交互式 shell、公开 idle-timeout 配置、provider 命令代理或多 store 共用进程。

## Target

- [x] T1：首次 RAG 命令为目标 store 自动启动唯一 daemon；同一 store 复用进程，不同 store 使用不同 PID/socket。
- [x] T2：daemon 生命周期内只创建一个 `RecallApp`，串行处理请求并在完成请求后空闲 30 分钟自动退出。
- [x] T3：`recall daemon status/stop --store X` 可观察和终止目标 daemon；provider 命令不启动 daemon。
- [x] T4：daemon 复用现有 CLI 业务分发和版本化 envelope，人类输出、`--json`、错误码及部分失败语义保持兼容。
- [x] T5：自动化测试和实际 subprocess smoke 覆盖单实例、store 隔离、复用、停止、空闲退出、失效 socket 恢复、权限及 wheel 分发。

## Plan

1. 建立只依赖标准库的 store runtime 定位、Unix socket client/server 和单实例锁。
2. 将 RAG 命令透明路由到 daemon，同时把 provider 与 daemon 管理命令留在前台 CLI。
3. 用可注入短 idle timeout 和临时 runtime/store 完成单元及真实进程验证，再同步 README 与工作区上下文。

## Result

- T1：RAG 命令按规范化 store SHA-256 标识连接 `~/.local/state/recall/daemons/` 下的 Unix socket；`fcntl` 锁和并发启动测试证明同 store 只有一个运行实例，两个临时 store 获得不同 PID/socket。
- T2：daemon 在 bind 前创建且全生命周期复用一个 `RecallApp`，同步 `UnixStreamServer` 串行执行；单元测试证明多次命令只创建一次 app，并以 0.2 秒注入值验证请求完成后的 idle 退出，生产常量为 30 分钟。
- T3：新增 `daemon status/stop` 人类及 JSON 输出，stop 幂等；provider 测试以 fail-fast fake 证明不会创建 daemon。
- T4：server 通过现有 `run(..., use_daemon=False)` 产生机器 envelope，client 重建成功、错误与 `PARTIAL_FAILURE`；请求仅在 connect 前失败时自动启动，发送后不重放，并通过 `0600` socket 临时转发/恢复当前环境变量。
- T5：41 个 Python 测试、7 个 Node 测试、Ruff、TypeScript、`uv lock --check`、`npm audit`（0 漏洞）、`uv build`、真实 BGE/Chroma 多 store subprocess 及提取 wheel 自动启动/status/stop smoke 全部通过；runtime root/socket 权限为 `0700`/`0600`，失效 socket 可恢复。README、技术选型和工作区上下文已同步。
- Review gate: Required — 涉及长期进程、store 写入隔离、重试语义和环境凭据传输；Decision: `APPROVED` — 两轮后无未解决 finding，[对抗审查报告](../../reports/adversarial-review/implement-per-store-daemon.md)。
