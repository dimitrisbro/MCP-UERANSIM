import re
import sys
import time
from typing import Optional

from .app import mcp
from .models import (
    GnbConfiguration, GnbContainer, GnbCreateResponse, GnbListResponse, GnbOperationResponse,
    UeConfiguration, UeContainer, UeCreateResponse, UeListResponse, UeOperationResponse,
)
from .utils import generate_random_suffix
from .validators import (
    validate_ip, validate_container_id, validate_container_name,
    validate_mcc, validate_mnc, validate_nci, validate_cell_access_type,
    validate_op_type, validate_session_type, validate_supi, validate_hex_key,
)
from .docker_utils import (
    get_container_runtime, run_container_command, detect_image_os,
    validate_existing_container, get_container_name,
)
from .config_ops import (
    gnb_config_cmds, ue_config_cmds,
    gnb_slice_cmds, ue_slice_cmds, gnb_gtp_advertise_cmds,
    GNB_CFG, UE_CFG,
)

_GNB_IMAGE = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest"
_UE_IMAGE  = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest"


def _is_container_id(value: str) -> bool:
    return bool(re.match(r'^[0-9a-fA-F]+$', value)) and len(value) in (12, 64)


def _exec(runtime: str, container_id: str, cmd: list,
          capture: bool = True) -> object:
    """Wrap a config_ops command for docker exec."""
    return run_container_command(
        [runtime, "exec", container_id] + cmd,
        capture_output=capture, text=True,
    )


def _detect_type(runtime: str, container_id_or_name: str) -> str:
    """Return 'gnb', 'ue', or 'unknown' from the container name prefix."""
    name = get_container_name(container_id_or_name)
    if name.startswith("gnb-"):
        return "gnb"
    if name.startswith("ue-"):
        return "ue"
    return "unknown"


# ── gNB tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def create_gnb(
    amf_address: str = "127.0.0.5",
    amf_port: str = "38412",
    container_name: Optional[str] = None,
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
) -> GnbCreateResponse:
    """Create a new gNB container.

    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        container_name: Optional container name (auto-generated if omitted)
        mcc: Mobile Country Code (3 digits)
        mnc: Mobile Network Code (2-3 digits)
        tac: Tracking Area Code
        nci: NR Cell Identity (36-bit hex, e.g. 0x000000010)
        id_length: NR gNB ID length in bits [22..32]
        slice_sst: Primary slice SST
        slice_sd: Primary slice SD (optional)
        cell_access_type: nr | nr-leo | nr-meo | nr-geo | nr-othersat
        gtp_advertise_ip: GTP advertise IP override (for NAT scenarios)
        ignore_stream_ids: Whether to ignore SCTP stream ID errors
    """
    _empty_cfg = lambda: GnbConfiguration(
        link_ip="", ngap_ip="", gtp_ip="",
        amf_address=amf_address, amf_port=amf_port,
        mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
        slice_sst=slice_sst, slice_sd=slice_sd,
        cell_access_type=cell_access_type,
        gtp_advertise_ip=gtp_advertise_ip,
        ignore_stream_ids=ignore_stream_ids,
    )
    try:
        validate_ip(amf_address)
        validate_mcc(mcc)
        validate_mnc(mnc)
        validate_nci(nci)
        validate_cell_access_type(cell_access_type)
        if gtp_advertise_ip is not None:
            validate_ip(gtp_advertise_ip)

        runtime = get_container_runtime()

        if container_name:
            validate_container_name(container_name, "gnb")
        else:
            container_name = f"gnb-{generate_random_suffix()}"

        result = run_container_command(
            [runtime, "run", "-d", "--name", container_name, _GNB_IMAGE],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id="", container_name="",
                configuration=_empty_cfg(), message=result.stderr,
            )

        container_id = result.stdout.strip()

        # Discover container IP
        inspect = run_container_command(
            [runtime, "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_id],
            capture_output=True, text=True,
        )
        if inspect.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id=container_id, container_name=container_name,
                configuration=_empty_cfg(),
                message=f"Failed to get container IP: {inspect.stderr}",
            )
        ip = inspect.stdout.strip()

        # Update interface IPs and AMF address
        for field, pattern in [
            ("linkIp", f"s/linkIp: .*/linkIp: {ip}/"),
            ("ngapIp", f"s/ngapIp: .*/ngapIp: {ip}/"),
            ("gtpIp",  f"s/gtpIp: .*/gtpIp: {ip}/"),
        ]:
            r = _exec(runtime, container_id,
                      ["sed", "-i", pattern, GNB_CFG])
            if r.returncode != 0:
                return GnbCreateResponse(
                    status="error", container_id=container_id,
                    container_name=container_name,
                    configuration=_empty_cfg(),
                    message=f"Failed to update {field}: {r.stderr}",
                )

        r = _exec(runtime, container_id,
                  ["sed", "-i", f"s/- address: .*/- address: {amf_address}/", GNB_CFG])
        if r.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id=container_id,
                container_name=container_name, configuration=_empty_cfg(),
                message=f"Failed to update AMF address: {r.stderr}",
            )

        # Apply additional parametric config
        for cmd in gnb_config_cmds(
            mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
            slice_sst=slice_sst, slice_sd=slice_sd,
            cell_access_type=cell_access_type,
            gtp_advertise_ip=gtp_advertise_ip,
            ignore_stream_ids=ignore_stream_ids,
        ):
            r = _exec(runtime, container_id, cmd)
            if r.returncode != 0:
                return GnbCreateResponse(
                    status="error", container_id=container_id,
                    container_name=container_name, configuration=_empty_cfg(),
                    message=f"Config command failed ({cmd[0]}): {r.stderr}",
                )

        return GnbCreateResponse(
            status="success", container_id=container_id, container_name=container_name,
            configuration=GnbConfiguration(
                link_ip=ip, ngap_ip=ip, gtp_ip=ip,
                amf_address=amf_address, amf_port=amf_port,
                mcc=mcc, mnc=mnc, tac=tac, nci=nci, id_length=id_length,
                slice_sst=slice_sst, slice_sd=slice_sd,
                cell_access_type=cell_access_type,
                gtp_advertise_ip=gtp_advertise_ip,
                ignore_stream_ids=ignore_stream_ids,
            ),
        )

    except ValueError as e:
        return GnbCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(), message=str(e),
        )
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = "Container runtime (Docker) not found or not accessible"
        elif "permission" in msg.lower():
            msg = f"Permission denied: {msg}"
        return GnbCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(), message=msg,
        )


