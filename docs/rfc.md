# Technical Design

## Decision Summary

The general client is a handwritten, GET-only transport over three GoDaddy endpoint families. A separate transport exposes exactly one non-retried, allowlisted DNS create POST. The project does not generate a broad SDK, wrap the beta official CLI, or expose arbitrary HTTP paths. This keeps the callable surface smaller than either credential's possible permissions.

## Upstream Contract

| Capability | Endpoint | Pagination |
|---|---|---|
| Account domain inventory | `GET /v1/domains` | `limit` plus last-domain `marker` |
| Domain detail | `GET /v3/domains/domain-names/{domain-name}` | none |
| GoDaddy zone records | `GET /v3/domains/zones/{zone}/dns-records` | `page`, `pageSize`, and links |
| Create one DNS record | `POST /v3/domains/zones/{zone}/dns-records` | none; success is `201` with `recordId` |

Reads require `domains.domain:read`. Execute uses a separate PAT with `domains.domain:read` and `domains.dns:update`. V3 requires PAT authentication. Legacy `sso-key` credentials are intentionally unsupported.

Exact schemas come from the official [v1 OpenAPI](https://developer.godaddy.com/openapi/domains-v1.json) and [v3 OpenAPI](https://developer.godaddy.com/openapi/domains-v3.json). Behavioral constraints come from the official [authentication](https://developer.godaddy.com/en/docs/api-users/auth), [pagination](https://developer.godaddy.com/en/docs/api-users/pagination), and [domain-management](https://developer.godaddy.com/en/docs/api-users/domain-management-concepts) guides.

## Trust Boundaries

### Credentials

The CLI reads `GODADDY_PAT` for normal reads and `GODADDY_WRITE_PAT` for apply-time reads and the single write. It has no token flag, interactive login, credential file, or secret-manager-specific code. The surrounding shell or runtime owns secret injection.

### Network

The public CLI always targets `https://api.godaddy.com`. Redirects are not followed. General requests pass through a GET path allowlist. The independent write transport has no generic request method and constructs only `POST /v3/domains/zones/{normalized-zone}/dns-records` with a validated, allowlisted create body.

Tests inject a fake session into the library. No public `--base-url` option exists because forwarding a Bearer token to a caller-selected origin would create a credential-exfiltration primitive.

### Data minimization

Domain contacts and `authCode` are not requested. A case-insensitive recursive redactor removes these containers if GoDaddy returns them unexpectedly in a success or error body. Raw byte-for-byte output is intentionally absent from V1.

## Registrar Versus DNS Authority

An account-visible domain proves only that GoDaddy exposes a registrar-management record to the authenticated account. It does not prove that GoDaddy serves live DNS.

The CLI therefore provides primitive reads and preserves nameservers, but does not label an externally delegated zone as empty. Callers must inspect authoritative nameservers before interpreting `dns list`. TXT plan and apply resolve live NS records and require their canonical set to exactly equal the account domain detail. DNS failure, missing account nameservers, or drift fails closed.

## DNS Plan, Dry-run Apply, And Execute

`dns create plan` reads domain detail and the matching type/name slice, checks authority and duplicate state, then writes a canonical JSON plan. The plan contains a UUID, action, zone, record body, preconditions, authorization instructions, creation time, 30-minute expiration, and a SHA-256 digest over every field except the digest itself. The digest catches accidental or manual changes; it is not a signature against an attacker who can modify local code and files. Plan files contain record data in plaintext and belong in the ignored `plans/` directory.

`dns create apply` defaults to dry-run and uses the read token. It validates the plan digest, expiration, allowlisted record shape, and exact `--confirm-domain`, then repeats domain-detail, live-authority, complete record-list, and identical-record checks. Only `apply --execute` uses `GODADDY_WRITE_PAT` and sends one POST after those gates. Every dry-run tells the agent to obtain exact user authorization; non-TXT execute additionally checks the canonical record JSON supplied through `--confirm-record`. The client does not retry because record creation is non-idempotent.

GoDaddy must return `201` and a string `recordId`. Apply performs a fresh filtered read and succeeds only when that opaque ID appears. If the POST outcome or verification is uncertain, the command reports failure and the operator must inspect current state; automatic resubmission is forbidden.

## Pagination

### Domains v1

Requests are sequential. The next marker is the last domain in the current page. The walk ends when the page is shorter than the requested limit. Repeated markers and duplicate page identities fail as protocol errors rather than looping forever.

An explicit `--max-items` cap is deliberate truncation. The response remains successful but reports `complete: false`, `truncated: true`, and the safe continuation marker.

### DNS v3

Requests are sequential with one-based pages. The walk follows the existence of a same-contract next relation, but reconstructs the next request locally instead of following an arbitrary URL with credentials. A short page or missing next relation ends the walk.

## Output Contract

Success:

```json
{
  "schema": "go-daddy-skill/v1",
  "ok": true,
  "command": "domains.list",
  "data": {"domains": []},
  "meta": {"complete": true, "truncated": false, "requests": 1}
}
```

Errors preserve the operation, path, status, selected headers, and recursively redacted body. Human-readable messages supplement rather than replace provider evidence.

## Error Policy

- Missing or malformed local credentials: exit 3.
- Provider `401`: exit 3.
- Provider `403`: exit 4.
- Network and other provider HTTP failures: exit 5.
- Upstream schema or pagination invariant failures: exit 7.
- CLI usage errors: exit 2.

The client records `X-Request-Id`, `RateLimit-Limit`, `RateLimit-Remaining`, `RateLimit-Reset`, and `Retry-After` when present. It does not hardcode a published quota because current official pages disagree and runtime headers are more authoritative.

## Why Not the Official CLI

GoDaddy publishes beta domain CLI and agent-skill material, but the documented command names and repository branches are still changing, and the tool includes write and purchase workflows. REST plus versioned OpenAPI is the smaller and more stable V1 dependency.

## Future Decisions

### Aggregate inventory

Add live NS resolution, explicit authoritative-provider classification, and per-zone coverage. External providers must report `external_provider_required`, never `clean`.

### Dangling CNAME audit

Add bounded CNAME traversal, loop detection, A/AAAA terminal checks, and authoritative NXDOMAIN confirmation. Findings must say that claimability was not tested. Provider-specific takeover checks require separately maintained evidence and legal review.

### Additional writes

Deletes, updates, replacements, SOA creation, arbitrary record types, nameserver changes, purchases, transfers, and contacts remain outside this increment. Adding any of them requires a new threat analysis rather than generalizing the create transport.
