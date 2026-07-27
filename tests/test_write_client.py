from __future__ import annotations

import pytest
from test_client import FakeResponse, FakeSession

from go_daddy_skill.client import GoDaddyAPIError
from go_daddy_skill.write_client import GoDaddyDNSWriteClient


def test_create_txt_is_one_non_retrying_pinned_post():
    session = FakeSession(
        [
            FakeResponse(
                201,
                {
                    "recordId": "synthetic-record-id",
                    "type": "TXT",
                    "name": "_agent-test",
                    "data": "verification=synthetic",
                    "ttl": 600,
                },
                {"Location": "https://api.godaddy.com/v3/domains/zones/example.com/dns-records/id"},
            )
        ]
    )
    client = GoDaddyDNSWriteClient("write-token", session=session)

    result = client.create_txt_record(
        "example.com",
        {
            "type": "TXT",
            "name": "_agent-test",
            "data": "verification=synthetic",
            "ttl": 600,
        },
    )

    assert result["record"]["recordId"] == "synthetic-record-id"
    assert len(session.calls) == 1
    assert session.calls[0]["url"].startswith("https://api.godaddy.com/")
    assert session.calls[0]["allow_redirects"] is False


def test_create_a_is_one_non_retrying_pinned_post():
    session = FakeSession(
        [
            FakeResponse(
                201,
                {
                    "recordId": "synthetic-a-record-id",
                    "type": "A",
                    "name": "www",
                    "data": "192.0.2.1",
                    "ttl": 600,
                },
            )
        ]
    )
    client = GoDaddyDNSWriteClient("write-token", session=session)

    result = client.create_record(
        "example.com",
        {"type": "A", "name": "www", "data": "192.0.2.1", "ttl": 600},
    )

    assert result["record"]["recordId"] == "synthetic-a-record-id"
    assert session.calls[0]["json"]["type"] == "A"
    assert len(session.calls) == 1


def test_create_accepts_201_without_record_id_for_readback_reconciliation():
    session = FakeSession([FakeResponse(201, {})])
    client = GoDaddyDNSWriteClient("write-token", session=session)

    result = client.create_record(
        "example.com",
        {"type": "CNAME", "name": "app", "data": "target.example.net.", "ttl": 600},
    )

    assert result["record"] == {}
    assert len(session.calls) == 1


def test_write_client_rejects_extra_body_fields():
    client = GoDaddyDNSWriteClient("write-token", session=FakeSession([]))

    with pytest.raises(ValueError, match="unsupported fields"):
        client.create_txt_record(
            "example.com",
            {
                "type": "TXT",
                "name": "_agent-test",
                "data": "verification=synthetic",
                "ttl": 600,
                "unexpected": "field",
            },
        )


def test_provider_failure_is_not_retried_and_reports_post():
    session = FakeSession([FakeResponse(503, {"code": "UNAVAILABLE"})])
    client = GoDaddyDNSWriteClient("write-token", session=session)

    with pytest.raises(GoDaddyAPIError) as caught:
        client.create_txt_record(
            "example.com",
            {
                "type": "TXT",
                "name": "_agent-test",
                "data": "verification=synthetic",
                "ttl": 600,
            },
        )

    assert caught.value.method == "POST"
    assert len(session.calls) == 1


def test_txt_compatibility_method_rejects_non_txt():
    client = GoDaddyDNSWriteClient("write-token", session=FakeSession([]))

    with pytest.raises(ValueError, match="TXT"):
        client.create_txt_record(
            "example.com",
            {"type": "A", "name": "www", "data": "192.0.2.1", "ttl": 600},
        )
