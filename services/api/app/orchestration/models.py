from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MentionDispatch:
    task_id: str
    plan_id: str
    step_ids: list[str]
