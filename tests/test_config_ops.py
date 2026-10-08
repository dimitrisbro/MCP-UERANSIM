"""Unit tests for ueransim_mcp.config_ops (Docker sed/awk commands and K8s dict builders).

The Docker command builders are checked two ways: by inspecting the generated sed
expressions, and by running them (via sh) against a copy of the shipped template and
parsing the resulting YAML, so the assertions are on the UERANSIM config contract.
"""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from ueransim_mcp.config_ops import (
    GNB_CFG, POD_IP_PLACEHOLDER, UE_CFG, apply_config_edit, build_gnb_config, build_ue_config,
    gnb_config_cmds, gnb_gtp_advertise_cmds, gnb_pod_command, gnb_slice_cmds, load_template,
    ue_config_cmds, ue_pod_command, ue_slice_cmds,
)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"

GNB_ARGS = dict(
    amf_address="10.0.0.5", amf_port="38412", mcc="001", mnc="01", tac=7,
    nci="0x000000abc", id_length=24, slice_sst=1, slice_sd=None, cell_access_type="nr",
    gtp_advertise_ip=None, ignore_stream_ids=True,
)
UE_ARGS = dict(
    gnb_search_list="10.0.0.9", supi="imsi-001010000000001", mcc="001", mnc="01",
    key=None, op=None, op_type="OPC", slice_sst=1, slice_sd=None,
    session_apn="internet", session_type="IPv4", tun_netmask="255.255.255.0",
)


def _sed_exprs(cmds):
    """Map sed commands to their s/// expression; assert every one targets the config file."""
    return [c[2] for c in cmds if c[0] == "sed"]


# The commands run inside the Linux UERANSIM container (GNU sed). BSD sed (macOS) rejects
# `sed -i <file>`, so executing them on such a host would test the host, not the contract.
GNU_SED = subprocess.run(["sed", "--version"], capture_output=True).returncode == 0


def _run(cmds, kind, tmp_path):
    """Execute commands against a temp copy of the template and return the parsed YAML."""
    if not GNU_SED:
        pytest.skip("needs GNU sed, as in the UERANSIM container")
    real = GNB_CFG if kind == "gnb" else UE_CFG
    target = tmp_path / f"open5gs-{kind}.yaml"
    shutil.copy(CONFIG_DIR / f"open5gs-{kind}.yaml", target)
    for cmd in cmds:
        rewritten = [a.replace(real, str(target)) for a in cmd]
        subprocess.run(rewritten, check=True, capture_output=True)
    return yaml.safe_load(target.read_text())


# ── Docker: gNB ───────────────────────────────────────────────────────────────

def test_gnb_config_cmds_target_gnb_file_and_keys():
    cmds = gnb_config_cmds(mcc="001", mnc="01", tac=7, nci="0x000000abc", id_length=24,
                           cell_access_type="nr-leo", ignore_stream_ids=False)
    assert all(c[-1] == GNB_CFG or c[:2] == ["sh", "-c"] for c in cmds)
    exprs = _sed_exprs(cmds)
    assert "s/^mcc: .*/mcc: '001'/" in exprs
    assert "s/^mnc: .*/mnc: '01'/" in exprs
    assert "s/^tac: .*/tac: 7/" in exprs
    assert "s/^nci: .*/nci: '0x000000abc'/" in exprs
    assert "s/^idLength: .*/idLength: 24/" in exprs
    assert "s/^cellAccessType: .*/cellAccessType: nr-leo/" in exprs
    assert "s/^ignoreStreamIds: .*/ignoreStreamIds: false/" in exprs


def test_gnb_config_cmds_amf_port_only_when_given():
    assert not any("port:" in e for e in _sed_exprs(gnb_config_cmds()))
    exprs = _sed_exprs(gnb_config_cmds(amf_port="30412"))
    assert "s/    port: .*/    port: 30412/" in exprs


def test_gnb_config_cmds_gtp_advertise_only_when_given():
    assert not any("gtpAdvertiseIp" in " ".join(c) for c in gnb_config_cmds())
    cmds = gnb_config_cmds(gtp_advertise_ip="1.2.3.4")
    assert any("gtpAdvertiseIp: 1.2.3.4" in " ".join(c) for c in cmds)


