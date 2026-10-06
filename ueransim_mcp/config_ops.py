"""
Shared configuration-editing commands for UERANSIM containers/pods.

Each public function returns List[List[str]] — a sequence of shell commands
to execute in order.  Callers wrap each command appropriately:

  Docker:  run_container_command([runtime, "exec", cid] + cmd, ...)
  K8s:     exec_in_pod(v1, pod_name, namespace, cmd)

All awk scripts use POSIX awk only (busybox awk on Alpine + gawk/mawk on Ubuntu).
Multi-line edits use sh -c "awk ... FILE > FILE.tmp && mv FILE.tmp FILE"
so in-place rewrite is portable across all platforms.
"""

from pathlib import Path
from typing import List, Optional

import yaml

GNB_CFG = "/etc/ueransim/open5gs-gnb.yaml"
UE_CFG  = "/etc/ueransim/open5gs-ue.yaml"


def gnb_config_cmds(
    mcc: str = "999",
    mnc: str = "70",
    tac: int = 1,
    nci: str = "0x000000010",
    id_length: int = 32,
    slice_sst: int = 1,
    slice_sd: Optional[int] = None,
    cell_access_type: str = "nr",
    gtp_advertise_ip: Optional[str] = None,
    ignore_stream_ids: bool = True,
    amf_port: Optional[str] = None,
) -> List[List[str]]:
    """Return ordered commands to configure a gNB container/pod.

    Does NOT include linkIp/ngapIp/gtpIp/amf_address — those depend on
    the container IP discovered at runtime and are handled by the caller.
    """
    f = GNB_CFG
    ignore = "true" if ignore_stream_ids else "false"

    cmds: List[List[str]] = [
        ["sed", "-i", f"s/^mcc: .*/mcc: '{mcc}'/", f],
        ["sed", "-i", f"s/^mnc: .*/mnc: '{mnc}'/", f],
        ["sed", "-i", f"s/^tac: .*/tac: {tac}/", f],
        ["sed", "-i", f"s/^nci: .*/nci: '{nci}'/", f],
        ["sed", "-i", f"s/^idLength: .*/idLength: {id_length}/", f],
        ["sed", "-i", f"s/^cellAccessType: .*/cellAccessType: {cell_access_type}/", f],
        ["sed", "-i", f"s/^ignoreStreamIds: .*/ignoreStreamIds: {ignore}/", f],
    ]

    if amf_port is not None:
        cmds.append(["sed", "-i", f"s/    port: .*/    port: {amf_port}/", f])

    # Replace the entire slices: block with the new sst (+ optional sd)
    cmds += gnb_slice_cmds(slice_sst, slice_sd)

    # gtpAdvertiseIp: replace if it already exists, otherwise insert after gtpIp
    if gtp_advertise_ip is not None:
        cmds += gnb_gtp_advertise_cmds(gtp_advertise_ip)

    return cmds


def ue_config_cmds(
    supi: Optional[str] = None,
    mcc: str = "999",
    mnc: str = "70",
    key: Optional[str] = None,
    op: Optional[str] = None,
    op_type: str = "OPC",
    slice_sst: int = 1,
    slice_sd: Optional[int] = None,
    session_apn: str = "internet",
    session_type: str = "IPv4",
    tun_netmask: str = "255.255.255.0",
) -> List[List[str]]:
    """Return ordered commands to configure a UE container/pod.

    Does NOT include gnbSearchList — that is handled by the caller.
    """
    f = UE_CFG
    cmds: List[List[str]] = [
        ["sed", "-i", f"s/^mcc: .*/mcc: '{mcc}'/", f],
        ["sed", "-i", f"s/^mnc: .*/mnc: '{mnc}'/", f],
        ["sed", "-i", f"s/^opType: .*/opType: '{op_type}'/", f],
        ["sed", "-i", f"s/^tunNetmask: .*/tunNetmask: '{tun_netmask}'/", f],
        # sessions[0].type and .apn — indented uniquely in the file
        ["sed", "-i", f"s/^  - type: .*/  - type: '{session_type}'/", f],
        ["sed", "-i", f"s/^    apn: .*/    apn: '{session_apn}'/", f],
    ]

    if supi is not None:
        cmds.append(["sed", "-i", f"s/^supi: .*/supi: '{supi}'/", f])
    if key is not None:
        cmds.append(["sed", "-i", f"s/^key: .*/key: '{key}'/", f])
    if op is not None:
        cmds.append(["sed", "-i", f"s/^op: .*/op: '{op}'/", f])

    # Update slice in all three YAML sections
    cmds += ue_slice_cmds(slice_sst, slice_sd)

    return cmds


