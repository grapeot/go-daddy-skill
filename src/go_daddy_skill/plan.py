from __future__ import annotations

import hashlib
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from .client import normalize_domain

PLAN_SCHEMA = "go-daddy-skill/dns-create-plan-v1"
def _digest(plan: dict[str, Any]) -> str:
    payload = deepcopy(plan)
    payload.pop("digest", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def build_txt_create_plan(
    zone: str,
    name: str,
    data: str,
    ttl: int,
    *,
    existing_records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    zone = normalize_domain(zone)
    if not isinstance(name, str) or not isinstance(data, str):
        raise ValueError("TXT name and data must be strings")
    if not isinstance(ttl, int) or isinstance(ttl, bool):
        raise ValueError("TTL must be an integer")
    name = name.strip()
    labels = name.split(".")
    name_is_valid = name == "@" or (
        len(name) <= 253
        and not name.lower().endswith(f".{zone}")
        and all(
            1 <= len(label) <= 63
            and not label.startswith("-")
            and not label.endswith("-")
            and all(
                character.isascii() and (character.isalnum() or character in "_-")
                for character in label
            )
            for label in labels
        )
    )
    if not name_is_valid:
        raise ValueError("TXT record name is invalid or is not relative to the zone")
    if not 1 <= len(data) <= 512:
        raise ValueError("TXT data must contain between 1 and 512 characters")
    if not 600 <= ttl <= 86400:
        raise ValueError("TTL must be between 600 and 86400 seconds")
    exact = [
        record
        for record in existing_records
        if str(record.get("type", "")).upper() == "TXT"
        and str(record.get("name", "")).lower() == name.lower()
        and record.get("data") == data
    ]
    if exact:
        raise ValueError("An identical TXT record already exists")

    created_at = now or datetime.now(UTC)
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    plan: dict[str, Any] = {
        "schema": PLAN_SCHEMA,
        "action": "dns.create",
        "plan_id": str(uuid.uuid4()),
        "created_at": created_at.isoformat().replace("+00:00", "Z"),
        "expires_at": (created_at + timedelta(minutes=30)).isoformat().replace("+00:00", "Z"),
        "zone": zone,
        "record": {"type": "TXT", "name": name, "data": data, "ttl": ttl},
        "preconditions": {
            "account_and_live_nameservers_match": True,
            "identical_record_count": 0,
        },
    }
    plan["digest"] = _digest(plan)
    return plan


def validate_txt_create_plan(
    plan: Any,
    *,
    confirm_domain: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    if not isinstance(plan, dict):
        raise ValueError("DNS plan must be a JSON object")
    if plan.get("schema") != PLAN_SCHEMA or plan.get("action") != "dns.create":
        raise ValueError("Unsupported DNS plan schema or action")
    if plan.get("digest") != _digest(plan):
        raise ValueError("DNS plan digest does not match its contents")
    zone = normalize_domain(str(plan.get("zone", "")))
    if normalize_domain(confirm_domain) != zone:
        raise ValueError("--confirm-domain does not match the plan zone")
    try:
        expires_at = datetime.fromisoformat(str(plan["expires_at"]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as exc:
        raise ValueError("DNS plan has an invalid expiration") from exc
    if expires_at.tzinfo is None:
        raise ValueError("DNS plan expiration must include a timezone")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    if current > expires_at:
        raise ValueError("DNS plan has expired")
    record = plan.get("record")
    if not isinstance(record, dict) or record.get("type") != "TXT":
        raise ValueError("DNS plan does not contain a TXT record")
    if not isinstance(record.get("name"), str) or not isinstance(record.get("data"), str):
        raise ValueError("DNS plan has an invalid TXT name or data value")
    if not isinstance(record.get("ttl"), int) or isinstance(record.get("ttl"), bool):
        raise ValueError("DNS plan has an invalid TTL")
    build_txt_create_plan(
        zone,
        record["name"],
        record["data"],
        record["ttl"],
        existing_records=[],
        now=current,
    )
    return plan