def test_gnb_config_cmds_defaults_applied_to_template(tmp_path):
    cfg = _run(gnb_config_cmds(), "gnb", tmp_path)
    assert (cfg["mcc"], cfg["mnc"], cfg["tac"]) == ("999", "70", 1)
    assert cfg["nci"] == "0x000000010"
    assert cfg["idLength"] == 32
    assert cfg["slices"] == [{"sst": 1}]
    assert cfg["ignoreStreamIds"] is True
    assert cfg["cellAccessType"] == "nr"
    assert "gtpAdvertiseIp" not in cfg


def test_gnb_config_cmds_executed_result(tmp_path):
    cmds = gnb_config_cmds(mcc="001", mnc="01", tac=7, nci="0x000000abc", id_length=24,
                           slice_sst=2, slice_sd=5, cell_access_type="nr-geo",
                           gtp_advertise_ip="1.2.3.4", ignore_stream_ids=False, amf_port="30412")
    cfg = _run(cmds, "gnb", tmp_path)
    assert (cfg["mcc"], cfg["mnc"], cfg["tac"]) == ("001", "01", 7)
    assert cfg["nci"] == "0x000000abc"
    assert cfg["idLength"] == 24
    assert cfg["cellAccessType"] == "nr-geo"
    assert cfg["ignoreStreamIds"] is False
    assert cfg["slices"] == [{"sst": 2, "sd": 5}]
    assert cfg["gtpAdvertiseIp"] == "1.2.3.4"
    assert cfg["amfConfigs"][0]["port"] == 30412
    # untouched keys survive
    assert cfg["amfConfigs"][0]["address"] == "127.0.0.5"
    assert cfg["gtpIp"] == "127.0.0.1"


def test_gnb_slice_cmds_without_sd(tmp_path):
    cmds = gnb_slice_cmds(3, None)
    assert len(cmds) == 1 and cmds[0][:2] == ["sh", "-c"]
    assert "sst: 3" in cmds[0][2] and "sd:" not in cmds[0][2]
    cfg = _run(cmds, "gnb", tmp_path)
    assert cfg["slices"] == [{"sst": 3}]
    assert cfg["ignoreStreamIds"] is True  # following top-level keys preserved


def test_gnb_slice_cmds_with_sd(tmp_path):
    cmds = gnb_slice_cmds(3, 10)
    assert "sd: 10" in cmds[0][2]
    cfg = _run(cmds, "gnb", tmp_path)
    assert cfg["slices"] == [{"sst": 3, "sd": 10}]
    assert cfg["cellAccessType"] == "nr"


def test_gnb_gtp_advertise_inserts_after_gtp_ip(tmp_path):
    cmds = gnb_gtp_advertise_cmds("9.9.9.9")
    assert "gtpAdvertiseIp: 9.9.9.9" in cmds[0][2]
    cfg = _run(cmds, "gnb", tmp_path)
    assert cfg["gtpAdvertiseIp"] == "9.9.9.9"
    keys = list(cfg)
    assert keys.index("gtpAdvertiseIp") == keys.index("gtpIp") + 1


@pytest.mark.xfail(strict=True, reason=(
    "bug: awk sees gtpIp before the existing gtpAdvertiseIp, so it inserts a new line "
    "and then also rewrites the old one, leaving a duplicate key"))
def test_gnb_gtp_advertise_replaces_existing(tmp_path):
    first = gnb_gtp_advertise_cmds("1.1.1.1")
    second = gnb_gtp_advertise_cmds("2.2.2.2")
    cfg = _run(first + second, "gnb", tmp_path)
    assert cfg["gtpAdvertiseIp"] == "2.2.2.2"
    assert (tmp_path / "open5gs-gnb.yaml").read_text().count("gtpAdvertiseIp:") == 1


# ── Docker: UE ────────────────────────────────────────────────────────────────

