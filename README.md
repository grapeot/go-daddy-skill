# GoDaddy Skill

An independent, read-first CLI and agent skill for listing domains visible to a GoDaddy account, reading domain details, enumerating DNS records from GoDaddy-hosted authoritative zones, and creating supported DNS records through a guarded, dry-run-first plan/apply workflow.

This project is not affiliated with or endorsed by GoDaddy. GoDaddy is a trademark of its respective owner.

## Why This Exists

Registrar ownership and authoritative DNS are different control planes. A domain can appear in a GoDaddy account while its live DNS is hosted by Cloudflare or another provider. This tool keeps those facts separate and never treats unavailable external-zone data as an empty or clean zone.

The general client is structurally read-only. The only mutation surface is creation of an allowlisted DNS record type through a separate credential and transport. Registration, renewal, transfer, nameserver, contact, record replacement/update, and delete operations remain out of scope.

## Install

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

Generate a GoDaddy Personal Access Token with only the `domains.domain:read` scope, then inject it at runtime:

```bash
export GODADDY_PAT=replace-with-your-read-only-token
```

Do not pass the token as a command-line argument or commit it to a file.

Execution additionally requires a separate token with `domains.domain:read` and `domains.dns:update`:

```bash
export GODADDY_WRITE_PAT=replace-with-your-separate-dns-write-token
```

Do not reuse a broader account-management credential.

## CLI

```bash
go-daddy-skill auth status
go-daddy-skill auth status --live
go-daddy-skill domains list
go-daddy-skill domains list --page-size 100 --max-items 250
go-daddy-skill domains get example.com
go-daddy-skill dns list example.com
go-daddy-skill dns list example.com --type CNAME
go-daddy-skill dns create plan example.com \
  --type A \
  --name app \
  --data 192.0.2.10 \
  --ttl 600 \
  --output plans/example-create.json
go-daddy-skill dns create apply plans/example-create.json \
  --confirm-domain example.com
go-daddy-skill dns create apply plans/example-create.json \
  --confirm-domain example.com \
  --confirm-record '{"data":"192.0.2.10","name":"app","ttl":600,"type":"A"}' \
  --execute
```

Every successful command prints one JSON value to stdout. Errors are JSON on stderr and preserve the redacted provider response, HTTP status, selected diagnostic headers, and request path.

Plans expire after 30 minutes and contain the requested record in plaintext. Keep them in the ignored `plans/` directory or another protected local path. Plan and apply are dry-run by default. Dry-run output explicitly requires user authorization for the exact record; non-TXT execution also requires its exact `required_confirm_record`. Only `apply --execute` writes. Execution rechecks the digest, domain confirmation, live DNS authority, and duplicate state, sends one non-retried `POST`, then verifies the returned opaque `recordId` through the read endpoint. If the result is uncertain, inspect live state instead of retrying.

## Safety Model

- Read credentials come only from `GODADDY_PAT`; writes use only `GODADDY_WRITE_PAT`.
- The public CLI is pinned to `https://api.godaddy.com`.
- The general transport accepts only three approved `GET` path families.
- The write transport accepts only `A`, `AAAA`, `CAA`, `CNAME`, `MX`, `NS`, `SRV`, and `TXT` creation on one approved v3 path and never retries a POST.
- Redirects are rejected, preventing credentials from crossing origins.
- Contact fields and transfer auth codes are never requested and are recursively redacted if returned unexpectedly.
- List commands fetch every page unless the caller explicitly sets `--max-items`.
- GoDaddy DNS records are meaningful only when GoDaddy serves the authoritative zone.
- Planning and applying both fail unless account nameservers exactly match live DNS nameservers.
- Applying requires the operator to repeat the plan's domain with `--confirm-domain`.
- Only `--execute` writes; non-TXT records require exact `--confirm-record` confirmation.

## Agent Installation

Give an AI coding agent this repository URL and ask it to install the project and register `skills/godaddy.md` in the target workspace's skill discovery chain. The agent should first inspect the workspace's `AGENTS.md` or `CLAUDE.md`, then update an existing skill index when one exists. Only the root skill should be globally registered.

## Documentation

- [`skills/godaddy.md`](skills/godaddy.md): canonical agent skill
- [`docs/prd.md`](docs/prd.md): product scope and success criteria
- [`docs/rfc.md`](docs/rfc.md): architecture and design decisions
- [`docs/test.md`](docs/test.md): verification strategy
- [`docs/working.md`](docs/working.md): changelog and lessons learned

## Upstream References

- [GoDaddy authentication](https://developer.godaddy.com/en/docs/api-users/auth)
- [Domains REST overview](https://developer.godaddy.com/en/docs/references/rest/domains)
- [Domains v1 OpenAPI](https://developer.godaddy.com/openapi/domains-v1.json)
- [Domains v3 OpenAPI](https://developer.godaddy.com/openapi/domains-v3.json)
