from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AuditLog:
    id: str
    actor_type: str
    actor_id: str
    action_type: str
    target_type: str
    target_id: str
    payload_hash: str
    created_at: str
