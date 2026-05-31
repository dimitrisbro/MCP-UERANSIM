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
from .validators import validate_ip, validate_container_id, validate_container_name
from .docker_utils import (
    get_container_runtime, run_container_command, detect_image_os, validate_existing_container,
)

_GNB_IMAGE = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-gnb:latest"
_UE_IMAGE  = "ghcr.io/apelgroup/mcp-ueransim-new/ueransim-ue:latest"


def _is_container_id(value: str) -> bool:
    return (re.match(r'^[0-9a-fA-F]+$', value)
            and len(value) in (12, 64))


# ── gNB tools ─────────────────────────────────────────────────────────────────

@mcp.tool()
def create_gnb(
    amf_address: str = "127.0.0.5",
    amf_port: str = "38412",
    container_name: Optional[str] = None,
) -> GnbCreateResponse:
    """Create a new gNB container.

    Args:
        amf_address: AMF IP address
        amf_port: AMF port
        container_name: Optional container name (auto-generated if omitted)

    Returns:
        GnbCreateResponse: Information about the new container
    """
    try:
        validate_ip(amf_address)
        runtime = get_container_runtime()

        if container_name:
            validate_container_name(container_name, "gnb")
        else:
            container_name = f"gnb-{generate_random_suffix()}"

        cmd = [runtime, "run", "-d", "--name", container_name, _GNB_IMAGE]
        result = run_container_command(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id="", container_name="",
                configuration=GnbConfiguration(link_ip="", ngap_ip="", gtp_ip="",
                                               amf_address=amf_address, amf_port=amf_port),
                message=result.stderr,
            )

        container_id = result.stdout.strip()

        inspect_result = run_container_command(
            [runtime, "inspect", "-f",
             "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}", container_id],
            capture_output=True, text=True,
        )
        if inspect_result.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id=container_id, container_name=container_name,
                configuration=GnbConfiguration(link_ip="", ngap_ip="", gtp_ip="",
                                               amf_address=amf_address, amf_port=amf_port),
                message=f"Failed to get container IP: {inspect_result.stderr}",
            )

        ip = inspect_result.stdout.strip()

        for field, pattern in [
            ("linkIp", f"s/linkIp: .*/linkIp: {ip}/"),
            ("ngapIp", f"s/ngapIp: .*/ngapIp: {ip}/"),
            ("gtpIp",  f"s/gtpIp: .*/gtpIp: {ip}/"),
        ]:
            r = run_container_command(
                [runtime, "exec", container_id, "sed", "-i", pattern,
                 "/etc/ueransim/open5gs-gnb.yaml"],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                return GnbCreateResponse(
                    status="error", container_id=container_id, container_name=container_name,
                    configuration=GnbConfiguration(link_ip=ip, ngap_ip=ip, gtp_ip=ip,
                                                   amf_address=amf_address, amf_port=amf_port),
                    message=f"Failed to update {field}: {r.stderr}",
                )

        r = run_container_command(
            [runtime, "exec", container_id, "sed", "-i",
             f"s/- address: .*/- address: {amf_address}/",
             "/etc/ueransim/open5gs-gnb.yaml"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return GnbCreateResponse(
                status="error", container_id=container_id, container_name=container_name,
                configuration=GnbConfiguration(link_ip=ip, ngap_ip=ip, gtp_ip=ip,
                                               amf_address=amf_address, amf_port=amf_port),
                message=f"Failed to update AMF address: {r.stderr}",
            )

        return GnbCreateResponse(
            status="success", container_id=container_id, container_name=container_name,
            configuration=GnbConfiguration(link_ip=ip, ngap_ip=ip, gtp_ip=ip,
                                           amf_address=amf_address, amf_port=amf_port),
        )

    except ValueError as e:
        return GnbCreateResponse(
            status="error", container_id="", container_name="",
            configuration=GnbConfiguration(link_ip="", ngap_ip="", gtp_ip="",
                                           amf_address=amf_address, amf_port=amf_port),
            message=str(e),
        )
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = "Container runtime (Docker) not found or not accessible"
        elif "permission" in msg.lower():
            msg = f"Permission denied: {msg}"
        return GnbCreateResponse(
            status="error", container_id="", container_name="",
            configuration=GnbConfiguration(link_ip="", ngap_ip="", gtp_ip="",
                                           amf_address=amf_address, amf_port=amf_port),
            message=msg,
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
            return GnbListResponse(status="error", containers=[], count=0, message=result.stderr)

        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                cid, name, status, created = line.split('|', 3)
                containers.append(GnbContainer(id=cid, name=name, status=status, created=created))

        return GnbListResponse(status="success", containers=containers, count=len(containers))

    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower() or "command not found" in msg.lower():
            msg = "Container runtime (Docker) not found"
        return GnbListResponse(status="error", containers=[], count=0, message=msg)


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
                    status="error",
                    message=f"Failed to {verb} container: {r.stderr}",
                    container=container_id_or_name,
                )

        return GnbOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name,
        )

    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e), container=container_id_or_name)
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = f"Container {container_id_or_name} not found"
        elif "already stopped" in msg.lower():
            msg = f"Container {container_id_or_name} is already stopped"
        return GnbOperationResponse(status="error", message=msg, container=container_id_or_name)


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
            return GnbOperationResponse(
                status="error", message=result.stderr, container=container_id_or_name
            )
        return GnbOperationResponse(
            status="success", message="Logs retrieved successfully",
            container=container_id_or_name, logs=result.stdout,
        )

    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=container_id_or_name)


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

        r = run_container_command(
            [runtime, "exec", container_id_or_name, "sed", "-i",
             f"s/- address: .*/- address: {amf_address}/",
             "/etc/ueransim/open5gs-gnb.yaml"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return GnbOperationResponse(
                status="error", message=f"Failed to update AMF address: {r.stderr}",
                container=container_id_or_name,
            )

        r = run_container_command(
            [runtime, "exec", "-d", container_id_or_name, "sh", "-c",
             "nohup /usr/local/bin/nr-gnb -c /etc/ueransim/open5gs-gnb.yaml"
             " > /proc/1/fd/1 2>&1 &"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return GnbOperationResponse(
                status="error", message=f"Failed to start nr-gnb: {r.stderr}",
                container=container_id_or_name,
            )

        time.sleep(2)

        status_r = run_container_command(
            [runtime, "exec", container_id_or_name, "sh", "-c",
             "pgrep -f nr-gnb && echo 'gNB process is running' || echo 'gNB process not found'"],
            capture_output=True, text=True,
        )
        process_ok = status_r.returncode == 0 and "process is running" in status_r.stdout

        return GnbOperationResponse(
            status="success",
            message=(f"Container {container_id_or_name} connected to core with AMF {amf_address}."
                     f" {'Process started.' if process_ok else 'Process may not be running.'}"),
            container=container_id_or_name,
            logs=status_r.stdout if status_r.returncode == 0 else None,
        )

    except Exception as e:
        return GnbOperationResponse(status="error", message=str(e), container=container_id_or_name)


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
            container=container_id_or_name,
            logs=ip,
        )

    except ValueError as e:
        return GnbOperationResponse(status="error", message=str(e), container=container_id_or_name)
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = f"Container {container_id_or_name} not found or not accessible"
        elif "permission" in msg.lower():
            msg = f"Permission denied: {msg}"
        return GnbOperationResponse(status="error", message=msg, container=container_id_or_name)


# ── UE tools ──────────────────────────────────────────────────────────────────

@mcp.tool()
def create_ue(
    gnb_search_list: str = "127.0.0.1",
    container_name: Optional[str] = None,
) -> UeCreateResponse:
    """Create a new UE container.

    Args:
        gnb_search_list: gNB IP for Radio Link Simulation, or 'auto' to use first available gNB
        container_name: Optional container name (auto-generated if omitted)
    """
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
            cmd += ["--cap-add=NET_ADMIN", "--device", "/dev/net/tun", "--network", "host",
                    _UE_IMAGE]

        result = run_container_command(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return UeCreateResponse(
                status="error", container_id="", container_name="",
                configuration=UeConfiguration(gnb_search_list=gnb_search_list),
                message=result.stderr,
            )

        container_id = result.stdout.strip()

        r = run_container_command(
            [runtime, "exec", container_id, "sed", "-i",
             f"s/- 127\\.0\\.0\\.1/- {gnb_search_list}/",
             "/etc/ueransim/open5gs-ue.yaml"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return UeCreateResponse(
                status="error", container_id=container_id, container_name=container_name,
                configuration=UeConfiguration(gnb_search_list=gnb_search_list),
                message=f"Container created but failed to update gnbSearchList: {r.stderr}",
            )

        return UeCreateResponse(
            status="success", container_id=container_id, container_name=container_name,
            configuration=UeConfiguration(gnb_search_list=gnb_search_list),
        )

    except Exception as e:
        return UeCreateResponse(
            status="error", container_id="", container_name="",
            configuration=UeConfiguration(
                gnb_search_list=gnb_search_list if 'gnb_search_list' in locals() else "127.0.0.1"
            ),
            message=str(e),
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
            return UeListResponse(status="error", containers=[], count=0, message=result.stderr)

        containers = []
        for line in result.stdout.strip().split('\n'):
            if line:
                cid, name, status, created = line.split('|', 3)
                containers.append(UeContainer(id=cid, name=name, status=status, created=created))

        return UeListResponse(status="success", containers=containers, count=len(containers))

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
                    status="error",
                    message=f"Failed to {verb} container: {r.stderr}",
                    container=container_id_or_name,
                )

        return UeOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} successfully deleted",
            container=container_id_or_name,
        )

    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=container_id_or_name)


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
            return UeOperationResponse(
                status="error", message=result.stderr, container=container_id_or_name
            )
        return UeOperationResponse(
            status="success", message="Logs retrieved successfully",
            container=container_id_or_name, logs=result.stdout,
        )

    except Exception as e:
        return UeOperationResponse(status="error", message=str(e), container=container_id_or_name)


@mcp.tool()
def attach_ue_to_gnb(
    ue_container_id_or_name: str, gnb_container_id_or_name: str
) -> UeOperationResponse:
    """Update the UE's gnbSearchList with the gNB IP and start the nr-ue process.

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

        r = run_container_command(
            [runtime, "exec", ue_container_id_or_name, "sed", "-i",
             f"s/- .*/- {gnb_ip}/", "/etc/ueransim/open5gs-ue.yaml"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return UeOperationResponse(
                status="error",
                message=f"Failed to update gnbSearchList with gNB IP {gnb_ip}: {r.stderr}",
                container=ue_container_id_or_name,
            )

        r = run_container_command(
            [runtime, "exec", "-d", ue_container_id_or_name, "sh", "-c",
             "nohup /usr/local/bin/nr-ue -c /etc/ueransim/open5gs-ue.yaml"
             " > /proc/1/fd/1 2>&1 &"],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return UeOperationResponse(
                status="error", message=f"Failed to start nr-ue: {r.stderr}",
                container=ue_container_id_or_name,
            )

        time.sleep(3)

        gnb_status = run_container_command(
            [runtime, "exec", gnb_container_id_or_name, "sh", "-c",
             "pgrep -f nr-gnb && echo 'gNB process is running' || echo 'gNB process not found'"],
            capture_output=True, text=True,
        )
        ue_status = run_container_command(
            [runtime, "exec", ue_container_id_or_name, "sh", "-c",
             "pgrep -f nr-ue && echo 'UE process is running' || echo 'UE process not found'"],
            capture_output=True, text=True,
        )

        details = []
        ok = False
        if gnb_status.returncode == 0:
            running = "process is running" in gnb_status.stdout
            details.append("gNB: nr-gnb active" if running else "gNB: nr-gnb not running")
            ok = ok or running
        if ue_status.returncode == 0:
            running = "process is running" in ue_status.stdout
            details.append("UE: nr-ue active" if running else "UE: nr-ue not running")
            ok = ok or running

        logs = (f"gNB process check:\n{gnb_status.stdout}\n\nUE process check:\n{ue_status.stdout}")

        return UeOperationResponse(
            status="success" if ok else "warning",
            message=(f"UE {ue_container_id_or_name} attached to gNB {gnb_container_id_or_name}."
                     f" {'Processes running' if ok else 'Some processes not running'}."
                     f" {'; '.join(details)}"),
            container=ue_container_id_or_name,
            logs=logs,
        )

    except Exception as e:
        return UeOperationResponse(
            status="error", message=str(e), container=ue_container_id_or_name
        )


@mcp.tool()
def edit_exist_container(
    container_id_or_name: str,
    config_type: str = "gnb_search_list",
    config_value: str = "127.0.0.1",
) -> UeOperationResponse:
    """Edit a configuration field inside an existing container.

    Args:
        container_id_or_name: Container ID or name
        config_type: One of gnb_search_list, ngap_ip, gtp_ip, amf_ip
        config_value: New value (IP address)
    """
    try:
        validate_existing_container(container_id_or_name)
        if config_type in ("gnb_search_list", "ngap_ip", "gtp_ip", "amf_ip"):
            validate_ip(config_value)

        runtime = get_container_runtime()

        patterns = {
            "gnb_search_list": (f"s/- 127\\.0\\.0\\.1/- {config_value}/",
                                "/etc/ueransim/open5gs-ue.yaml"),
            "ngap_ip":         (f"s/ngapIp: .*/ngapIp: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
            "gtp_ip":          (f"s/gtpIp: .*/gtpIp: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
            "amf_ip":          (f"s/- address: .*/- address: {config_value}/",
                                "/etc/ueransim/open5gs-gnb.yaml"),
        }
        if config_type not in patterns:
            return UeOperationResponse(
                status="error", message=f"Unsupported config type: {config_type}",
                container=container_id_or_name,
            )

        sed_pattern, config_file = patterns[config_type]
        r = run_container_command(
            [runtime, "exec", container_id_or_name, "sed", "-i", sed_pattern, config_file],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            return UeOperationResponse(
                status="error", message=f"Failed to update {config_type}: {r.stderr}",
                container=container_id_or_name,
            )

        run_container_command(
            [runtime, "exec", container_id_or_name, "sh", "-c",
             f"echo 'Configuration updated: {config_type}={config_value}'"
             " >> /var/log/ueransim.log"],
        )

        return UeOperationResponse(
            status="success",
            message=f"Container {container_id_or_name} configuration updated:"
                    f" {config_type}={config_value}",
            container=container_id_or_name,
        )

    except ValueError as e:
        return UeOperationResponse(status="error", message=str(e), container=container_id_or_name)
    except Exception as e:
        msg = str(e)
        if "not found" in msg.lower():
            msg = f"Container {container_id_or_name} not found or not accessible"
        elif "no such file" in msg.lower():
            msg = "Configuration file not found in container"
        return UeOperationResponse(status="error", message=msg, container=container_id_or_name)
