---
name: godaddy-domain-management
description: Read-first GoDaddy domain inventory, authoritative DNS retrieval, and guarded dry-run-first DNS record creation through a least-privilege CLI. Use for owned-domain lists, expiration and protection review, nameserver inspection, DNS inventory, or an explicitly authorized DNS create. Do not use for purchases, transfers, nameserver changes, updates, replacements, or deletes.
---

# GoDaddy Domain Management

## Goal

Produce a complete or explicitly incomplete machine-readable inventory of domains visible to a GoDaddy account and records from GoDaddy-hosted authoritative DNS zones. When the user explicitly authorizes a named change, create one supported DNS record through a reviewable plan/apply boundary.

## Boundaries

- General inventory operations are structurally read-only.
- Read credentials must come from `GODADDY_PAT`, never arguments or prompts. This PAT should contain only `domains.domain:read`.
- Apply credentials must come from a separate `GODADDY_WRITE_PAT` with `domains.domain:read` and `domains.dns:update`.
- Never execute a plan without explicit user authorization for the exact zone, type, name, data, TTL, and type-specific fields.
- Create is the only mutation. Supported types are `A`, `AAAA`, `CAA`, `CNAME`, `MX`, `NS`, `SRV`, and `TXT`; `SOA` is deliberately excluded.
- Both plan and apply default to dry-run. Only `apply --execute` may write.
- For every non-TXT record, show the dry-run output to the user, ask for explicit authorization, and copy the exact `required_confirm_record` into `--confirm-record`.
- Do not use this skill for update, replace, delete, nameserver, purchase, transfer, contact, or generic API operations.
- Do not request or expose contacts or transfer auth codes.
- A domain registered at GoDaddy may use another authoritative DNS provider. In that case, GoDaddy cannot supply a trustworthy live-zone inventory.
- A broken CNAME target is not, by itself, proof that a third party can claim the hostname.

## Project

```text
adhoc_jobs/go_daddy_skill/
```

Install with a project-local uv environment:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## CLI Contract

```bash
.venv/bin/go-daddy-skill auth status
.venv/bin/go-daddy-skill auth status --live
.venv/bin/go-daddy-skill domains list
.venv/bin/go-daddy-skill domains get example.com
.venv/bin/go-daddy-skill dns list example.com
.venv/bin/go-daddy-skill dns list example.com --type CNAME
.venv/bin/go-daddy-skill dns create plan example.com \
  --type A --name app --data 192.0.2.10 --ttl 600 \
  --output plans/example-create.json
.venv/bin/go-daddy-skill dns create apply plans/example-create.json \
  --confirm-domain example.com
# After showing the dry-run and receiving exact user authorization:
.venv/bin/go-daddy-skill dns create apply plans/example-create.json \
  --confirm-domain example.com \
  --confirm-record '{"data":"192.0.2.10","name":"app","ttl":600,"type":"A"}' \
  --execute
```

All successful commands emit one JSON object on stdout. Provider and validation failures emit a JSON error on stderr with status, redacted body, path, request ID, and relevant rate-limit headers.

## Acceptance Criteria

A domain inventory is complete only when:

- `meta.complete` is `true`.
- The command did not use a limiting `--max-items` value that truncated results.
- Every v1 marker page was retrieved without a repeated marker or provider failure.
- Any interpretation of DNS records is limited to zones for which GoDaddy is authoritative.

A DNS inventory is complete only when:

- `meta.complete` is `true`.
- Every v3 record page was retrieved.
- Independent nameserver evidence confirms that GoDaddy serves the live zone.

If authority is external or unknown, report the provider gap. Never translate unavailable data into an empty-zone or clean result.

## Method Guidance

Start with `domains list` to establish account-visible scope. Inspect each domain's nameservers before calling `dns list`. Use the external provider's own API when the live nameservers are not GoDaddy's.

Treat expiration, auto-renew, lock, privacy, and nameserver fields as operational evidence rather than assumptions. Preserve the retrieval timestamp and completeness metadata in any durable report.

For a write, plan first and inspect the plan's zone, record, expiration, digest, and authorization block. Plans contain record data in plaintext and should remain in the ignored `plans/` directory. A plain apply is another dry-run and must not write. Execute only after confirming that the authorization still covers the exact operation. Non-TXT execute requires the plan's exact `required_confirm_record`. Plan and apply both require matching account/live nameservers; execute also rechecks duplicate state, sends one non-retried POST, and verifies the returned `recordId`. If the outcome is uncertain, read current state and do not rerun blindly.

## Failure Interpretation

- Exit `3`: missing, malformed, expired, or rejected credential.
- Exit `4`: authenticated but forbidden, ineligible, or missing read scope.
- Exit `5`: provider HTTP or network failure.
- Exit `7`: upstream schema or pagination invariant failure.

Do not hide the provider error body when escalating a failure, but keep the CLI's redactions intact.
