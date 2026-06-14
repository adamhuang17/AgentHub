# AI Collaboration Log

## 协作原则

本项目使用 AI 辅助开发，但不允许 AI 输出未经验证的成功状态。

## 当前阶段

阶段：方案 A 统一产品入口封装。

目标：在不破坏 OpenCode workspace 的前提下，新增 `AgentHub-Lite/` 作为比赛项目统一入口。

## 重要决策

1. 废弃旧 AgentHub Web。
2. OpenCode `packages/app` 作为前端基座。
3. 旧 AgentHub `services/api` 作为 Control Plane。
4. 先封装统一入口，不做完整源码搬迁。
5. 保留 no fake success 工程纪律。

## 给 Codex 的后续任务原则

每次 Codex 完成后必须报告：

- 修改文件列表。
- 运行命令。
- 测试结果。
- 手动验收步骤。
- 未完成项。
- 是否存在 fake success / hardcode / mock。