@mcp.tool()
def list_gnbs() -> GnbListResponse:
    """List all gNB containers."""
    try:
        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "ps", "-a", "--filter", "name=gnb-",
             "--format", "{{.ID}}|{{.Names}}|{{.Status}}|{{.CreatedAt}}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return GnbListResponse(status="error", containers=[], count=0,
                                   message=result.stderr)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                cid, name, status, created = line.split('|', 3)
                containers.append(GnbContainer(id=cid, name=name, status=status,
                                               created=created))
        return GnbListResponse(status="success", containers=containers,
                               count=len(containers))
    except Exception as e:
        return GnbListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def delete_gnb(container_id_or_name: str) -> GnbOperationResponse:
    """Delete a gNB container (stop then remove).

    Args:
        container_id_or_name: Container ID or name
    """
    try:
        if _is_container_id(container_id_or_name):
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")

        runtime = get_container_runtime()
        for sub_cmd, verb in [("stop", "stop"), ("rm", "remove")]:
            r = run_container_command(
                [runtime, sub_cmd, container_id_or_name], capture_output=True, text=True
            )
            if r.returncode != 0:
                return GnbOperationResponse(
                    status="error", message=f"Failed to {verb} container: {r.stderr}",
                    container=container_id_or_name,
                )
        return GnbOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name,
        )
    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)


@mcp.tool()
def get_gnb_logs(container_id_or_name: str, lines: int = 100) -> GnbOperationResponse:
    """Get logs from a gNB container.

    Args:
        container_id_or_name: Container ID or name
        lines: Number of lines to retrieve (default: 100)
    """
    try:
        if _is_container_id(container_id_or_name):
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")

        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "logs", f"--tail={lines}", container_id_or_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return GnbOperationResponse(status="error", message=result.stderr,
                                        container=container_id_or_name)
        return GnbOperationResponse(status="success", message="Logs retrieved successfully",
                                    container=container_id_or_name, logs=result.stdout)
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)


