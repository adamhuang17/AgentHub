# Orchestrator Reference Notes

Scope: A6 structured routing notes. These notes summarize reference reading for the Orchestrator planning step and still exclude execution/runtime work.

## Files Read

1. `D:/Public Project/dify-main/api/core/workflow/workflow_entry.py`
2. `D:/Public Project/dify-main/api/core/workflow/node_runtime.py`
3. `D:/Public Project/dify-main/api/core/app/apps/workflow/app_runner.py`
4. `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/unified-coordinator.ts`
5. `D:/Public Project/ruflo-main/v3/@claude-flow/swarm/src/topology-manager.ts`
6. `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/multi-agent.ts`
7. `D:/Public Project/cline-main/sdk/packages/core/src/extensions/tools/team/spawn-agent-tool.ts`
8. `E:/obsidian/cache/ApparatusJJ/40_Projects/02-Project_Comparisons/Multi_Agent_Orchestration_Comparison.md`
9. `E:/obsidian/cache/ApparatusJJ/40_Projects/04-AI_System_Knowledge/Patterns/Queue_Based_Execution_Pattern.md`
10. `E:/obsidian/cache/ApparatusJJ/40_Projects/04-AI_System_Knowledge/Patterns/Session_Lane_Queue_Pattern.md`

## Reference Findings

| Source | Borrow | Do Not Copy | AgentHub Mapping | Why Not Directly Copy |
| --- | --- | --- | --- | --- |
| Dify `workflow_entry.py` | Clear split between workflow entry, graph engine, variable pool, runtime state, and node events. Single-node debug path is a useful mental model for narrow planning tests. | Do not copy Dify graph engine, layers, quota, tracing, child workflow engine, or free-node execution. | AgentHub A6 can keep `Task -> Plan -> PlanStep` as persisted definitions and reserve execution for later phases. | Dify is a mature workflow runtime; A6 only needs deterministic planning records, not a full graph executor. |
| Dify `node_runtime.py` | Runtime adapters are isolated behind protocols and explicit error mapping. Tool/LLM invocation is not mixed into graph entry. | Do not copy tool runtime invocation, LLM runtime, file manager, human input runtime, or provider-specific adapters. | AgentHub should keep Planner separate from Adapter execution and surface blocked/provider states explicitly. | A6 forbids Adapter invocation and AgentRun creation, so node runtime code would overreach. |
| Dify `app_runner.py` | App runner prepares inputs and runtime state before handing off to workflow entry. Resume state is separate from initial run. | Do not copy Redis command channels, workflow execution repositories, queue manager, or runner lifecycle. | AgentHub can later add task recovery without coupling it to A6 planning. | A6 creates plan records synchronously; queue/resume behavior belongs to A12 or execution phases. |
| Ruflo `unified-coordinator.ts` | Domain pools, task status transitions, queued reason, assignment records, and event emission show how to keep dispatch explainable. | Do not copy swarm coordinator, consensus, message bus, domain pools, parallel execution, or task assignment to live agents. | AgentHub A6 can use capability matching to choose an AgentProfile or mark a step blocked with a reason. | Ruflo coordinates active agents; AgentHub currently has profile-only agents and no executable adapters. |
| Ruflo `topology-manager.ts` | Agent topology and role/state indexing are useful for future multi-agent membership and health-aware routing. | Do not copy mesh/hierarchical/hybrid topology, leader election, rebalance, or path finding. | AgentHub conversation members and agent registry can later expose capability and health metadata without topology complexity. | A6 only needs a single plan with up to three steps, not a network topology. |
| Cline `multi-agent.ts` | Team state separates members, tasks, mailbox messages, runs, outcomes, mission log, and hydration. Queue/run states are explicit. | Do not copy SessionRuntime, queued run dispatch, team mailbox runtime, teammate spawning, run recovery, or outcome artifacts. | AgentHub can mirror the separation between plan records and future runs: A6 creates plan steps only, not runs. | Cline is an execution runtime; A6 is a planner precondition and must not execute agents. |
| Cline `spawn-agent-tool.ts` | Spawn tool has explicit input schema, lifecycle hooks, start/end callbacks, and propagates errors rather than hiding them. | Do not copy sub-agent creation, delegated agent config, tool approval forwarding, or run result shaping. | AgentHub can later define AdapterRunRequest schemas, but A6 must stop at dispatch metadata. | The tool creates and runs sub-agents; A6 explicitly forbids AgentRun and Adapter invoke. |
| Multi-Agent Orchestration Comparison | Useful comparison of hierarchical, role-based, workspace-lane, and gateway/session-lane approaches. | Do not import a whole framework model such as Queen-led swarm, Crew flow, or channel gateway. | AgentHub should stay IM-first: conversations create tasks, tasks create plans, plans explain dispatch. | The comparison is pattern guidance, not code or a single target architecture. |
| Queue Based Execution Pattern | Separating API trigger, persisted execution state, queue, worker, and retry clarifies later phases. | Do not add Redis/RabbitMQ/Celery/worker execution in A6. | A6 should create durable records that a future queue/executor can consume. | Queue-based execution belongs after planning, when AgentRun and execution events are allowed. |
| Session Lane Queue Pattern | Per-session serialization is useful for future transcript/workspace consistency. | Do not add session locks, leases, or run serialization in A6. | AgentHub may later serialize conversation task execution while still allowing planning records to be created deterministically. | A6 has no concurrent execution surface; adding a lane queue now would be premature. |

## Cross-Reference Summary

- Borrow the discipline of separating definition, planning, and execution.
- Borrow explicit state and reason fields for both assigned and blocked steps.
- Borrow durable records that can be resumed or inspected later.
- Do not borrow active runtimes, queues, message buses, LLM/tool invocation, topology algorithms, or sub-agent spawning.
- Do not treat AgentProfile as an executable Adapter.

## AgentHub Mapping

For A6, AgentHub should map the references into a small synchronous planning flow:

```text
message without mentions
  -> TurnRouter
  -> TurnDecision schema validation
  -> CapabilityMatcher
  -> persisted task / plan / plan_steps
```

The output remains a planned graph, not execution. Future phases may attach execution queues or AgentRun records after adapter contracts are real.
