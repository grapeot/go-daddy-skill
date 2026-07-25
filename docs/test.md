# Test Strategy

## Default Offline Suite

The default suite uses fake HTTP sessions and synthetic `example.com` data. It must not require credentials or internet access.

Required coverage:

- Credential presence and malformed legacy-value rejection.
- Method/path allowlist enforcement before transport.
- Redirect rejection.
- V1 domain marker pagination, truncation, repeated-marker detection, and empty accounts.
- V3 DNS page pagination and truncation.
- Recursive redaction in success and error bodies.
- Stable success and error envelopes.
- Exit-code mapping for authentication, authorization, provider, and protocol failures.
- Plan digest, expiration, domain confirmation, TXT validation, and duplicate rejection.
- One-shot POST behavior, fixed origin, redirect rejection, and required `recordId`.

Run:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
```

## Opt-In Live Tests

Production reads are allowed only when all required variables are present:

```text
GODADDY_ENABLE_LIVE_TESTS=1
GODADDY_PAT=<token with only domains.domain:read>
GODADDY_LIVE_TEST_DOMAIN=example.com
```

Live tests may only call the same approved GET paths. They must not print domain names, DNS records, or response fixtures into CI logs. They should assert structural properties and skip when the selected domain uses external authoritative DNS.

## Live Mutation Boundary

The default and opt-in pytest suites never mutate DNS. A live TXT create is a case-specific CLI acceptance test requiring a separately scoped `GODADDY_WRITE_PAT`, explicit user authorization for the named zone and record, an expiring plan, and manual cleanup. Never place a production domain or returned record in fixtures or logs.

## Publication Privacy Check

Before publication, scan tracked files for:

- Real domains and email addresses.
- Real API tokens or token-shaped strings.
- Private 1Password references.
- Internal absolute paths and server names.
- Live domain inventories and DNS dumps.

Expected examples must use reserved domains and fake credentials.