@mcp.tool()
def attach_gnb_to_core(
    container_id_or_name: str, amf_address: str = "127.0.0.5"
) -> GnbOperationResponse:
    """Update AMF address and start the nr-gnb process inside the container.

    Args:
        container_id_or_name: gNB container ID or name
        amf_address: AMF IP address (default: 127.0.0.5)
    """
    try:
        validate_ip(amf_address)
        if _is_container_id(container_id_or_name):
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "gnb")

        runtime = get_container_runtime()
        r = _exec(runtime, container_id_or_name,
                  ["sed", "-i", f"s/- address: .*/- address: {amf_address}/", GNB_CFG])
        if r.returncode != 0:
            return GnbOperationResponse(
                status="error", message=f"Failed to update AMF address: {r.stderr}",
                container=container_id_or_name,
            )

        r = _exec(runtime, container_id_or_name,
                  ["sh", "-c",
                   "nohup /usr/local/bin/nr-gnb -c /etc/ueransim/open5gs-gnb.yaml"
                   " > /proc/1/fd/1 2>&1 &"])
        if r.returncode != 0:
            return GnbOperationResponse(
                status="error", message=f"Failed to start nr-gnb: {r.stderr}",
                container=container_id_or_name,
            )

        time.sleep(2)
        status_r = _exec(runtime, container_id_or_name,
                         ["sh", "-c",
                          "pgrep -f nr-gnb && echo 'gNB process is running'"
                          " || echo 'gNB process not found'"])
        process_ok = status_r.returncode == 0 and "process is running" in status_r.stdout

        return GnbOperationResponse(
            status="success",
            message=(f"Container {container_id_or_name} connected to core with AMF"
                     f" {amf_address}. {'Process started.' if process_ok else 'Process may not be running.'}"),
            container=container_id_or_name,
            logs=status_r.stdout if status_r.returncode == 0 else None,
        )
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)


# ── Common tools ──────────────────────────────────────────────────────────────

@mcp.tool()
def inspect_container_ip(container_id_or_name: str) -> GnbOperationResponse:
    """Return the IP address of a Docker container.

    Args:
        container_id_or_name: Container ID or name
    """
    try:
        validate_existing_container(container_id_or_name)
        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
             container_id_or_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return GnbOperationResponse(
                status="error", message=f"Failed to inspect container: {result.stderr}",
                container=container_id_or_name,
            )
        ip = result.stdout.strip()
        if not ip:
            return GnbOperationResponse(
                status="error",
                message=f"No IP address found for container {container_id_or_name}",
                container=container_id_or_name,
            )
        return GnbOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} IP address: {ip}",
            container=container_id_or_name, logs=ip,
        )
    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)
    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e),
                                    container=container_id_or_name)


