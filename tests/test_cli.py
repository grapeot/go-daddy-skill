from __future__ import annotations

import json

from go_daddy_skill import cli


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


def test_apply_requires_write_token_not_read_token(monkeypatch, capsys):
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
            ]
        )
        == 3
    )

    error = json.loads(capsys.readouterr().err)
    assert error["command"] == "dns.create.apply"
    assert error["error"]["kind"] == "authentication"
    assert "GODADDY_WRITE_PAT" in error["error"]["message"]
