from __future__ import annotations

import pytest

from go_daddy_skill.client import GoDaddyAPIError, GoDaddyClient, GoDaddyProtocolError, redact


class FakeResponse:
    def __init__(self, status_code: int, body, headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._body = body
        self.headers = headers or {"content-type": "application/json"}
        self.text = ""
        self.ok = 200 <= status_code < 300

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses: list[FakeResponse]):
        self.responses = list(responses)
        self.calls: list[dict] = []

    def get(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)

    def post(self, url, **kwargs):
        self.calls.append({"url": url, **kwargs})
        return self.responses.pop(0)


def test_rejects_missing_and_legacy_credentials():
    with pytest.raises(ValueError):
        GoDaddyClient("")
    with pytest.raises(ValueError):
        GoDaddyClient("legacy-key:legacy-secret")


def test_redacts_sensitive_fields_recursively():
    value = {
        "domain": "example.com",
        "auth_code": "secret",
        "nested": {"ContactRegistrant": {"email": "alice@example.com"}},
    }
    assert redact(value) == {
        "domain": "example.com",
        "auth_code": "[REDACTED]",
        "nested": {"ContactRegistrant": "[REDACTED]"},
    }


def test_domain_marker_pagination_is_complete():
    session = FakeSession(
        [
            FakeResponse(200, [{"domain": "a.example"}, {"domain": "b.example"}]),
            FakeResponse(200, [{"domain": "c.example"}]),
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    domains, meta = client.list_domains(page_size=2)

    assert [item["domain"] for item in domains] == ["a.example", "b.example", "c.example"]
    assert meta == {
        "complete": True,
        "truncated": False,
        "continuation_marker": None,
        "requests": 2,
    }
    assert session.calls[1]["params"]["marker"] == "b.example"
    assert session.calls[0]["allow_redirects"] is False


def test_domain_truncation_has_continuation_marker():
    session = FakeSession(
        [
            FakeResponse(200, [{"domain": "a.example"}]),
            FakeResponse(200, [{"domain": "b.example"}]),
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    domains, meta = client.list_domains(page_size=2, max_items=1)

    assert domains == [{"domain": "a.example"}]
    assert meta["complete"] is False
    assert meta["truncated"] is True
    assert meta["continuation_marker"] == "a.example"


def test_domain_cap_equal_to_account_size_is_complete():
    session = FakeSession(
        [
            FakeResponse(200, [{"domain": "a.example"}]),
            FakeResponse(200, []),
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    domains, meta = client.list_domains(page_size=10, max_items=1)

    assert domains == [{"domain": "a.example"}]
    assert meta["complete"] is True
    assert meta["truncated"] is False


def test_dns_page_pagination_is_complete():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"items": [{"recordId": "1"}], "links": [{"rel": "next", "href": "ignored"}]},
            ),
            FakeResponse(200, {"items": [{"recordId": "2"}], "links": []}),
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    records, meta = client.list_dns_records("example.com", page_size=1)

    assert [item["recordId"] for item in records] == ["1", "2"]
    assert meta["complete"] is True
    assert session.calls[1]["params"]["page"] == 2
    assert session.calls[1]["url"].startswith("https://api.godaddy.com/")


def test_dns_short_page_with_next_link_continues():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"items": [{"recordId": "1"}], "links": [{"rel": "next"}]},
            ),
            FakeResponse(200, {"items": [{"recordId": "2"}], "links": []}),
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    records, meta = client.list_dns_records("example.com", page_size=100)

    assert [item["recordId"] for item in records] == ["1", "2"]
    assert meta["complete"] is True


def test_dns_cap_uses_page_boundary_for_continuation():
    session = FakeSession(
        [
            FakeResponse(
                200,
                {"items": [{"recordId": "1"}], "links": [{"rel": "next"}]},
            )
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    records, meta = client.list_dns_records("example.com", page_size=100, max_items=1)

    assert records == [{"recordId": "1"}]
    assert meta["complete"] is False
    assert meta["continuation_page"] == 2


def test_provider_error_keeps_redacted_body_and_headers():
    session = FakeSession(
        [
            FakeResponse(
                403,
                {"code": "ACCESS_DENIED", "authCode": "must-not-leak"},
                {"X-Request-Id": "provider-id", "RateLimit-Remaining": "2"},
            )
        ]
    )
    client = GoDaddyClient("pat-value", session=session)

    with pytest.raises(GoDaddyAPIError) as caught:
        client.auth_status(live=True)

    assert caught.value.response_body["authCode"] == "[REDACTED]"
    assert caught.value.response_headers == {
        "x-request-id": "provider-id",
        "ratelimit-remaining": "2",
    }


def test_unapproved_path_is_rejected_before_network():
    session = FakeSession([])
    client = GoDaddyClient("pat-value", session=session)

    with pytest.raises(GoDaddyProtocolError):
        client._request("/v1/domains/example.com/records")

    assert session.calls == []


def test_redirect_is_rejected():
    session = FakeSession([FakeResponse(302, {})])
    client = GoDaddyClient("pat-value", session=session)

    with pytest.raises(GoDaddyAPIError) as caught:
        client.auth_status(live=True)

    assert caught.value.status_code == 302


def test_unicode_domain_uses_modern_idna():
    session = FakeSession([FakeResponse(200, {"domain": "xn--fa-hia.de"})])
    client = GoDaddyClient("pat-value", session=session)

    client.get_domain("faß.de")

    assert session.calls[0]["url"].endswith("/domain-names/xn--fa-hia.de")


def test_non_json_error_body_is_not_echoed():
    response = FakeResponse(502, {})
    response.json = lambda: (_ for _ in ()).throw(ValueError("not json"))
    response.text = "authCode=secret-value"
    session = FakeSession([response])
    client = GoDaddyClient("pat-value", session=session)

    with pytest.raises(GoDaddyAPIError) as caught:
        client.auth_status(live=True)

    assert "secret-value" not in str(caught.value.response_body)
    assert caught.value.response_body["body_text"] == "[NON_JSON_BODY_REDACTED]"