def test_ue_config_cmds_target_ue_file_and_keys():
    cmds = ue_config_cmds(supi="imsi-001010000000001", mcc="001", mnc="01", key="K" * 32,
                          op="O" * 32, op_type="OP", session_apn="ims", session_type="IPv6",
                          tun_netmask="255.255.0.0")
    assert all(c[-1] == UE_CFG or c[:2] == ["sh", "-c"] for c in cmds)
    exprs = _sed_exprs(cmds)
    assert "s/^supi: .*/supi: 'imsi-001010000000001'/" in exprs
    assert "s/^mcc: .*/mcc: '001'/" in exprs
    assert "s/^mnc: .*/mnc: '01'/" in exprs
    assert f"s/^key: .*/key: '{'K' * 32}'/" in exprs
    assert f"s/^op: .*/op: '{'O' * 32}'/" in exprs
    assert "s/^opType: .*/opType: 'OP'/" in exprs
    assert "s/^tunNetmask: .*/tunNetmask: '255.255.0.0'/" in exprs
    assert "s/^  - type: .*/  - type: 'IPv6'/" in exprs
    assert "s/^    apn: .*/    apn: 'ims'/" in exprs


def test_ue_config_cmds_optional_fields_omitted_by_default():
    exprs = _sed_exprs(ue_config_cmds())
    assert not any(e.startswith(("s/^supi", "s/^key", "s/^op:")) for e in exprs)


def test_ue_config_cmds_executed_result(tmp_path):
    key, op = "A" * 32, "B" * 32
    cmds = ue_config_cmds(supi="imsi-001010000000001", mcc="001", mnc="01", key=key, op=op,
                          op_type="OP", slice_sst=2, slice_sd=4, session_apn="ims",
                          session_type="IPv4v6", tun_netmask="255.255.0.0")
    cfg = _run(cmds, "ue", tmp_path)
    assert cfg["supi"] == "imsi-001010000000001"
    assert (cfg["mcc"], cfg["mnc"]) == ("001", "01")
    assert (cfg["key"], cfg["op"], cfg["opType"]) == (key, op, "OP")
    assert cfg["tunNetmask"] == "255.255.0.0"
    assert cfg["sessions"][0]["type"] == "IPv4v6"
    assert cfg["sessions"][0]["apn"] == "ims"
    assert cfg["sessions"][0]["slice"] == {"sst": 2, "sd": 4}
    assert cfg["configured-nssai"] == [{"sst": 2, "sd": 4}]
    assert cfg["default-nssai"] == [{"sst": 2, "sd": 4}]


def test_ue_slice_cmds_without_sd_only_sets_sst(tmp_path):
    cmds = ue_slice_cmds(4, None)
    assert all(c[0] == "sed" for c in cmds)
    exprs = _sed_exprs(cmds)
    assert "s/^      sst: .*/      sst: 4/" in exprs
    assert "s/^  - sst: .*/  - sst: 4/" in exprs
    cfg = _run(cmds, "ue", tmp_path)
    assert cfg["sessions"][0]["slice"]["sst"] == 4
    assert [s["sst"] for s in cfg["configured-nssai"]] == [4]
    assert [s["sst"] for s in cfg["default-nssai"]] == [4]


def test_ue_slice_cmds_with_sd_adds_awk_steps(tmp_path):
    cmds = ue_slice_cmds(4, 9)
    assert len(cmds) == 4
    assert all("sd: 9" in c[2] for c in cmds[2:])
    cfg = _run(cmds, "ue", tmp_path)
    assert cfg["sessions"][0]["slice"] == {"sst": 4, "sd": 9}
    assert cfg["configured-nssai"] == [{"sst": 4, "sd": 9}]
    # default-nssai already had sd: 1 in the template; it must be replaced, not duplicated
    assert cfg["default-nssai"] == [{"sst": 4, "sd": 9}]


# ── K8s: build_*_config ───────────────────────────────────────────────────────

def test_build_gnb_config_fields_on_template_keys():
    cfg = build_gnb_config(**GNB_ARGS)
    assert (cfg["mcc"], cfg["mnc"], cfg["tac"]) == ("001", "01", 7)
    assert cfg["nci"] == "0x000000abc"
    assert cfg["idLength"] == 24
    assert cfg["cellAccessType"] == "nr"
    assert cfg["ignoreStreamIds"] is True
    assert cfg["amfConfigs"] == [{"address": "10.0.0.5", "port": 38412}]
    for key in ("linkIp", "ngapIp", "gtpIp"):
        assert cfg[key] == POD_IP_PLACEHOLDER
    assert cfg["slices"] == [{"sst": 1}]
    assert "gtpAdvertiseIp" not in cfg


