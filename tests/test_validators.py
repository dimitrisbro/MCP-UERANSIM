"""Unit tests for ueransim_mcp.validators."""

import pytest

from ueransim_mcp.validators import (
    validate_cell_access_type, validate_container_id, validate_container_name,
    validate_hex_key, validate_ip, validate_mcc, validate_mnc, validate_nci,
    validate_op_type, validate_session_type, validate_supi,
)


@pytest.mark.parametrize("ip", ["0.0.0.0", "10.0.0.1", "192.168.188.210", "255.255.255.255"])
def test_validate_ip_valid(ip):
    assert validate_ip(ip) is True


@pytest.mark.parametrize("ip", ["", "1.2.3", "1.2.3.4.5", "256.1.1.1", "1.1.1.300", "a.b.c.d",
                                "1.2.3.-4", "1.2.3.4 ", "::1", "1234.1.1.1"])
def test_validate_ip_invalid(ip):
    with pytest.raises(ValueError):
        validate_ip(ip)


@pytest.mark.parametrize("cid", ["abc123", "0123456789abcdef", "ABCDEF", "1"])
def test_validate_container_id_valid(cid):
    assert validate_container_id(cid) is True


@pytest.mark.parametrize("cid", ["", "xyz", "abc-123", "abc 123", "gnb-1"])
def test_validate_container_id_invalid(cid):
    with pytest.raises(ValueError):
        validate_container_id(cid)


@pytest.mark.parametrize("mcc", ["001", "999", "310"])
def test_validate_mcc_valid(mcc):
    assert validate_mcc(mcc) is True


@pytest.mark.parametrize("mcc", ["", "99", "9999", "abc", "9 9", "-99"])
def test_validate_mcc_invalid(mcc):
    with pytest.raises(ValueError):
        validate_mcc(mcc)


@pytest.mark.parametrize("mnc", ["01", "70", "001", "999"])
def test_validate_mnc_valid(mnc):
    assert validate_mnc(mnc) is True


@pytest.mark.parametrize("mnc", ["", "1", "1234", "ab", "7 ", "-1"])
def test_validate_mnc_invalid(mnc):
    with pytest.raises(ValueError):
        validate_mnc(mnc)


@pytest.mark.parametrize("nci", ["0x000000010", "0x0", "0xFFFFFFFFF", "0xfffffffff", "10", "ABC"])
def test_validate_nci_valid(nci):
    assert validate_nci(nci) is True


@pytest.mark.parametrize("nci", ["", "0x1000000000", "0xGGG", "xyz", "-0x1"])
def test_validate_nci_invalid(nci):
    with pytest.raises(ValueError):
        validate_nci(nci)


@pytest.mark.parametrize("cat", ["nr", "nr-leo", "nr-meo", "nr-geo", "nr-othersat"])
def test_validate_cell_access_type_valid(cat):
    assert validate_cell_access_type(cat) is True


@pytest.mark.parametrize("cat", ["", "NR", "nr-xyz", "leo", "nr "])
def test_validate_cell_access_type_invalid(cat):
    with pytest.raises(ValueError):
        validate_cell_access_type(cat)


@pytest.mark.parametrize("op_type", ["OP", "OPC"])
def test_validate_op_type_valid(op_type):
    assert validate_op_type(op_type) is True


@pytest.mark.parametrize("op_type", ["", "opc", "op", "OPc", "TOP"])
def test_validate_op_type_invalid(op_type):
    with pytest.raises(ValueError):
        validate_op_type(op_type)


@pytest.mark.parametrize("st", ["IPv4", "IPv6", "IPv4v6"])
def test_validate_session_type_valid(st):
    assert validate_session_type(st) is True


@pytest.mark.parametrize("st", ["", "ipv4", "IPv", "IPv4v6v4", "Ethernet"])
def test_validate_session_type_invalid(st):
    with pytest.raises(ValueError):
        validate_session_type(st)


@pytest.mark.parametrize("supi", ["imsi-999700000000001", "imsi-001010123456789"])
def test_validate_supi_valid(supi):
    assert validate_supi(supi) is True


@pytest.mark.parametrize("supi", ["", "999700000000001", "imsi-99970000000001",
                                  "imsi-9997000000000011", "imsi-99970000000000a",
                                  "IMSI-999700000000001"])
def test_validate_supi_invalid(supi):
    with pytest.raises(ValueError):
        validate_supi(supi)


@pytest.mark.xfail(strict=True, reason=(
    "bug: regex uses '$' without fullmatch, so a trailing newline is accepted"))
def test_validate_supi_rejects_trailing_newline():
    with pytest.raises(ValueError):
        validate_supi("imsi-999700000000001\n")


@pytest.mark.parametrize("key", ["465B5CE8B199B49FAA5F0A2EE238A6BC", "0" * 32, "abcdef0123456789ABCDEF0123456789"])
def test_validate_hex_key_valid(key):
    assert validate_hex_key(key) is True


@pytest.mark.parametrize("key", ["", "0" * 31, "0" * 33, "g" * 32, "0x" + "0" * 30])
def test_validate_hex_key_invalid(key):
    with pytest.raises(ValueError):
        validate_hex_key(key)


def test_validate_hex_key_error_names_the_field():
    with pytest.raises(ValueError, match="Invalid op"):
        validate_hex_key("zz", name="op")


@pytest.mark.parametrize("name", ["gnb-1", "ue_2", "A-b_9", "x"])
def test_validate_container_name_valid_without_prefix(name):
    assert validate_container_name(name) is True


@pytest.mark.parametrize("name", ["", "has space", "dot.name", "slash/name", "semi;colon"])
def test_validate_container_name_invalid(name):
    with pytest.raises(ValueError):
        validate_container_name(name)


def test_validate_container_name_with_prefix():
    assert validate_container_name("gnb-abcd", prefix="gnb") is True
    with pytest.raises(ValueError, match="must start with 'gnb-'"):
        validate_container_name("ue-abcd", prefix="gnb")
    # prefix must be followed by a hyphen
    with pytest.raises(ValueError):
        validate_container_name("gnbabcd", prefix="gnb")
