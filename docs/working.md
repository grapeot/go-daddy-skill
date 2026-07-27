# Working Notes

## Changelog

### 2026-07-25

- Created the public-ready project scaffold and canonical root skill.
- Documented the PAT-only, read-only V1 boundary and the v1/v3 API split.
- Added a minimal GET-only client for domain inventory, domain detail, and DNS records.
- Added stable JSON envelopes, pagination completeness metadata, and recursive sensitive-field redaction.
- Added offline tests for transport boundaries, pagination, truncation, redaction, and provider errors.
- Removed configurable API origins from the public library surface so Bearer credentials remain pinned to GoDaddy.
- Corrected DNS pagination to honor the provider next relation even when a page is shorter than its requested maximum.
- Added modern IDNA encoding, resumable page-boundary truncation, and fail-closed handling for non-JSON error bodies.
- Verified 15 offline tests, Ruff, Python bytecode compilation, CLI JSON output, and public-repository privacy scans.
- Added guarded TXT creation with separate read/write credentials, an expiring digest-checked plan, exact domain confirmation, authority and conflict rechecks, a non-retried POST, and record-ID verification.
- Added live NS resolution as a mandatory write precondition and kept delete/update operations outside the CLI.
- Expanded the offline suite to 28 tests and updated the public product, safety, and agent contracts.
- Completed an explicitly authorized production TXT acceptance test: plan and apply preconditions passed, GoDaddy returned and read-back verified the opaque record ID, and both authoritative nameservers served the expected value. The record was intentionally left for manual cleanup; no production identifiers are stored in tracked files.
- Generalized the create-only safety boundary to an explicit DNS type allowlist. Plan and apply remain dry-run by default; only `--execute` writes, and non-TXT records require exact canonical record confirmation after explicit user authorization.
- Added credential-free GitHub Actions CI for Ruff, offline tests, and bytecode compilation.

### 2026-07-27

- Accepted GoDaddy DNS create responses that return HTTP 201 without a `recordId`, as observed in production for a CNAME create.
- Preserved fail-closed, non-retrying semantics by requiring the post-write inventory to contain exactly one record matching every planned field, then using its opaque `recordId` as the verified result.
- Expanded the offline suite to 40 passing tests; Ruff and bytecode compilation also pass.

## Lessons Learned

- GoDaddy API versions are capability namespaces, not replacements: owned-domain listing remains in v1 while the preferred domain-detail and DNS-record reads are in v3.
- Registrar custody does not imply DNS authority. GoDaddy zone data must not be treated as live when nameservers delegate elsewhere.
- Current official pages disagree about fixed rate limits and some error shapes. Preserve runtime headers and provider bodies instead of hardcoding prose claims.
- The official CLI surface is still changing. The public REST/OpenAPI contract is the narrower dependency for this project.
- A provider page size is a maximum, not a guaranteed row count. Pagination must follow the API continuation signal rather than assuming a short page is terminal.
- Raw non-JSON provider text cannot be safely key-redacted. V1 reports its type and length but suppresses the body.
- A DNS create POST is non-idempotent. Unknown outcomes require state inspection, never an automatic retry.
- Successful create response shapes are not consistent across record types. The authoritative readback, not the POST body alone, is the final verification source.
- A digest embedded in a plan catches accidental edits but is not a signature against a hostile local actor; local plan storage remains inside the trusted boundary.