def test_build_gnb_config_slice_with_sd_and_advertise_ip():
    cfg = build_gnb_config(**{**GNB_ARGS, "slice_sst": 2, "slice_sd": 5,
                              "gtp_advertise_ip": "1.2.3.4", "cell_access_type": "nr-leo",
                              "ignore_stream_ids": False})
    assert cfg["slices"] == [{"sst": 2, "sd": 5}]
    assert cfg["gtpAdvertiseIp"] == "1.2.3.4"
    assert cfg["cellAccessType"] == "nr-leo"
    assert cfg["ignoreStreamIds"] is False


def test_build_gnb_config_does_not_mutate_template():
    build_gnb_config(**GNB_ARGS)
    assert load_template("gnb")["mcc"] == "999"


def test_build_ue_config_fields_on_template_keys():
    cfg = build_ue_config(**UE_ARGS)
    assert cfg["supi"] == "imsi-001010000000001"
    assert (cfg["mcc"], cfg["mnc"]) == ("001", "01")
    assert cfg["opType"] == "OPC"
    assert cfg["tunNetmask"] == "255.255.255.0"
    assert cfg["gnbSearchList"] == ["10.0.0.9"]
    assert cfg["sessions"][0]["type"] == "IPv4"
    assert cfg["sessions"][0]["apn"] == "internet"
    assert cfg["sessions"][0]["slice"] == {"sst": 1}
    assert cfg["configured-nssai"] == [{"sst": 1}]
    assert cfg["default-nssai"] == [{"sst": 1}]  # template's sd: 1 must be dropped
    # key/op not given -> template defaults kept
    tpl = load_template("ue")
    assert cfg["key"] == tpl["key"] and cfg["op"] == tpl["op"]


def test_build_ue_config_with_sd_key_and_op():
    cfg = build_ue_config(**{**UE_ARGS, "slice_sst": 3, "slice_sd": 6, "key": "A" * 32,
                             "op": "B" * 32, "op_type": "OP", "session_apn": "ims",
                             "session_type": "IPv6", "supi": None})
    assert cfg["key"] == "A" * 32 and cfg["op"] == "B" * 32 and cfg["opType"] == "OP"
    assert cfg["sessions"][0]["slice"] == {"sst": 3, "sd": 6}
    assert cfg["configured-nssai"] == [{"sst": 3, "sd": 6}]
    assert cfg["default-nssai"] == [{"sst": 3, "sd": 6}]
    assert (cfg["sessions"][0]["type"], cfg["sessions"][0]["apn"]) == ("IPv6", "ims")
    assert cfg["supi"] == load_template("ue")["supi"]  # None keeps the template value


# ── K8s: apply_config_edit ────────────────────────────────────────────────────

@pytest.mark.parametrize("config_type,value,key,expected", [
    ("ngap_ip", "10.1.1.1", "ngapIp", "10.1.1.1"),
    ("gtp_ip", "10.1.1.2", "gtpIp", "10.1.1.2"),
    ("mcc", "310", "mcc", "310"),
    ("mnc", "410", "mnc", "410"),
    ("tac", "42", "tac", 42),
    ("nci", "0x000000099", "nci", "0x000000099"),
    ("id_length", "24", "idLength", 24),
    ("cell_access_type", "nr-geo", "cellAccessType", "nr-geo"),
    ("ignore_stream_ids", "false", "ignoreStreamIds", False),
    ("ignore_stream_ids", "True", "ignoreStreamIds", True),
    ("gtp_advertise_ip", "5.5.5.5", "gtpAdvertiseIp", "5.5.5.5"),
])
def test_apply_config_edit_gnb_fields(config_type, value, key, expected):
    cfg = load_template("gnb")
    assert apply_config_edit(cfg, "gnb", config_type, value) is True
    assert cfg[key] == expected


