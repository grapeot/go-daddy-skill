from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import idna
import requests

PRODUCTION_ORIGIN = "https://api.godaddy.com"
SCHEMA = "go-daddy-skill/v1"

_ALLOWED_PATHS = (
    re.compile(r"^/v1/domains$"),
    re.compile(r"^/v3/domains/domain-names/[a-z0-9.-]+$"),
    re.compile(r"^/v3/domains/zones/[a-z0-9.-]+/dns-records$"),
)
_DOMAIN_RE = re.compile(
    r"^(?=.{1,253}\.?$)"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.?$"
)
_SENSITIVE_KEYS = {
    "authcode",
    "contactadmin",
    "contactbilling",
    "contactregistrant",
    "contacttech",
    "contacts",
}
_DIAGNOSTIC_HEADERS = {
    "x-request-id",
    "ratelimit-limit",
    "ratelimit-remaining",
    "ratelimit-reset",
    "retry-after",
}


class GoDaddyProtocolError(RuntimeError):
    pass


@dataclass
class GoDaddyAPIError(RuntimeError):
    status_code: int
    path: str
    response_body: Any
    response_headers: dict[str, str]
    request_id: str
    method: str = "GET"

    def __str__(self) -> str:
        return f"GoDaddy API {self.status_code} at {self.path}"


def _normalized_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if _normalized_key(str(key)) in _SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def normalize_domain(domain: str) -> str:
    value = domain.strip().rstrip(".").lower()
    try:
        value = idna.encode(value, uts46=True).decode("ascii")
    except idna.IDNAError as exc:
        raise ValueError(f"Invalid domain: {domain}") from exc
    if not _DOMAIN_RE.fullmatch(value):
        raise ValueError(f"Invalid domain: {domain}")
    return value


