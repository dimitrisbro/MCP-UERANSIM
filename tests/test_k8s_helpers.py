"""Unit tests for small helpers in ueransim_mcp.k8s_tools."""

import pytest

from ueransim_mcp.k8s_tools import _pod_type


@pytest.mark.parametrize("name,expected", [
    ("gnb-abcd", "gnb"),
    ("gnb-", "gnb"),
    ("ue-1234", "ue"),
    ("ue-", "ue"),
    ("gnb", "unknown"),
    ("ue", "unknown"),
    ("GNB-abcd", "unknown"),
    ("my-gnb-abcd", "unknown"),
    ("uex-1", "unknown"),
    ("", "unknown"),
])
def test_pod_type(name, expected):
    assert _pod_type(name) == expected