# ── UE tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def create_ue(
    gnb_search_list: str = "127.0.0.1",
    container_name: Optional[str] = None,
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
) -> UeCreateResponse:
    """Create a new UE container.

    Args:
        gnb_search_list: gNB IP for Radio Link Simulation, or 'auto' to use first available gNB
        container_name: Optional container name (auto-generated if omitted)
        supi: SUPI in imsi-MCCMNCMSISDN format (15 digits after imsi-)
        mcc: Mobile Country Code (3 digits)
        mnc: Mobile Network Code (2-3 digits)
        key: Permanent subscription key (32 hex chars)
        op: Operator code (32 hex chars)
        op_type: OP or OPC
        slice_sst: Primary slice SST
        slice_sd: Primary slice SD (optional)
        session_apn: PDU session APN
        session_type: IPv4 | IPv6 | IPv4v6
        tun_netmask: TUN interface netmask
    """
    _empty_cfg = lambda gsl: UeConfiguration(
        gnb_search_list=gsl,
        supi=supi, mcc=mcc, mnc=mnc,
        key=key, op=op, op_type=op_type,
        slice_sst=slice_sst, slice_sd=slice_sd,
        session_apn=session_apn, session_type=session_type,
        tun_netmask=tun_netmask,
    )
    try:
        if gnb_search_list == "auto":
            gnb_list = list_gnbs()
            if gnb_list.status == "success" and gnb_list.count > 0:
                ip_result = inspect_container_ip(gnb_list.containers[0].name)
                gnb_search_list = ip_result.logs if ip_result.status == "success" else "127.0.0.1"
            else:
                gnb_search_list = "127.0.0.1"
            print(f"Auto-detected gNB IP: {gnb_search_list}", file=sys.stderr)

        validate_ip(gnb_search_list)
        validate_mcc(mcc)
        validate_mnc(mnc)
        validate_op_type(op_type)
        validate_session_type(session_type)
        if supi is not None:
            validate_supi(supi)
        if key is not None:
            validate_hex_key(key, "key")
        if op is not None:
            validate_hex_key(op, "op")

        runtime = get_container_runtime()
        is_alpine = detect_image_os(_UE_IMAGE) == "alpine"

        if container_name:
            validate_container_name(container_name, "ue")
        else:
            container_name = f"ue-{generate_random_suffix()}"

        cmd = [runtime, "run", "-d", "--name", container_name]
        if is_alpine:
            cmd += ["--privileged", "--cap-add=NET_ADMIN", "--network", "host", _UE_IMAGE]
        else:
            cmd += ["--cap-add=NET_ADMIN", "--device", "/dev/net/tun",
                    "--network", "host", _UE_IMAGE]

        result = run_container_command(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return UeCreateResponse(
                status="error", container_id="", container_name="",
                configuration=_empty_cfg(gnb_search_list), message=result.stderr,
            )

        container_id = result.stdout.strip()

        # Update gnbSearchList
        r = _exec(runtime, container_id,
                  ["sed", "-i", f"s/- 127\\.0\\.0\\.1/- {gnb_search_list}/", UE_CFG])
        if r.returncode != 0:
            return UeCreateResponse(
                status="error", container_id=container_id, container_name=container_name,
                configuration=_empty_cfg(gnb_search_list),
                message=f"Failed to update gnbSearchList: {r.stderr}",
            )

        # Apply additional parametric config
        for cmd in ue_config_cmds(
            supi=supi, mcc=mcc, mnc=mnc, key=key, op=op, op_type=op_type,
            slice_sst=slice_sst, slice_sd=slice_sd,
            session_apn=session_apn, session_type=session_type,
            tun_netmask=tun_netmask,
        ):
            r = _exec(runtime, container_id, cmd)
            if r.returncode != 0:
                return UeCreateResponse(
                    status="error", container_id=container_id,
                    container_name=container_name,
                    configuration=_empty_cfg(gnb_search_list),
                    message=f"Config command failed ({cmd[0]}): {r.stderr}",
                )

        return UeCreateResponse(
            status="success", container_id=container_id, container_name=container_name,
            configuration=_empty_cfg(gnb_search_list),
        )

    except Exception as e:
        gsl = gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=_empty_cfg(gsl), message=str(e),
        )


@mcp.tool()
def list_ues() -> UeListResponse:
    """List all UE containers."""
    try:
        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "ps", "-a", "--filter", "name=ue-",
             "--format", "{{.ID}}|{{.Names}}|{{.Status}}|{{.CreatedAt}}"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return UeListResponse(status="error", containers=[], count=0,
                                  message=result.stderr)
        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                cid, name, status, created = line.split('|', 3)
                containers.append(UeContainer(id=cid, name=name, status=status,
                                              created=created))
        return UeListResponse(status="success", containers=containers,
                              count=len(containers))
    except Exception as e:
        return UeListResponse(status="error", containers=[], count=0, message=str(e))


@mcp.tool()
def delete_ue(container_id_or_name: str) -> UeOperationResponse:
    """Delete a UE container (stop then remove).

    Args:
        container_id_or_name: Container ID or name
    """
    try:
        if _is_container_id(container_id_or_name):
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "ue")

        runtime = get_container_runtime()
        for sub_cmd, verb in [("stop", "stop"), ("rm", "remove")]:
            r = run_container_command(
                [runtime, sub_cmd, container_id_or_name], capture_output=True, text=True
            )
            if r.returncode != 0:
                return UeOperationResponse(
                    status="error", message=f"Failed to {verb} container: {r.stderr}",
                    container=container_id_or_name,
                )
        return UeOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name,
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e),
                                   container=container_id_or_name)


@mcp.tool()
def get_ue_logs(container_id_or_name: str, lines: int = 100) -> UeOperationResponse:
    """Get logs from a UE container.

    Args:
        container_id_or_name: Container ID or name
        lines: Number of lines to retrieve (default: 100)
    """
    try:
        if _is_container_id(container_id_or_name):
            validate_container_id(container_id_or_name)
        else:
            validate_container_name(container_id_or_name, "ue")

        runtime = get_container_runtime()
        result = run_container_command(
            [runtime, "logs", f"--tail={lines}", container_id_or_name],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return UeOperationResponse(status="error", message=result.stderr,
                                       container=container_id_or_name)
        return UeOperationResponse(status="success", message="Logs retrieved successfully",
                                   container=container_id_or_name, logs=result.stdout)
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e),
                                   container=container_id_or_name)


