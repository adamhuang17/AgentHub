# No Fake Success Policy

AgentHub Competition 禁止以下行为：

1. 未真实调用 Agent，却显示 Agent succeeded。
2. 未真实创建 Artifact，却显示 Artifact available。
3. 未真实生成 Diff，却显示 DiffCard。
4. 未真实复制或发布文件，却显示 Deployment published。
5. 未真实检查 CLI/API Key，却显示 Agent ready。
6. 未真实调用 Planner，却显示 Orchestrator 已理解并拆解任务。
7. 使用写死的 URL、写死的 Agent 回复、写死的产物内容冒充 Demo。
8. 捕获异常后吞掉错误并继续成功流程。
9. 找不到 Agent 时 fallback 到默认 Agent。
10. Provider 未配置时 fallback 到 mock provider。

允许 demo seed，但必须满足：

1. 文件名、变量名、UI 文案都标记 `demo_seed`。
2. `demo_seed` 不得进入真实 AgentRun 成功路径。
3. `demo_seed` 不得作为比赛演示的真实执行结果。
