# 按关注点整理本地 Git 提交

Status (2026-07-29 10:58): Completed

## Scope

- 包含：当前仓库全部未跟踪源码、测试、配置、扩展与文档。
- 不包含：被 `.gitignore` 排除的依赖、构建产物、缓存、本地数据库和用户配置。

## Target

- [x] T1：全部本地变更按项目脚手架、配置、模型运行时、RAG 核心、daemon、CLI、Pi 扩展和文档等独立关注点分别提交。
- [x] T2：每个提交使用清晰的 conventional-style message，且 staged 内容只属于该提交主题。
- [x] T3：最终工作树无未提交变更，提交历史可清楚反映逻辑边界。

## Plan

1. 盘点 Git 状态、文件职责和依赖关系，确定提交顺序。
2. 每组逐项暂存，检查 staged diff 后提交。
3. 核对提交历史和最终工作树状态。

## Result

- T1：形成 10 个提交，分别覆盖脚手架、原子配置、模型运行时与认证、setup 向导、RAG 核心、daemon、CLI、Pi 扩展、文档和本任务记录。
- T2：每组提交前均检查 `git diff --cached --name-status`、`--stat` 和主题相关 diff；提交消息全部采用 `chore:`、`feat(scope):` 或 `docs:` conventional-style 格式。
- T3：`git log --oneline --reverse` 显示清晰的依赖顺序；最终 `git status --short` 无输出。
- Review gate: Skipped — 用户要求整理提交，没有请求独立审查。
