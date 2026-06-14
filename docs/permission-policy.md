# Permission Policy

Status: A10-2 / A10-3 Review Gate + Apply Patch Hardening.

Acceptance IDs: A10.

## Scope

A10 implements the minimum durable permission gate for applying patch or diff artifacts to an existing artifact version. It does not deploy, publish previews, write to the workspace, or enable agent adapter write tools.

## Review Gate

High-risk action:

- `apply_patch`

Required records:

- `ReviewRequest`
- `ReviewDecision`
- `PatchApplication`
- `AuditLog`

Rules:

- The first `POST /api/artifacts/{id}/apply-patch` for a patch or diff artifact returns `review_required`.
- That first request creates a pending `ReviewRequest` and writes an audit log with `action_type = review_request.created`.
- A pending request may be decided once through `POST /api/review-requests/{id}/decision`.
- `approved` and `rejected` decisions both write audit logs.
- A rejected request cannot create an `ArtifactVersion`.
- An approved request may apply only if the target current version still equals the approved base version.

## Patch Application Outcomes

| Outcome | Error Code | Version Created |
| --- | --- | --- |
| `review_required` | `review_required` | no |
| `rejected` | `review_rejected` | no |
| `applied` | null | yes |
| `failed` | `artifact_apply_stale_base` | no |
| `failed` | `artifact_apply_checksum_mismatch` | no |
| `conflict` | `artifact_apply_conflict` | no |

Every `PatchApplication` outcome writes an audit log with `action_type = patch_application.{status}`.

## Idempotency

An approved review request is single-result for the same patch/diff artifact, target artifact, and base version. After a successful apply, repeated calls return the existing `PatchApplication(applied)` and `result_version_id` with no second `ArtifactVersion`.

## Consistency

The applied path writes the new `ArtifactVersion`, updates the artifact current version, inserts `PatchApplication(applied)`, and writes the audit log in one SQLite transaction. If the patch application or audit insert fails, the database rolls back the version/current-version update.

## Explicit Non-Goals

A10 does not:

- write to the workspace
- call deployment or preview publish paths
- enable Codex `workspace-write`
- enable Codex `danger-full-access`
- enable Claude Edit, Write, Bash, or MCP write tools
- apply a patch without an approved review decision
- fake an applied result
- hardcode patch output
