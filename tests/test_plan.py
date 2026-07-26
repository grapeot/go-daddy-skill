from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from go_daddy_skill.plan import (
    build_dns_create_plan,
    build_txt_create_plan,
    record_confirmation,
    validate_dns_create_plan,
    validate_txt_create_plan,
)


def test_plan_round_trip_and_digest():
    now = datetime(2026, 7, 25, tzinfo=UTC)
    plan = build_txt_create_plan(
        "example.com",
        "_agent-test",
        "verification=synthetic",
        600,
        existing_records=[],
        now=now,
    )

    assert validate_txt_create_plan(
        plan,
        confirm_domain="example.com",
        now=now + timedelta(minutes=1),
    ) == plan


def test_tampered_plan_is_rejected():
    plan = build_txt_create_plan(
        "example.com",
        "_agent-test",
        "verification=synthetic",
        600,
        existing_records=[],
    )
    tampered = deepcopy(plan)
    tampered["record"]["data"] = "changed"

    with pytest.raises(ValueError, match="digest"):
        validate_txt_create_plan(tampered, confirm_domain="example.com")


def test_expired_plan_is_rejected():
    now = datetime(2026, 7, 25, tzinfo=UTC)
    plan = build_txt_create_plan(
        "example.com",
        "_agent-test",
        "verification=synthetic",
        600,
        existing_records=[],
        now=now,
    )

    with pytest.raises(ValueError, match="expired"):
        validate_txt_create_plan(
            plan,
            confirm_domain="example.com",
            now=now + timedelta(hours=1),
        )


def test_identical_record_blocks_plan():
    with pytest.raises(ValueError, match="identical"):
        build_txt_create_plan(
            "example.com",
            "_agent-test",
            "verification=synthetic",
            600,
            existing_records=[
                {
                    "type": "TXT",
                    "name": "_agent-test",
                    "data": "verification=synthetic",
                }
            ],
        )


def test_non_object_plan_is_rejected():
    with pytest.raises(ValueError, match="JSON object"):
        validate_txt_create_plan([], confirm_domain="example.com")


def test_a_plan_requires_exact_non_txt_confirmation():
    now = datetime(2026, 7, 25, tzinfo=UTC)
    record = {"type": "A", "name": "app", "data": "192.0.2.10", "ttl": 600}
    plan = build_dns_create_plan(
        "example.com",
        record,
        existing_records=[],
        now=now,
    )

    assert plan["record"] == record
    assert plan["authorization"]["explicit_user_authorization_required"] is True
    assert plan["authorization"]["non_txt_double_check_required"] is True
    assert plan["authorization"]["required_confirm_record"] == record_confirmation(record)
    assert validate_dns_create_plan(
        plan,
        confirm_domain="example.com",
        now=now + timedelta(minutes=1),
    ) == plan


@pytest.mark.parametrize(
    ("record", "message"),
    [
        ({"type": "A", "name": "app", "data": "not-an-ip", "ttl": 600}, "IPv4"),
        ({"type": "AAAA", "name": "app", "data": "192.0.2.1", "ttl": 600}, "IPv6"),
        ({"type": "SOA", "name": "@", "data": "unsafe", "ttl": 600}, "Unsupported"),
    ],
)
def test_record_specific_validation(record, message):
    with pytest.raises(ValueError, match=message):
        build_dns_create_plan("example.com", record, existing_records=[])


def test_mx_priority_is_part_of_identity():
    plan = build_dns_create_plan(
        "example.com",
        {
            "type": "MX",
            "name": "@",
            "data": "mail.example.net",
            "ttl": 600,
            "priority": 20,
        },
        existing_records=[
            {
                "type": "MX",
                "name": "@",
                "data": "mail.example.net",
                "ttl": 600,
                "priority": 10,
            }
        ],
    )

    assert plan["record"]["priority"] == 20
