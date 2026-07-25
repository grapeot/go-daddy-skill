from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from go_daddy_skill.plan import build_txt_create_plan, validate_txt_create_plan


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
