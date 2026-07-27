from __future__ import annotations

import json

import pytest

from go_daddy_skill import cli
from go_daddy_skill.client import GoDaddyProtocolError
from go_daddy_skill.plan import build_dns_create_plan, record_confirmation


def test_auth_status_without_token_is_json_error(monkeypatch, capsys):
    monkeypatch.delenv("GODADDY_PAT", raising=False)

    assert cli.main(["auth", "status"]) == 3

    error = json.loads(capsys.readouterr().err)
    assert error["ok"] is False
    assert error["error"]["kind"] == "authentication"
    assert "GODADDY_PAT" in error["error"]["message"]


def test_auth_status_does_not_print_token(monkeypatch, capsys):
    monkeypatch.setenv("GODADDY_PAT", "top-secret-token")

    assert cli.main(["auth", "status"]) == 0

    output = capsys.readouterr().out
    assert "top-secret-token" not in output
    body = json.loads(output)
    assert body["data"] == {"present": True, "source": "environment", "live": False}


def test_execute_requires_write_token_not_read_token(monkeypatch, capsys):
    monkeypatch.setenv("GODADDY_PAT", "read-token")
    monkeypatch.delenv("GODADDY_WRITE_PAT", raising=False)

    assert (
        cli.main(
            [
                "dns",
                "create",
                "apply",
                "plans/synthetic.json",
                "--confirm-domain",
                "example.com",
                "--execute",
            ]
        )
        == 3
    )

    error = json.loads(capsys.readouterr().err)
    assert error["command"] == "dns.create.apply"
    assert error["error"]["kind"] == "authentication"
    assert "GODADDY_WRITE_PAT" in error["error"]["message"]


def test_apply_without_execute_uses_read_token(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("GODADDY_PAT", "read-token")
    monkeypatch.delenv("GODADDY_WRITE_PAT", raising=False)
    plan_path = tmp_path / "missing.json"

    assert (
        cli.main(
            [
                "dns",
                "create",
                "apply",
                str(plan_path),
                "--confirm-domain",
                "example.com",
            ]
        )
        == 2
    )

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["kind"] == "input"
    assert "Unable to read DNS plan" in error["error"]["message"]


class _FakeApplyClient:
    def __init__(self, token):
        self.token = token

    def get_domain(self, domain):
        return {"nameServers": ["ns1.example.net", "ns2.example.net"]}

    def list_dns_records(self, domain, *, record_type, name):
        return [], {"complete": True}


def _write_a_plan(tmp_path):
    plan = build_dns_create_plan(
        "example.com",
        {"type": "A", "name": "app", "data": "192.0.2.10", "ttl": 600},
        existing_records=[],
    )
    path = tmp_path / "a-create.json"
    path.write_text(json.dumps(plan), encoding="utf-8")
    return path, plan


def test_post_write_reconciliation_accepts_unique_exact_readback_without_response_id():
    target = {"type": "CNAME", "name": "app", "data": "target.example.net.", "ttl": 600}
    verified = {**target, "recordId": "readback-id"}

    assert cli._verified_created_record({"record": {}}, [verified], target) == verified


def test_post_write_reconciliation_rejects_ambiguous_exact_readback():
    target = {"type": "CNAME", "name": "app", "data": "target.example.net.", "ttl": 600}
    records = [
        {**target, "recordId": "first-id"},
        {**target, "recordId": "second-id"},
    ]

    with pytest.raises(GoDaddyProtocolError, match="not unique"):
        cli._verified_created_record({"record": {}}, records, target)


def test_apply_is_zero_write_dry_run_by_default(monkeypatch, tmp_path, capsys):
    plan_path, plan = _write_a_plan(tmp_path)
    monkeypatch.setenv("GODADDY_PAT", "read-token")
    monkeypatch.delenv("GODADDY_WRITE_PAT", raising=False)
    monkeypatch.setattr(cli, "GoDaddyClient", _FakeApplyClient)
    monkeypatch.setattr(cli, "resolve_nameservers", lambda domain: ["ns1.example.net"])
    monkeypatch.setattr(cli, "require_matching_authority", lambda account, live: None)

    class ForbiddenWriter:
        def __init__(self, token):
            raise AssertionError("dry-run must not construct the write client")

    monkeypatch.setattr(cli, "GoDaddyDNSWriteClient", ForbiddenWriter)

    assert (
        cli.main(
            [
                "dns",
                "create",
                "apply",
                str(plan_path),
                "--confirm-domain",
                "example.com",
            ]
        )
        == 0
    )

    output = json.loads(capsys.readouterr().out)
    assert output["data"]["dry_run"] is True
    assert output["data"]["ready_to_execute"] is True
    assert output["data"]["would_create"] == plan["record"]
    assert "explicit user authorization" in output["data"]["instruction"]


def test_non_txt_execute_requires_exact_record_confirmation(monkeypatch, tmp_path, capsys):
    plan_path, plan = _write_a_plan(tmp_path)
    monkeypatch.setenv("GODADDY_PAT", "read-token")
    monkeypatch.setenv("GODADDY_WRITE_PAT", "write-token")
    monkeypatch.setattr(cli, "GoDaddyClient", _FakeApplyClient)

    assert (
        cli.main(
            [
                "dns",
                "create",
                "apply",
                str(plan_path),
                "--confirm-domain",
                "example.com",
                "--confirm-record",
                record_confirmation({**plan["record"], "data": "192.0.2.11"}),
                "--execute",
            ]
        )
        == 2
    )

    error = json.loads(capsys.readouterr().err)
    assert error["error"]["kind"] == "input"
    assert "required_confirm_record" in error["error"]["message"]