def test_apply_config_edit_gnb_amf_ip():
    cfg = load_template("gnb")
    assert apply_config_edit(cfg, "gnb", "amf_ip", "10.9.9.9") is True
    assert cfg["amfConfigs"][0]["address"] == "10.9.9.9"
    assert cfg["amfConfigs"][0]["port"] == 38412


def test_apply_config_edit_gnb_slice():
    cfg = load_template("gnb")
    assert apply_config_edit(cfg, "gnb", "slice", "2,7") is True
    assert cfg["slices"] == [{"sst": 2, "sd": 7}]
    assert apply_config_edit(cfg, "gnb", "slice", "3") is True
    assert cfg["slices"] == [{"sst": 3}]


@pytest.mark.parametrize("config_type,value,key,expected", [
    ("supi", "imsi-001010000000002", "supi", "imsi-001010000000002"),
    ("key", "C" * 32, "key", "C" * 32),
    ("op", "D" * 32, "op", "D" * 32),
    ("op_type", "OP", "opType", "OP"),
    ("mcc", "310", "mcc", "310"),
    ("mnc", "410", "mnc", "410"),
    ("tun_netmask", "255.255.0.0", "tunNetmask", "255.255.0.0"),
    ("gnb_search_list", "10.2.2.2", "gnbSearchList", ["10.2.2.2"]),
])
def test_apply_config_edit_ue_fields(config_type, value, key, expected):
    cfg = load_template("ue")
    assert apply_config_edit(cfg, "ue", config_type, value) is True
    assert cfg[key] == expected


def test_apply_config_edit_ue_session_fields():
    cfg = load_template("ue")
    assert apply_config_edit(cfg, "ue", "session_apn", "ims") is True
    assert apply_config_edit(cfg, "ue", "session_type", "IPv6") is True
    assert cfg["sessions"][0]["apn"] == "ims"
    assert cfg["sessions"][0]["type"] == "IPv6"


def test_apply_config_edit_ue_slice():
    cfg = load_template("ue")
    assert apply_config_edit(cfg, "ue", "slice", "2,3") is True
    assert cfg["sessions"][0]["slice"] == {"sst": 2, "sd": 3}
    assert cfg["configured-nssai"] == [{"sst": 2, "sd": 3}]
    assert cfg["default-nssai"] == [{"sst": 2, "sd": 3}]
    assert apply_config_edit(cfg, "ue", "slice", "5") is True
    assert cfg["sessions"][0]["slice"] == {"sst": 5}
    assert cfg["default-nssai"] == [{"sst": 5}]


@pytest.mark.parametrize("ctype,config_type", [
    ("gnb", "bogus"), ("gnb", "supi"), ("gnb", "gnb_search_list"),
    ("ue", "bogus"), ("ue", "ngap_ip"), ("ue", "amf_ip"),
    ("other", "mcc"), ("unknown", "slice"),
])
def test_apply_config_edit_unsupported_returns_false_and_leaves_cfg(ctype, config_type):
    cfg = load_template("gnb" if ctype == "gnb" else "ue")
    before = yaml.safe_dump(cfg)
    assert apply_config_edit(cfg, ctype, config_type, "1") is False
    assert yaml.safe_dump(cfg) == before


# ── K8s: pod commands ─────────────────────────────────────────────────────────

def test_gnb_pod_command_renders_pod_ip_and_execs_nr_gnb():
    cmd = gnb_pod_command()
    assert cmd[:2] == ["sh", "-c"]
    script = cmd[2]
    assert f"s/{POD_IP_PLACEHOLDER}/$(hostname -i)/g" in script
    assert GNB_CFG in script
    assert script.endswith("exec /usr/local/bin/nr-gnb -c /tmp/gnb.yaml")


def test_gnb_pod_command_custom_cfg_path():
    assert "/custom/gnb.yaml" in gnb_pod_command("/custom/gnb.yaml")[2]


def test_ue_pod_command():
    assert ue_pod_command() == ["/usr/local/bin/nr-ue", "-c", UE_CFG]
    assert ue_pod_command("/x.yaml") == ["/usr/local/bin/nr-ue", "-c", "/x.yaml"]