# ── Slice helpers (also used by edit tools) ───────────────────────────────────

def gnb_slice_cmds(slice_sst: int, slice_sd: Optional[int]) -> List[List[str]]:
    """Replace the entire gNB slices: block (primary slice only)."""
    f = GNB_CFG
    sd_line = f'print "    sd: {slice_sd}"; ' if slice_sd is not None else ""
    script = (
        f"awk '/^slices:/{{print \"slices:\"; print \"  - sst: {slice_sst}\"; "
        f"{sd_line}skip=1; next}} "
        f"skip && /^[^ ]/{{skip=0}} skip{{next}} {{print}}' "
        f"{f} > {f}.tmp && mv {f}.tmp {f}"
    )
    return [["sh", "-c", script]]


def ue_slice_cmds(slice_sst: int, slice_sd: Optional[int]) -> List[List[str]]:
    """Update UE slice config in sessions, configured-nssai, and default-nssai."""
    f = UE_CFG
    cmds: List[List[str]] = [
        # sessions[].slice.sst — 6-space indent, unique to this block
        ["sed", "-i", f"s/^      sst: .*/      sst: {slice_sst}/", f],
        # configured-nssai and default-nssai sst — "  - sst:" at 2-space indent
        ["sed", "-i", f"s/^  - sst: .*/  - sst: {slice_sst}/", f],
    ]

    if slice_sd is not None:
        # sessions[].slice.sd — replace at 6-space, or insert after sst if absent
        sess_sd = (
            f"awk '/^      sd:/{{found=1; print \"      sd: {slice_sd}\"; next}} "
            f"/^      sst:/ && !found{{print; print \"      sd: {slice_sd}\"; "
            f"found=1; next}} {{print}}' "
            f"{f} > {f}.tmp && mv {f}.tmp {f}"
        )
        cmds.append(["sh", "-c", sess_sd])

        # configured-nssai and default-nssai sd — replace at 4-space, or insert
        # after "  - sst:"; reset found at each new top-level YAML key so both
        # sections are handled independently
        nssai_sd = (
            f"awk '/^[a-zA-Z]/{{found=0}} "
            f"/^    sd:/{{found=1; print \"    sd: {slice_sd}\"; next}} "
            f"/^  - sst:/ && !found{{print; print \"    sd: {slice_sd}\"; "
            f"found=1; next}} {{print}}' "
            f"{f} > {f}.tmp && mv {f}.tmp {f}"
        )
        cmds.append(["sh", "-c", nssai_sd])

    return cmds


def gnb_gtp_advertise_cmds(gtp_advertise_ip: str) -> List[List[str]]:
    """Insert or replace the gtpAdvertiseIp field (after gtpIp if not present)."""
    f = GNB_CFG
    script = (
        f"awk '/^gtpAdvertiseIp:/{{found=1; "
        f"print \"gtpAdvertiseIp: {gtp_advertise_ip}\"; next}} "
        f"/^gtpIp:/ && !found{{print; "
        f"print \"gtpAdvertiseIp: {gtp_advertise_ip}\"; found=1; next}} "
        f"{{print}}' "
        f"{f} > {f}.tmp && mv {f}.tmp {f}"
    )
    return [["sh", "-c", script]]


# ── Kubernetes: config as a ConfigMap, edited as YAML ─────────────────────────
#
# K8s pods mount their config read-only from a ConfigMap (subPath), so the sed/awk
# commands above can't edit it in place. The K8s tools build and edit the config
# as a dict instead, store it in the pod's ConfigMap, and recreate the pod.

POD_IP_PLACEHOLDER = "__POD_IP__"

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def load_template(kind: str) -> dict:
    """Return the default config for 'gnb' or 'ue' from config/open5gs-<kind>.yaml."""
    return yaml.safe_load((_CONFIG_DIR / f"open5gs-{kind}.yaml").read_text())


def dump_config(cfg: dict) -> str:
    return yaml.safe_dump(cfg, sort_keys=False)


def gnb_pod_command(cfg_path: str = GNB_CFG) -> List[str]:
    """nr-gnb as PID 1, with __POD_IP__ in the config replaced by the pod's IP.

    Same shape as the networkAssistant infra/ gNB manifests.
    """
    return [
        "sh", "-c",
        f"sed \"s/{POD_IP_PLACEHOLDER}/$(hostname -i)/g\" {cfg_path} > /tmp/gnb.yaml"
        " && exec /usr/local/bin/nr-gnb -c /tmp/gnb.yaml",
    ]


