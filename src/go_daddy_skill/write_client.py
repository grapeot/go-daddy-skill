from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

import requests

from .client import PRODUCTION_ORIGIN, GoDaddyAPIError, normalize_domain, redact
from .plan import build_dns_create_plan


class GoDaddyDNSWriteClient:
    """Narrow non-retrying client for one DNS create operation."""

    def __init__(
        self,
        token: str,
        *,
        session: requests.Session | None = None,
        timeout: float = 30.0,
    ) -> None:
        token = token.strip()
        if not token or any(character.isspace() for character in token) or ":" in token:
            raise ValueError("GODADDY_WRITE_PAT is missing or malformed")
        self._token = token
        self._session = session or requests.Session()
        self._timeout = timeout

    def create_record(self, zone: str, record: dict[str, Any]) -> dict[str, Any]:
        normalized = normalize_domain(zone)
        validated = build_dns_create_plan(
            normalized,
            record,
            existing_records=[],
        )["record"]
        path = f"/v3/domains/zones/{quote(normalized, safe='.-')}/dns-records"
        request_id = str(uuid.uuid4())
        response = self._session.post(
            PRODUCTION_ORIGIN + path,
            json=validated,
            headers={
                "Accept": "application/json",
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "User-Agent": "go-daddy-skill/0.2.0",
                "X-Request-Id": request_id,
            },
            timeout=self._timeout,
            allow_redirects=False,
        )
        headers = {
            key.lower(): value
            for key, value in response.headers.items()
            if key.lower()
            in {
                "location",
                "x-request-id",
                "ratelimit-limit",
                "ratelimit-remaining",
                "ratelimit-reset",
            }
        }
        try:
            body = redact(response.json())
        except ValueError:
            body = {
                "body_text": "[NON_JSON_BODY_REDACTED]",
                "body_length": len(response.text),
                "content_type": response.headers.get("content-type"),
            }
        if response.status_code != 201 or not isinstance(body, dict):
            raise GoDaddyAPIError(
                response.status_code,
                path,
                body,
                headers,
                request_id,
                method="POST",
            )
        return {"record": body, "headers": headers, "request_id": request_id}

    def create_txt_record(self, zone: str, record: dict[str, Any]) -> dict[str, Any]:
        if record.get("type") != "TXT":
            raise ValueError("create_txt_record accepts TXT records only")
        return self.create_record(zone, record)