@mcp.tool()
def attach_ue_to_gnb(
    ue_container_id_or_name: str, gnb_container_id_or_name: str
) -> UeOperationResponse:
    """Update UE gnbSearchList with the gNB IP and start nr-ue.

    Args:
        ue_container_id_or_name: UE container ID or name
        gnb_container_id_or_name: gNB container ID or name
    """
    try:
        if _is_container_id(ue_container_id_or_name):
            validate_container_id(ue_container_id_or_name)
        else:
            validate_container_name(ue_container_id_or_name, "ue")

        if _is_container_id(gnb_container_id_or_name):
            validate_container_id(gnb_container_id_or_name)
        else:
            validate_container_name(gnb_container_id_or_name, "gnb")

        runtime = get_container_runtime()

        gnb_ip_result = inspect_container_ip(gnb_container_id_or_name)
        if gnb_ip_result.status != "success" or not gnb_ip_result.logs:
            return UeOperationResponse(
                status="error",
                message=(f"Could not determine IP for gNB {gnb_container_id_or_name}:"
                         f" {gnb_ip_result.message}"),
                container=ue_container_id_or_name,
            )
        gnb_ip = gnb_ip_result.logs.strip()

        r = _exec(runtime, ue_container_id_or_name,
                  ["sed", "-i", f"s/- .*/- {gnb_ip}/", UE_CFG])
        if r.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to update gnbSearchList with {gnb_ip}: {r.stderr}",
                container=ue_container_id_or_name,
            )

        r = _exec(runtime, ue_container_id_or_name,
                  ["sh", "-c",
                   "nohup /usr/local/bin/nr-ue -c /etc/ueransim/open5gs-ue.yaml"
                   " > /proc/1/fd/1 2>&1 &"])
        if r.returncode != 0:
            return UeOperationResponse(
                status="error", message=f"Failed to start nr-ue: {r.stderr}",
                container=ue_container_id_or_name,
            )

        time.sleep(3)

        gnb_s = _exec(runtime, gnb_container_id_or_name,
                      ["sh", "-c",
                       "pgrep -f nr-gnb && echo 'gNB process is running'"
                       " || echo 'gNB process not found'"])
        ue_s = _exec(runtime, ue_container_id_or_name,
                     ["sh", "-c",
                      "pgrep -f nr-ue && echo 'UE process is running'"
                      " || echo 'UE process not found'"])

        details, ok = [], False
        if gnb_s.returncode == 0:
            running = "process is running" in gnb_s.stdout
            details.append("gNB: nr-gnb active" if running else "gNB: nr-gnb not running")
            ok = ok or running
        if ue_s.returncode == 0:
            running = "process is running" in ue_s.stdout
            details.append("UE: nr-ue active" if running else "UE: nr-ue not running")
            ok = ok or running

        return UeOperationResponse(
            status="success" if ok else "warning",
            message=(f"UE {ue_container_id_or_name} attached to gNB"
                     f" {gnb_container_id_or_name}."
                     f" {'Processes running' if ok else 'Some processes not running'}."
                     f" {'; '.join(details)}"),
            container=ue_container_id_or_name,
            logs=f"gNB:\n{gnb_s.stdout}\n\nUE:\n{ue_s.stdout}",
        )
    except Exception as e:
        return UeOperationResponse(status="error", message=str(e),
                                   container=ue_container_id_or_name)


