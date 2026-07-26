from __future__ import annotations

import hashlib
import ipaddress
import json
import uuid
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from typing import Any

from .client import normalize_domain

PLAN_SCHEMA = "go-daddy-skill/dns-create-plan-v2"
SUPPORTED_RECORD_TYPES = frozenset({"A", "AAAA", "CAA", "CNAME", "MX", "NS", "SRV", "TXT"})


def _digest(plan: dict[str, Any]) -> str:
    payload = deepcopy(plan)
    payload.pop("digest", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "sha256:" + hashlib.sha256(canonical.encode()).hexdigest()


def _validate_name(name: Any, zone: str) -> str:
    if not isinstance(name, str):
        raise ValueError("DNS record name must be a string")
    name = name.strip()
    labels = name.split(".")
    valid = name == "@" or (
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
    if not valid:
        raise ValueError("DNS record name is invalid or is not relative to the zone")
    return name


def _validate_record(record: Any, zone: str) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise ValueError("DNS record must be a JSON object")
    record_type = str(record.get("type", "")).upper()
    if record_type not in SUPPORTED_RECORD_TYPES:
        raise ValueError(
            f"Unsupported DNS record type; expected one of {sorted(SUPPORTED_RECORD_TYPES)}"
        )
    allowed = {"type", "name", "data", "ttl"}
    if record_type == "MX":
        allowed.add("priority")
    elif record_type == "SRV":
        allowed.update({"priority", "weight", "port", "service", "protocol"})
    if set(record) - allowed:
        raise ValueError(f"DNS {record_type} record contains unsupported fields")

    name = _validate_name(record.get("name"), zone)
    data = record.get("data")
    ttl = record.get("ttl")
    if not isinstance(data, str) or not 1 <= len(data) <= 1024:
        raise ValueError("DNS record data must contain between 1 and 1024 characters")
    data = data.strip()
    if not data:
        raise ValueError("DNS record data must not be blank")
    if not isinstance(ttl, int) or isinstance(ttl, bool):
        raise ValueError("TTL must be an integer")
    if not 600 <= ttl <= 86400:
        raise ValueError("TTL must be between 600 and 86400 seconds")
    if record_type == "A":
        try:
            if ipaddress.ip_address(data).version != 4:
                raise ValueError
        except ValueError as exc:
            raise ValueError("A record data must be a valid IPv4 address") from exc
    elif record_type == "AAAA":
        try:
            if ipaddress.ip_address(data).version != 6:
                raise ValueError
        except ValueError as exc:
            raise ValueError("AAAA record data must be a valid IPv6 address") from exc
    elif record_type == "TXT" and len(data) > 512:
        raise ValueError("TXT data must contain between 1 and 512 characters")

    validated: dict[str, Any] = {
        "type": record_type,
        "name": name,
        "data": data,
        "ttl": ttl,
    }
    numeric_fields = {
        "MX": ("priority",),
        "SRV": ("priority", "weight", "port"),
    }.get(record_type, ())
    for field in numeric_fields:
        value = record.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= 65535:
            raise ValueError(f"DNS {record_type} record requires integer {field} in 0..65535")
        validated[field] = value
    if record_type == "SRV":
        for field in ("service", "protocol"):
            value = record.get(field)
            if (
                not isinstance(value, str)
                or not value.startswith("_")
                or len(value) < 2
                or len(value) > 63
            ):
                raise ValueError(f"DNS SRV record requires {field} such as _sip or _tcp")
            validated[field] = value
    return validated


def record_confirmation(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def records_are_identical(existing: dict[str, Any], target: dict[str, Any]) -> bool:
    for key, target_value in target.items():
        if key == "ttl":
            continue
        existing_value = existing.get(key)
        if key in {"type", "name"}:
            if str(existing_value).lower() != str(target_value).lower():
                return False
        elif existing_value != target_value:
            return False
    return True


def build_dns_create_plan(
    zone: str,
    record: dict[str, Any],
    *,
    existing_records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    zone = normalize_domain(zone)
    record = _validate_record(record, zone)
    exact = [
        existing
        for existing in existing_records
        if records_are_identical(existing, record)
    ]
    if exact:
        raise ValueError("An identical DNS record already exists")

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
        "record": record,
        "preconditions": {
            "account_and_live_nameservers_match": True,
            "identical_record_count": 0,
        },
        "authorization": {
            "explicit_user_authorization_required": True,
            "non_txt_double_check_required": record["type"] != "TXT",
            "required_confirm_record": (
                record_confirmation(record) if record["type"] != "TXT" else None
            ),
            "instruction": (
                "Dry run only. Show this exact record to the user and obtain explicit "
                "authorization before rerunning apply with --execute. For non-TXT records, "
                "also pass the exact required_confirm_record value."
            ),
        },
    }
    plan["digest"] = _digest(plan)
    return plan


def validate_dns_create_plan(
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
    record = _validate_record(plan.get("record"), zone)
    authorization = plan.get("authorization")
    if not isinstance(authorization, dict):
        raise ValueError("DNS plan is missing authorization instructions")
    expected_confirmation = record_confirmation(record) if record["type"] != "TXT" else None
    if authorization.get("explicit_user_authorization_required") is not True:
        raise ValueError("DNS plan does not require explicit user authorization")
    if authorization.get("required_confirm_record") != expected_confirmation:
        raise ValueError("DNS plan confirmation value does not match its record")
    return plan


def build_txt_create_plan(
    zone: str,
    name: str,
    data: str,
    ttl: int,
    *,
    existing_records: list[dict[str, Any]],
    now: datetime | None = None,
) -> dict[str, Any]:
    return build_dns_create_plan(
        zone,
        {"type": "TXT", "name": name, "data": data, "ttl": ttl},
        existing_records=existing_records,
        now=now,
    )


def validate_txt_create_plan(
    plan: Any,
    *,
    confirm_domain: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    validated = validate_dns_create_plan(plan, confirm_domain=confirm_domain, now=now)
    if validated["record"]["type"] != "TXT":
        raise ValueError("DNS plan does not contain a TXT record")
    return validated
