# GoDaddy Skill

## Project Role

This repository provides an independent, read-first CLI and agent skill for inventorying domains visible to a GoDaddy account, reading GoDaddy-hosted DNS zones, and performing one guarded TXT-record create operation.

It is not an official GoDaddy product, a registrar automation tool, or an arbitrary API proxy. The only mutation path is an explicit, expiring plan/apply workflow for TXT creation.

## Structure

- `src/go_daddy_skill/` contains the reusable client and CLI.
- `skills/godaddy.md` is the canonical root skill.
- `docs/prd.md`, `docs/rfc.md`, `docs/test.md`, and `docs/working.md` are project memory.
- `tests/` contains offline tests. Live API tests must remain opt-in.
- `scripts/run_cli.sh` is the stable local entrypoint.

## Environment

Use the project-local uv environment for all Python operations:

```bash
uv venv .venv
source .venv/bin/activate
uv pip install -e '.[dev]'
```

## Non-Negotiable Boundaries

- Keep the general client structurally read-only. Its transport may issue only approved `GET` requests.
- Keep DNS writes in the separate narrow transport. It may issue one non-retried `POST` only to the approved v3 DNS-record path.
- Read credentials only from `GODADDY_PAT` and `GODADDY_WRITE_PAT`; never accept tokens as CLI arguments.
- Require a digest-checked, 30-minute plan, exact domain confirmation, matching account/live nameservers, conflict revalidation, and record-ID verification for every write.
- Support TXT creation only. Do not add update, delete, nameserver, purchase, transfer, contact, or arbitrary API operations.
- Never request, print, cache, or fixture WHOIS contacts or domain transfer auth codes.
- Keep the production origin pinned to `https://api.godaddy.com` in the public CLI.
- Preserve provider HTTP status, request identifiers, rate-limit headers, and redacted response bodies in errors.
- Use only synthetic domains, credentials, account data, and paths in tracked files.
- Do not commit `.env`, live API output, domain inventories, logs, or credentials.
- Update `docs/working.md` after behavior, interface, test, or safety-boundary changes.
- Do not commit or push unless the user explicitly requests it.

## Verification

Run offline checks before reporting completion:

```bash
.venv/bin/ruff check .
.venv/bin/pytest -q
```

Live read tests require an explicit gate and a read-only PAT. Live writes require separate case-specific user authorization and a separate write PAT. Publication readiness also requires a privacy scan for real domains, credentials, email addresses, internal paths, and private secret-manager references.
