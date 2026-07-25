from __future__ import annotations

from collections.abc import Iterable

import dns.resolver

from .client import normalize_domain


class AuthorityError(RuntimeError):
    pass


def canonical_nameservers(values: Iterable[str]) -> list[str]:
    return sorted({normalize_domain(value) for value in values})


def resolve_nameservers(zone: str) -> list[str]:
    normalized = normalize_domain(zone)
    try:
        answers = dns.resolver.resolve(normalized, "NS", lifetime=15)
    except dns.exception.DNSException as exc:
        raise AuthorityError(f"Unable to resolve live nameservers for {normalized}") from exc
    return canonical_nameservers(str(answer.target) for answer in answers)


def require_matching_authority(
    account_nameservers: Iterable[str], live_nameservers: Iterable[str]
) -> None:
    account = canonical_nameservers(account_nameservers)
    live = canonical_nameservers(live_nameservers)
    if not account:
        raise AuthorityError("GoDaddy domain detail did not include nameservers")
    if not live:
        raise AuthorityError("Live DNS did not return authoritative nameservers")
    if account != live:
        raise AuthorityError(
            "GoDaddy account nameservers do not match live DNS; refusing to plan a write"
        )