def ue_pod_command(cfg_path: str = UE_CFG) -> List[str]:
    return ["/usr/local/bin/nr-ue", "-c", cfg_path]


def _slices(sst: int, sd: Optional[int]) -> List[dict]:
    return [{"sst": sst, "sd": sd} if sd is not None else {"sst": sst}]


def build_gnb_config(
    amf_address: str,
    amf_port: str,
    mcc: str,
    mnc: str,
    tac: int,
    nci: str,
    id_length: int,
    slice_sst: int,
    slice_sd: Optional[int],
    cell_access_type: str,
    gtp_advertise_ip: Optional[str],
    ignore_stream_ids: bool,
) -> dict:
    cfg = load_template("gnb")
    cfg.update(
        mcc=mcc, mnc=mnc, nci=nci, idLength=id_length, tac=tac,
        linkIp=POD_IP_PLACEHOLDER, ngapIp=POD_IP_PLACEHOLDER, gtpIp=POD_IP_PLACEHOLDER,
        amfConfigs=[{"address": amf_address, "port": int(amf_port)}],
        slices=_slices(slice_sst, slice_sd),
        ignoreStreamIds=ignore_stream_ids, cellAccessType=cell_access_type,
    )
    if gtp_advertise_ip is not None:
        cfg["gtpAdvertiseIp"] = gtp_advertise_ip
    return cfg


def build_ue_config(
    gnb_search_list: str,
    supi: Optional[str],
    mcc: str,
    mnc: str,
    key: Optional[str],
    op: Optional[str],
    op_type: str,
    slice_sst: int,
    slice_sd: Optional[int],
    session_apn: str,
    session_type: str,
    tun_netmask: str,
) -> dict:
    cfg = load_template("ue")
    cfg.update(mcc=mcc, mnc=mnc, opType=op_type, tunNetmask=tun_netmask,
               gnbSearchList=[gnb_search_list])
    for field, value in (("supi", supi), ("key", key), ("op", op)):
        if value is not None:
            cfg[field] = value
    cfg["sessions"][0].update(type=session_type, apn=session_apn)
    _set_ue_slice(cfg, slice_sst, slice_sd)
    return cfg


def _set_ue_slice(cfg: dict, sst: int, sd: Optional[int]) -> None:
    for session in cfg["sessions"]:
        session["slice"] = _slices(sst, sd)[0]
    cfg["configured-nssai"] = _slices(sst, sd)
    cfg["default-nssai"] = _slices(sst, sd)


# config_type -> (YAML key, value parser) for single-field edits.
_GNB_FIELDS = {
    "ngap_ip": ("ngapIp", str), "gtp_ip": ("gtpIp", str),
    "mcc": ("mcc", str), "mnc": ("mnc", str), "tac": ("tac", int), "nci": ("nci", str),
    "id_length": ("idLength", int), "cell_access_type": ("cellAccessType", str),
    "ignore_stream_ids": ("ignoreStreamIds", lambda v: v.lower() == "true"),
    "gtp_advertise_ip": ("gtpAdvertiseIp", str),
}
_UE_FIELDS = {
    "supi": ("supi", str), "key": ("key", str), "op": ("op", str),
    "op_type": ("opType", str), "mcc": ("mcc", str), "mnc": ("mnc", str),
    "tun_netmask": ("tunNetmask", str),
}


def apply_config_edit(cfg: dict, ctype: str, config_type: str, config_value: str) -> bool:
    """Apply one k8s_edit_pod_config edit to cfg in place. False if unsupported."""
    if config_type == "slice":
        parts = config_value.split(",")
        sst, sd = int(parts[0]), int(parts[1]) if len(parts) > 1 else None
        if ctype == "gnb":
            cfg["slices"] = _slices(sst, sd)
        elif ctype == "ue":
            _set_ue_slice(cfg, sst, sd)
        else:
            return False
        return True
    if ctype == "gnb":
        if config_type == "amf_ip":
            cfg["amfConfigs"][0]["address"] = config_value
            return True
        fields = _GNB_FIELDS
    elif ctype == "ue":
        if config_type == "gnb_search_list":
            cfg["gnbSearchList"] = [config_value]
            return True
        if config_type in ("session_apn", "session_type"):
            cfg["sessions"][0][config_type.removeprefix("session_")] = config_value
            return True
        fields = _UE_FIELDS
    else:
        return False
    if config_type not in fields:
        return False
    yaml_key, parse = fields[config_type]
    cfg[yaml_key] = parse(config_value)
    return True
