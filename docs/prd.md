# Product Requirements

## Product Statement

Provide humans and AI agents with a least-privilege, machine-readable view of domains visible to a GoDaddy account and DNS records hosted by GoDaddy, plus a tightly guarded, dry-run-first DNS-record creation workflow, without exposing private registration data or broad registrar mutations.

## Users

- Domain owners who need a complete registrar inventory.
- Operators auditing expiration, auto-renew, lock, privacy, nameserver, and DNS state.
- AI agents that need stable JSON rather than dashboard automation.
- Security reviewers investigating stale records without changing production DNS.

## Read Requirements

V1 must:

- Authenticate with a scoped Personal Access Token from `GODADDY_PAT`.
- List every account-visible domain through sequential marker pagination.
- Retrieve one domain through the privacy-minimized v3 detail endpoint.
- List every DNS record in a GoDaddy-hosted zone through v3 pagination.
- Return versioned JSON with explicit completeness metadata.
- Distinguish deliberate truncation from provider or protocol failure.
- Preserve useful upstream HTTP errors after recursive redaction.
- Prevent all non-GET and unapproved-origin requests in the general client.
- Avoid contact and transfer-auth-code expansions.
- Run all default tests without network access or credentials.

## Guarded DNS Create Requirements

The write increment must:

- Read a separate `GODADDY_WRITE_PAT` with `domains.domain:read` and `domains.dns:update`.
- Create only allowlisted `A`, `AAAA`, `CAA`, `CNAME`, `MX`, `NS`, `SRV`, and `TXT` records through `POST /v3/domains/zones/{zone}/dns-records`.
- Split every operation into a local plan and a separate apply command.
- Expire plans after 30 minutes and reject any digest mismatch.
- Require exact `--confirm-domain` input at apply time.
- Keep apply dry-run unless `--execute` is present.
- Tell the agent in every dry-run to obtain explicit user authorization for the exact record.
- Require exact `--confirm-record` confirmation for non-TXT execute.
- Confirm that account and live DNS nameserver sets match during plan and apply.
- Reject an identical record during plan and recheck immediately before apply.
- Send the non-idempotent POST exactly once without automatic retry.
- Require `201 Created`, retain the opaque `recordId`, and verify that ID through a fresh read.
- Return manual cleanup coordinates without exposing a delete command.

## Explicit Non-Goals

- Domain purchase, renewal, cancellation, transfer, or forwarding.
- DNS update, replacement, or deletion; allowlisted creation is the sole exception.
- Nameserver mutation.
- WHOIS contact access.
- Transfer auth-code access.
- Reseller and `X-Shopper-Id` workflows.
- Wrapping the beta official GoDaddy CLI.
- Claiming that an unresolved CNAME is exploitable or takeable.
- Enumerating DNS hosted by Cloudflare, Route 53, or other external providers.

## Interface

```text
go-daddy-skill auth status [--live]
go-daddy-skill domains list [--page-size N] [--start-marker DOMAIN] [--max-items N]
go-daddy-skill domains get DOMAIN
go-daddy-skill dns list DOMAIN [--type TYPE] [--name NAME] [--page-size N] [--max-items N]
go-daddy-skill dns create plan DOMAIN --type TYPE --name NAME --data DATA [TYPE_FIELDS] [--ttl N] --output PATH
go-daddy-skill dns create apply PLAN --confirm-domain DOMAIN [--confirm-record JSON] [--execute]
```

Global `--pretty` controls indentation. Compact JSON is the default.

## Success Criteria

- A synthetic account with more than one domain page returns each domain exactly once.
- A zone with more than one DNS page returns each record and reports `complete: true`.
- Explicit caps report `complete: false`, `truncated: true`, and a continuation marker or page.
- Missing credentials fail before network access and never echo token material.
- Redirects, writes, and unapproved paths fail locally.
- The general transport rejects writes and unapproved paths locally.
- Execute cannot run with only the read token, a stale or modified plan, mismatched authority, a conflicting record, a different confirmed domain, or a missing non-TXT confirmation.
- Apply without `--execute` performs zero writes.
- A successful execute performs one POST and verifies its returned `recordId`.
- Unexpected contact and auth-code fields never appear in output.
- Provider errors retain status, redacted body, request path, request ID, and rate-limit headers.

## Roadmap

The next read-only increment may add an aggregate inventory artifact that combines registrar data with live NS resolution. A later DNS-audit increment may detect CNAME loops and evidence-backed NXDOMAIN targets. It must not equate DNS failure with confirmed subdomain takeover.

Further write support—especially update, replacement, or delete—requires a separate product and safety review. It must not enter this CLI as an unlocked method or generic request command.
