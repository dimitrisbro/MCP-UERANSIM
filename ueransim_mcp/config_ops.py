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

from typing import List, Optional

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