@mcp.tool()
def edit_exist_container(
    container_id_or_name: str,
    config_type: str = "gnb_search_list",
    config_value: str = "127.0.0.1",
) -> UeOperationResponse:
    """Edit a configuration field inside an existing container.

    Args:
        container_id_or_name: Container ID or name (gnb-* or ue-*)
        config_type: Field to change. GNB types: ngap_ip, gtp_ip, amf_ip, mcc, mnc,
            tac, nci, id_length, cell_access_type, ignore_stream_ids, gtp_advertise_ip,
            slice (value: "sst" or "sst,sd").
            UE types: gnb_search_list, supi, key, op, op_type, mcc, mnc, session_apn,
            session_type, tun_netmask, slice (value: "sst" or "sst,sd").
        config_value: New value as a string
    """
    try:
        validate_existing_container(container_id_or_name)
        runtime = get_container_runtime()
        ctype = _detect_type(runtime, container_id_or_name)

        # ── IP-validated types ──────────────────────────────────────────────
        _ip_types = {"ngap_ip", "gtp_ip", "amf_ip", "gtp_advertise_ip",
                     "gnb_search_list"}
        if config_type in _ip_types:
            validate_ip(config_value)

        # ── Build the command(s) ───────────────────────────────────────────
        cmds = _edit_commands(config_type, config_value, ctype)
        if cmds is None:
            return UeOperationResponse(
                status="error",
                message=(f"Unsupported config_type '{config_type}' for container"
                         f" type '{ctype}'. Check the docstring for valid types."),
                container=container_id_or_name,
            )

        for cmd in cmds:
            r = _exec(runtime, container_id_or_name, cmd)
            if r.returncode != 0:
                return UeOperationResponse(
                    status="error",
                    message=f"Failed to apply {config_type}: {r.stderr}",
                    container=container_id_or_name,
                )

        return UeOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} updated: {config_type}={config_value}",
            container=container_id_or_name,
        )

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e),
                                   container=container_id_or_name)
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = f"Container {container_id_or_name} not found"
        return UeOperationResponse(status="error", message=msg,
                                   container=container_id_or_name)


def _edit_commands(config_type: str, config_value: str, ctype: str):
    """Return List[List[str]] of commands for the given config_type, or None if unknown."""
    f_gnb, f_ue = GNB_CFG, UE_CFG

    # Shared "slice" type — format: "sst" or "sst,sd"
    if config_type == "slice":
        parts = config_value.split(",")
        sst = int(parts[0])
        sd = int(parts[1]) if len(parts) > 1 else None
        if ctype == "gnb":
            return gnb_slice_cmds(sst, sd)
        if ctype == "ue":
            return ue_slice_cmds(sst, sd)
        return None

    # gNB-only types
    _gnb_map = {
        "ngap_ip":          [["sed", "-i", f"s/ngapIp: .*/ngapIp: {config_value}/", f_gnb]],
        "gtp_ip":           [["sed", "-i", f"s/gtpIp: .*/gtpIp: {config_value}/", f_gnb]],
        "amf_ip":           [["sed", "-i", f"s/- address: .*/- address: {config_value}/", f_gnb]],
        "tac":              [["sed", "-i", f"s/^tac: .*/tac: {config_value}/", f_gnb]],
        "nci":              [["sed", "-i", f"s/^nci: .*/nci: '{config_value}'/", f_gnb]],
        "id_length":        [["sed", "-i", f"s/^idLength: .*/idLength: {config_value}/", f_gnb]],
        "cell_access_type": [["sed", "-i",
                               f"s/^cellAccessType: .*/cellAccessType: {config_value}/", f_gnb]],
        "ignore_stream_ids":[["sed", "-i",
                               f"s/^ignoreStreamIds: .*/ignoreStreamIds: {config_value}/", f_gnb]],
        "gtp_advertise_ip": gnb_gtp_advertise_cmds(config_value),
    }

    # UE-only types
    _ue_map = {
        "gnb_search_list":  [["sed", "-i",
                               f"s/^  - [0-9].*/  - {config_value}/", f_ue]],
        "supi":             [["sed", "-i", f"s/^supi: .*/supi: '{config_value}'/", f_ue]],
        "key":              [["sed", "-i", f"s/^key: .*/key: '{config_value}'/", f_ue]],
        "op":               [["sed", "-i", f"s/^op: .*/op: '{config_value}'/", f_ue]],
        "op_type":          [["sed", "-i", f"s/^opType: .*/opType: '{config_value}'/", f_ue]],
        "session_apn":      [["sed", "-i",
                               f"s/^    apn: .*/    apn: '{config_value}'/", f_ue]],
        "session_type":     [["sed", "-i",
                               f"s/^  - type: .*/  - type: '{config_value}'/", f_ue]],
        "tun_netmask":      [["sed", "-i",
                               f"s/^tunNetmask: .*/tunNetmask: '{config_value}'/", f_ue]],
    }

    # mcc and mnc apply to whichever file matches the container type
    if config_type in ("mcc", "mnc"):
        target = f_gnb if ctype == "gnb" else f_ue if ctype == "ue" else None
        if target is None:
            return None
        return [["sed", "-i", f"s/^{config_type}: .*/{config_type}: '{config_value}'/", target]]

    if config_type in _gnb_map:
        return _gnb_map[config_type]
    if config_type in _ue_map:
        return _ue_map[config_type]
    return None
