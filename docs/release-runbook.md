# Release Runbook

Status: A12-1 Static Host Deployment Provider.

## Boundary

A12-0 defines the release record, provider contract, direct deploy API, read API, and explicit failure states.

A12-1 adds the first real provider, `static_host`. It publishes already-persisted Artifact Store bytes into a configured local static deployment directory and serves them from the AgentHub API process. It does not build, call cloud providers, read cloud credentials, or write deployment output into the workspace.

Allowed API surface:

- `POST /api/artifacts/{id}/deploy`
- `GET /api/deployments/{id}`

Release fields:

- `id`
- `artifact_id`
- `artifact_version_id`
- `provider`
- `status`: `created`, `publishing`, `published`, or `failed`
- `url`: nullable
- `error_code`: nullable
- `created_at`
- `published_at`: nullable

## Failure Codes

- `deployment_artifact_unsupported`: the source artifact type is not deployable in this phase.
- `deployment_provider_not_configured`: no real deployment provider is configured for the request.
- `deployment_artifact_checksum_mismatch`: Artifact Store bytes did not match the source `ArtifactVersion` checksum during publish.
- `deployment_publish_failed`: the configured provider could not write or serve the static deployment bytes.
- `deployment_credentials_missing`: reserved for configured providers with missing credentials.
- `deployment_provider_failed`: reserved for future provider failures that are not otherwise classified.

## Static Host Configuration

`static_host` is selected by posting:

```json
{"provider":"static_host"}
```

Required:

- `AGENTHUB_STATIC_DEPLOY_DIR`: writable directory outside the workspace where published static files are copied.

Optional:

- `AGENTHUB_PUBLIC_BASE_URL`: public base URL used for returned deployment URLs.
- `HOST` and `PORT`: used to form `http://{HOST}:{PORT}` when `AGENTHUB_PUBLIC_BASE_URL` is not set. `0.0.0.0` and `::` are returned as `127.0.0.1`.

Static files are served from:

```text
GET /static-deployments/{release_id}/...
```

For single-file web artifacts, HTML and extensionless web artifacts publish as `index.html`. The returned URL points to the real published file, for example:

```text
{base_url}/static-deployments/{release_id}/index.html
```

## Release Artifact

Successful `static_host` publish behavior:

- `DeploymentRelease.status = published`
- `url` is the real static serving URL.
- `published_at` is non-null.
- A `deployment_release` artifact is created with status `available`.
- The release artifact JSON records `provider`, `url`, `status`, `error_code`, the release envelope, `source_artifact`, and `source_version` (`id`, `version`, `checksum`).

Failure behavior:

- `DeploymentRelease.status = failed`
- `url = null`
- `published_at = null`
- A `deployment_release` artifact is created with status `failed`.

## Rules

- Do not return fake or placeholder deployment URLs.
- Do not treat preview URLs as published URLs.
- Do not fallback to a fake provider.
- Do not run shell builds.
- Do not write deployment output into the workspace.
- Do not read provider credentials.
- Do not call Vercel, Cloudflare, or another cloud provider.
- Do not mark a release as `published` unless a real provider returns a real URL.
- Do not create a `published` release without a `deployment_release` artifact.