class GoDaddyClient:
    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ) -> None:
        token = token.strip()
        if not token or any(character.isspace() for character in token) or ":" in token:
            raise ValueError("GODADDY_PAT is missing or malformed")
        self._token = token
        self._session = session or requests.Session()
        self._timeout = timeout
        self.request_count = 0

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if not any(pattern.fullmatch(path) for pattern in _ALLOWED_PATHS):
            raise GoDaddyProtocolError(f"Request path is not allowed: {path}")

        request_id = str(uuid.uuid4())
        response = self._session.get(
            PRODUCTION_ORIGIN + path,
            params=params,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "User-Agent": "go-daddy-skill/0.1.0",
                "X-Request-Id": request_id,
            },
            timeout=self._timeout,
            allow_redirects=False,
        )
        self.request_count += 1

        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower() in _DIAGNOSTIC_HEADERS
        }
        try:
            body = response.json()
        except ValueError:
            body = {
                "body_text": "[NON_JSON_BODY_REDACTED]",
                "body_length": len(response.text),
                "content_type": response.headers.get("content-type"),
            }
        body = redact(body)

        if 300 <= response.status_code < 400:
            raise GoDaddyAPIError(response.status_code, path, body, headers, request_id)
        if not response.ok:
            raise GoDaddyAPIError(response.status_code, path, body, headers, request_id)
        if not isinstance(body, (dict, list)):
            raise GoDaddyProtocolError(f"Unexpected JSON shape from {path}")
        return body

    def auth_status(self, *, live: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {"present": True, "source": "environment", "live": live}
        if live:
            body = self._request("/v1/domains", params={"limit": 1})
            if not isinstance(body, list):
                raise GoDaddyProtocolError("Expected a list from /v1/domains")
            data["authorized"] = True
        return data

    def list_domains(
        self,
        *,
        page_size: int = 1000,
        start_marker: str | None = None,
        max_items: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if not 1 <= page_size <= 1000:
            raise ValueError("page_size must be between 1 and 1000")
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be positive")

        domains: list[dict[str, Any]] = []
        marker = normalize_domain(start_marker) if start_marker else None
        seen_markers: set[str] = set()
        truncated = False

        while True:
            request_limit = page_size
            if max_items is not None:
                request_limit = min(page_size, max_items - len(domains))
            params: dict[str, Any] = {
                "limit": request_limit,
                "includes": "nameServers",
            }
            if marker:
                if marker in seen_markers:
                    raise GoDaddyProtocolError(f"Repeated domain marker: {marker}")
                seen_markers.add(marker)
                params["marker"] = marker

            body = self._request("/v1/domains", params=params)
            if not isinstance(body, list) or any(not isinstance(item, dict) for item in body):
                raise GoDaddyProtocolError("Expected an array of domain objects")

            domains.extend(redact(item) for item in body)
            if len(body) < request_limit:
                break
            if not body or not isinstance(body[-1].get("domain"), str):
                raise GoDaddyProtocolError(
                    "A full domain page did not contain a continuation domain"
                )
            next_marker = normalize_domain(body[-1]["domain"])
            if next_marker == marker:
                raise GoDaddyProtocolError(f"Repeated domain marker: {next_marker}")
            if max_items is not None and len(domains) >= max_items:
                probe = self._request(
                    "/v1/domains",
                    params={"limit": 1, "includes": "nameServers", "marker": next_marker},
                )
                if not isinstance(probe, list):
                    raise GoDaddyProtocolError("Expected an array from the continuation probe")
                truncated = bool(probe)
                marker = next_marker
                break
            marker = next_marker

        continuation = None
        if truncated and domains and isinstance(domains[-1].get("domain"), str):
            continuation = normalize_domain(domains[-1]["domain"])
        return domains, {
            "complete": not truncated,
            "truncated": truncated,
            "continuation_marker": continuation,
            "requests": self.request_count,
        }

    def get_domain(self, domain: str) -> dict[str, Any]:
        normalized = normalize_domain(domain)
        body = self._request(f"/v3/domains/domain-names/{quote(normalized, safe='.-')}")
        if not isinstance(body, dict):
            raise GoDaddyProtocolError("Expected a domain object")
        return body

    def list_dns_records(
        self,
        domain: str,
        *,
        record_type: str | None = None,
        name: str | None = None,
        page_size: int = 100,
        max_items: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        normalized = normalize_domain(domain)
        if not 1 <= page_size <= 100:
            raise ValueError("page_size must be between 1 and 100")
        if max_items is not None and max_items < 1:
            raise ValueError("max_items must be positive")

        records: list[dict[str, Any]] = []
        page = 1
        truncated = False
        seen_pages: set[int] = set()
        path = f"/v3/domains/zones/{quote(normalized, safe='.-')}/dns-records"

        while True:
            if page in seen_pages:
                raise GoDaddyProtocolError(f"Repeated DNS page: {page}")
            seen_pages.add(page)
            request_page_size = page_size
            if max_items is not None:
                request_page_size = min(page_size, max_items - len(records))
            params: dict[str, Any] = {"page": page, "pageSize": request_page_size}
            if record_type:
                params["type"] = record_type.upper()
            if name:
                params["name"] = name
            body = self._request(path, params=params)
            if not isinstance(body, dict) or not isinstance(body.get("items"), list):
                raise GoDaddyProtocolError("Expected a DNS page object with items")
            items = body["items"]
            if any(not isinstance(item, dict) for item in items):
                raise GoDaddyProtocolError("Expected DNS record objects")

            records.extend(redact(item) for item in items)

            links = body.get("links") or []
            has_next = any(
                isinstance(link, dict) and str(link.get("rel", "")).lower() == "next"
                for link in links
            )
            if max_items is not None and len(records) >= max_items:
                truncated = has_next
                break
            if not has_next:
                break
            page += 1

        return records, {
            "complete": not truncated,
            "truncated": truncated,
            "continuation_page": page + 1 if truncated else None,
            "requests": self.request_count,
        }
