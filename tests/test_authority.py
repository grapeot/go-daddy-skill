from __future__ import annotations

import pytest

from go_daddy_skill.authority import (
    AuthorityError,
    canonical_nameservers,
    require_matching_authority,
)


def test_nameservers_are_canonicalized_as_a_set():
    assert canonical_nameservers(["NS2.EXAMPLE.NET.", "ns1.example.net"]) == [
        "ns1.example.net",
        "ns2.example.net",
    ]


def test_matching_authority_accepts_order_difference():
    require_matching_authority(
        ["ns1.example.net", "ns2.example.net"],
        ["NS2.EXAMPLE.NET.", "ns1.example.net."],
    )


def test_authority_drift_fails_closed():
    with pytest.raises(AuthorityError, match="do not match"):
        require_matching_authority(
            ["ns1.example.net", "ns2.example.net"],
            ["ns1.example.org", "ns2.example.org"],
        )
